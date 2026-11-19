"""审计脚本的单元测试。

用临时目录构造合成数据集，验证审计逻辑的正确性：
- data.yaml 解析
- 图片/标签一一对应检查
- 类别 id 越界与坐标越界检测
- 空标签比例计算
- 跨 split 重复图检测（SHA256）
- 报告渲染

测试不触碰真实 ``dataset/`` 目录 —— 全部在 tmp_path 中构造。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ 不属于 app 包，需显式加入 sys.path 才能导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from audit_dataset import (  # noqa: E402
    DatasetSpec,
    audit_dataset,
    build_report,
    find_cross_split_duplicates,
    find_within_split_duplicates,
    parse_data_yaml,
)


def _write_yaml(path: Path, names: list[str], nc: int) -> None:
    """写出一个最小可用的 data.yaml。"""
    joined = ", ".join(f"'{n}'" for n in names)
    path.write_text(
        "train: ../train/images\nval: ../valid/images\ntest: ../test/images\n\n"
        f"nc: {nc}\nnames: [{joined}]\n",
        encoding="utf-8",
    )


def _make_split(
    root: Path,
    split: str,
    items: list[tuple[str, str | None]],
    image_bytes: dict[str, bytes] | None = None,
) -> None:
    """构造一个 split 目录。

    items 的每一项为 ``(stem, label_content)``：
    label_content 为 None 表示只有图片没有标签；
    空字符串表示空标签文件（存在但无标注行）。

    image_bytes 可显式指定图片内容，用于构造「内容完全相同」的跨 split 重复图；
    未指定时按 stem+split 生成内容，保证同一 split 内图片互不相同。
    """
    images_dir = root / split / "images"
    labels_dir = root / split / "labels"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    for stem, label_content in items:
        payload = (
            image_bytes[stem]
            if image_bytes and stem in image_bytes
            else f"IMAGE-{stem}-{split}".encode()
        )
        (images_dir / f"{stem}.jpg").write_bytes(payload)
        if label_content is not None:
            (labels_dir / f"{stem}.txt").write_text(label_content, encoding="utf-8")


def _build_dataset(root: Path, names: list[str]) -> DatasetSpec:
    """构造一个三 split 的合成数据集。"""
    root.mkdir(parents=True, exist_ok=True)
    _write_yaml(root / "data.yaml", names, len(names))
    return DatasetSpec(
        name=root.name,
        root=root,
        names=tuple(names),
        declared_nc=len(names),
    )


# ---------------------------------------------------------------------------
# data.yaml 解析
# ---------------------------------------------------------------------------


def test_parse_data_yaml_reads_names_and_nc(tmp_path: Path) -> None:
    yaml_path = tmp_path / "data.yaml"
    yaml_path.write_text(
        "# 注释行\ntrain: ../train/images\nnc: 3\nnames: ['Cyclists', 'helmet', 'no helmet']\n",
        encoding="utf-8",
    )

    names, nc = parse_data_yaml(yaml_path)

    assert names == ("Cyclists", "helmet", "no helmet")
    assert nc == 3


def test_parse_data_yaml_tolerates_comments_and_missing_nc(tmp_path: Path) -> None:
    yaml_path = tmp_path / "data.yaml"
    yaml_path.write_text(
        "# 顶部注释\nnames: ['helmet', 'no helmet']\nroboflow:\n  version: 2\n",
        encoding="utf-8",
    )

    names, nc = parse_data_yaml(yaml_path)

    assert names == ("helmet", "no helmet")
    assert nc == -1


# ---------------------------------------------------------------------------
# 匹配与统计
# ---------------------------------------------------------------------------


def test_audit_counts_images_labels_and_instances(tmp_path: Path) -> None:
    spec = _build_dataset(tmp_path / "ds", ["Cyclists", "helmet", "no helmet"])
    _make_split(
        spec.root,
        "train",
        [
            ("a", "0 0.5 0.5 0.2 0.2\n1 0.5 0.4 0.1 0.1\n"),
            ("b", "0 0.3 0.3 0.1 0.1\n"),
        ],
    )
    _make_split(spec.root, "valid", [("c", "2 0.5 0.5 0.1 0.1\n")])
    _make_split(spec.root, "test", [])

    audit = audit_dataset(spec)
    train = audit.splits["train"]

    assert train.image_count == 2
    assert train.label_count == 2
    assert train.total_instances == 3
    # class 0 出现 2 次，class 1 出现 1 次
    assert train.instance_counts[0] == 2
    assert train.instance_counts[1] == 1
    assert train.instance_counts[2] == 0


def test_audit_detects_images_without_labels(tmp_path: Path) -> None:
    spec = _build_dataset(tmp_path / "ds", ["helmet"])
    _make_split(spec.root, "train", [("a", "0 0.5 0.5 0.1 0.1\n"), ("b", None)])

    audit = audit_dataset(spec)

    assert audit.splits["train"].images_without_labels == ["b"]
    assert audit.splits["train"].labels_without_images == []


def test_audit_detects_labels_without_images(tmp_path: Path) -> None:
    spec = _build_dataset(tmp_path / "ds", ["helmet"])
    _make_split(spec.root, "train", [("a", "0 0.5 0.5 0.1 0.1\n")])

    # 手动放一个没有对应图片的标签
    orphan = spec.root / "train" / "labels" / "orphan.txt"
    orphan.write_text("0 0.5 0.5 0.1 0.1\n", encoding="utf-8")

    audit = audit_dataset(spec)

    assert audit.splits["train"].labels_without_images == ["orphan"]


def test_audit_tracks_empty_label_ratio(tmp_path: Path) -> None:
    spec = _build_dataset(tmp_path / "ds", ["helmet"])
    _make_split(
        spec.root,
        "train",
        [
            ("a", "0 0.5 0.5 0.1 0.1\n"),
            ("b", ""),  # 空标签文件
            ("c", "   \n\n"),  # 只有空白行，同样算空标签
        ],
    )

    audit = audit_dataset(spec)
    train = audit.splits["train"]

    assert len(train.empty_label_files) == 2
    assert train.empty_label_ratio == pytest.approx(2 / 3)


def test_audit_ignores_cache_files(tmp_path: Path) -> None:
    """labels.cache 不是数据本体，不应被计入标签数。"""
    spec = _build_dataset(tmp_path / "ds", ["helmet"])
    _make_split(spec.root, "train", [("a", "0 0.5 0.5 0.1 0.1\n")])
    (spec.root / "train" / "labels" / "labels.cache").write_bytes(b"\x00\x01cache")

    audit = audit_dataset(spec)

    assert audit.splits["train"].label_count == 1


# ---------------------------------------------------------------------------
# 越界检查
# ---------------------------------------------------------------------------


def test_audit_detects_out_of_range_class_id(tmp_path: Path) -> None:
    spec = _build_dataset(tmp_path / "ds", ["helmet", "no helmet"])
    _make_split(spec.root, "train", [("a", "0 0.5 0.5 0.1 0.1\n5 0.5 0.5 0.1 0.1\n")])

    audit = audit_dataset(spec)
    train = audit.splits["train"]

    assert train.out_of_range_class_ids == [("a", 5)]
    # 越界 id 仍计入实例总数（反映真实数据状况）
    assert train.instance_counts[5] == 1


def test_audit_detects_out_of_range_coords(tmp_path: Path) -> None:
    spec = _build_dataset(tmp_path / "ds", ["helmet"])
    _make_split(
        spec.root,
        "train",
        [("a", "0 1.5 0.5 0.1 0.1\n0 0.5 -0.2 0.1 0.1\n0 0.5 0.5 -0.1 0.2\n")],
    )

    audit = audit_dataset(spec)
    train = audit.splits["train"]

    # cx=1.5、cy=-0.2、w=-0.1 三处越界
    assert len(train.out_of_range_coords) == 3


def test_audit_accepts_coords_at_boundaries(tmp_path: Path) -> None:
    """0 与 1 是合法边界值，不应被误报。"""
    spec = _build_dataset(tmp_path / "ds", ["helmet"])
    _make_split(spec.root, "train", [("a", "0 0 0 1 1\n0 1 1 1 1\n")])

    audit = audit_dataset(spec)

    assert audit.splits["train"].out_of_range_coords == []


def test_audit_detects_malformed_label_lines(tmp_path: Path) -> None:
    spec = _build_dataset(tmp_path / "ds", ["helmet"])
    _make_split(
        spec.root,
        "train",
        [("a", "0 0.5 0.5 0.1 0.1\n0 0.5 0.5\nnot-a-number 0.5 0.5 0.1 0.1\n")],
    )

    audit = audit_dataset(spec)
    train = audit.splits["train"]

    # 字段不足 + 非数字，两行都应被标记
    assert len(train.malformed_lines) == 2


# ---------------------------------------------------------------------------
# 泄漏检测
# ---------------------------------------------------------------------------


def test_detects_cross_split_duplicate_images(tmp_path: Path) -> None:
    spec = _build_dataset(tmp_path / "ds", ["helmet"])
    # 相同字节内容 → 相同 SHA256 → 构成跨 split 泄漏
    shared = {"dup": b"IDENTICAL-IMAGE-BYTES"}
    _make_split(spec.root, "train", [("dup", "0 0.5 0.5 0.1 0.1\n")], image_bytes=shared)
    _make_split(spec.root, "valid", [("dup", "0 0.5 0.5 0.1 0.1\n")], image_bytes=shared)
    _make_split(spec.root, "test", [])

    audit = audit_dataset(spec)

    assert len(audit.duplicate_groups) == 1
    _, locations = audit.duplicate_groups[0]
    assert locations == ["train/dup", "valid/dup"]


def test_no_duplicate_when_images_differ(tmp_path: Path) -> None:
    spec = _build_dataset(tmp_path / "ds", ["helmet"])
    _make_split(spec.root, "train", [("a", "0 0.5 0.5 0.1 0.1\n")])
    _make_split(spec.root, "valid", [("a", "0 0.5 0.5 0.1 0.1\n")])

    audit = audit_dataset(spec)

    assert audit.duplicate_groups == []


def test_within_split_duplicates_are_not_leakage(tmp_path: Path) -> None:
    """同 split 内的重复不算泄漏，应由另一个函数单独统计。"""
    spec = _build_dataset(tmp_path / "ds", ["helmet"])
    _make_split(spec.root, "train", [("a", "0 0.5 0.5 0.1 0.1\n"), ("a2", "0 0.5 0.5 0.1 0.1\n")])

    audit = audit_dataset(spec)

    assert audit.duplicate_groups == []
    within = find_within_split_duplicates(audit.splits)
    assert len(within) == 0  # 内容不同（stem 不同 → 写入字节不同）


def test_find_cross_split_duplicates_helper_is_reusable(tmp_path: Path) -> None:
    """辅助函数直接对 splits 字典工作。"""
    spec = _build_dataset(tmp_path / "ds", ["helmet"])
    shared = {"x": b"SAME-BYTES"}
    _make_split(spec.root, "train", [("x", "0 0.5 0.5 0.1 0.1\n")], image_bytes=shared)
    _make_split(spec.root, "valid", [("x", "0 0.5 0.5 0.1 0.1\n")], image_bytes=shared)

    audit = audit_dataset(spec)
    groups = find_cross_split_duplicates(audit.splits)

    assert len(groups) == 1


# ---------------------------------------------------------------------------
# 报告渲染
# ---------------------------------------------------------------------------


def test_report_contains_real_statistics(tmp_path: Path) -> None:
    spec = _build_dataset(tmp_path / "ds", ["helmet", "no helmet"])
    _make_split(spec.root, "train", [("a", "0 0.5 0.5 0.1 0.1\n1 0.5 0.4 0.1 0.1\n")])
    _make_split(spec.root, "valid", [])
    _make_split(spec.root, "test", [])

    audit = audit_dataset(spec)
    report = build_report([audit], spec.root)

    assert "# 数据集审计报告" in report
    assert "只读" in report
    # 真实统计数字
    assert "2" in report
    assert "helmet" in report
    assert "no helmet" in report
    assert "## 六、审计结论" in report


def test_report_flags_matching_problems(tmp_path: Path) -> None:
    spec = _build_dataset(tmp_path / "ds", ["helmet"])
    _make_split(spec.root, "train", [("a", None), ("b", "9 0.5 0.5 0.1 0.1\n")])

    audit = audit_dataset(spec)
    report = build_report([audit], spec.root)

    assert "缺少对应标签文件" in report
    assert "类别 id 越界" in report
    assert "存在不匹配" in report
