"""数据集只读审计：统计规模、类别分布、匹配完整性与跨 split 泄漏风险。

安全约束（硬性）：
- 本脚本对 ``dataset/`` **只读**，不创建、不修改、不删除其中任何文件。
- 唯一的写操作是输出 Markdown 报告到 ``docs文档/数据集审计报告.md``。
- ``*.cache`` 是 YOLO 训练生成的标签缓存索引，不属于数据本体，审计时忽略。

用法::

    python scripts/audit_dataset.py
    python scripts/audit_dataset.py --dataset-dir dataset --output docs文档/数据集审计报告.md
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# 图片扩展名（小写匹配）；与 Roboflow 导出的实际格式一致。
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".webp"})

# 三个 split 的标准名。注意目录名是 valid（不是 val）。
SPLITS = ("train", "valid", "test")

# 坐标归一化容差：浮点换算可能产生极小误差。
COORD_TOLERANCE = 1e-6

# 标签每行期望的字段数。
EXPECTED_LABEL_FIELDS = 5


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DatasetSpec:
    """一个数据集（一个 data.yaml 对应一个目录树）。"""

    name: str
    root: Path
    names: tuple[str, ...]
    declared_nc: int


@dataclass
class SplitAudit:
    """单个 split 的审计结果。"""

    split: str
    image_count: int = 0
    label_count: int = 0
    instance_counts: Counter[int] = field(default_factory=Counter)
    empty_label_files: list[str] = field(default_factory=list)
    images_without_labels: list[str] = field(default_factory=list)
    labels_without_images: list[str] = field(default_factory=list)
    out_of_range_class_ids: list[tuple[str, int]] = field(default_factory=list)
    out_of_range_coords: list[tuple[str, int, str]] = field(default_factory=list)
    malformed_lines: list[tuple[str, int, str]] = field(default_factory=list)
    image_hashes: dict[str, str] = field(default_factory=dict)

    @property
    def total_instances(self) -> int:
        return sum(self.instance_counts.values())

    @property
    def empty_label_ratio(self) -> float:
        if self.label_count == 0:
            return 0.0
        return len(self.empty_label_files) / self.label_count


@dataclass
class DatasetAudit:
    """一个数据集的完整审计结果。"""

    spec: DatasetSpec
    splits: dict[str, SplitAudit] = field(default_factory=dict)
    duplicate_groups: list[tuple[str, list[str]]] = field(default_factory=list)

    @property
    def total_images(self) -> int:
        return sum(s.image_count for s in self.splits.values())

    @property
    def total_labels(self) -> int:
        return sum(s.label_count for s in self.splits.values())

    @property
    def total_instances(self) -> int:
        return sum(s.total_instances for s in self.splits.values())


# ---------------------------------------------------------------------------
# 解析工具
# ---------------------------------------------------------------------------


def parse_data_yaml(path: Path) -> tuple[tuple[str, ...], int]:
    """解析 data.yaml，取出 names 与 nc。

    只支持本项目实际使用的扁平 YAML 形态（``nc:`` 与 ``names: [...]``），
    不引入 PyYAML 依赖 —— 避免为只读审计脚本增加运行时依赖。
    """
    text = path.read_text(encoding="utf-8", errors="replace")

    names: list[str] = []
    nc = -1

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("#") or not line:
            continue
        if line.startswith("nc:"):
            try:
                nc = int(line.split(":", 1)[1].strip())
            except ValueError:
                nc = -1
        elif line.startswith("names:"):
            value = line.split(":", 1)[1].strip()
            if value.startswith("[") and value.endswith("]"):
                inner = value[1:-1]
                names = [item.strip().strip("'\"").strip() for item in inner.split(",")]
                names = [n for n in names if n]

    return tuple(names), nc


def sha256_of(path: Path) -> str:
    """计算文件内容 SHA256；用于跨 split 重复图检测。"""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def list_files(directory: Path, suffixes: frozenset[str]) -> list[Path]:
    """列出目录下匹配扩展名的文件（不含子目录）。"""
    if not directory.is_dir():
        return []
    return sorted(
        (p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in suffixes),
        key=lambda p: p.name,
    )


# ---------------------------------------------------------------------------
# 审计主流程
# ---------------------------------------------------------------------------


def audit_dataset(spec: DatasetSpec) -> DatasetAudit:
    """审计单个数据集的三个 split。"""
    result = DatasetAudit(spec=spec)
    valid_ids = set(range(len(spec.names)))

    for split in SPLITS:
        split_root = spec.root / split
        images_dir = split_root / "images"
        labels_dir = split_root / "labels"

        image_files = list_files(images_dir, IMAGE_SUFFIXES)
        label_files = list_files(labels_dir, frozenset({".txt"}))
        # labels.cache 已被扩展名过滤排除，符合「.cache 不是数据本体」的约定。

        audit = SplitAudit(split=split, image_count=len(image_files), label_count=len(label_files))

        image_by_stem = {p.stem: p for p in image_files}
        label_by_stem = {p.stem: p for p in label_files}

        # ---- 匹配检查 ----
        for stem in sorted(set(image_by_stem) - set(label_by_stem)):
            audit.images_without_labels.append(stem)
        for stem in sorted(set(label_by_stem) - set(image_by_stem)):
            audit.labels_without_images.append(stem)

        # ---- 图片哈希（跨 split 泄漏检测用） ----
        for stem, path in image_by_stem.items():
            audit.image_hashes[stem] = sha256_of(path)

        # ---- 标签内容检查 ----
        for label_file in label_files:
            stem = label_file.stem
            lines = label_file.read_text(encoding="utf-8", errors="replace").splitlines()
            content_lines = [ln for ln in lines if ln.strip()]

            if not content_lines:
                audit.empty_label_files.append(stem)

            for line_no, line in enumerate(content_lines, start=1):
                parts = line.split()
                if len(parts) < EXPECTED_LABEL_FIELDS:
                    audit.malformed_lines.append((stem, line_no, line.strip()))
                    continue

                try:
                    class_id = int(parts[0])
                    coords = [float(v) for v in parts[1:5]]
                except ValueError:
                    audit.malformed_lines.append((stem, line_no, line.strip()))
                    continue

                if class_id not in valid_ids:
                    audit.out_of_range_class_ids.append((stem, class_id))

                audit.instance_counts[class_id] += 1

                # 归一化坐标校验：cx, cy, w, h 必须落在 [0, 1]
                # 每个字段最多记一次问题，避免负宽高被范围检查与负值检查重复计数。
                cx, cy, w, h = coords
                for value, label in (
                    (cx, "cx"),
                    (cy, "cy"),
                    (w, "w"),
                    (h, "h"),
                ):
                    if value < -COORD_TOLERANCE or value > 1 + COORD_TOLERANCE:
                        audit.out_of_range_coords.append((stem, line_no, f"{label}={value}"))

        result.splits[split] = audit

    result.duplicate_groups = find_cross_split_duplicates(result.splits)
    return result


def find_cross_split_duplicates(splits: dict[str, SplitAudit]) -> list[tuple[str, list[str]]]:
    """找出跨 split 的内容重复图。

    返回 ``(sha256, ["train/xxx.jpg", "valid/yyy.jpg"])`` 列表。
    仅统计出现在**不同 split**的重复，同 split 内重复另行标注。
    """
    hash_to_locations: dict[str, list[str]] = defaultdict(list)

    for split_name, audit in splits.items():
        for stem, digest in audit.image_hashes.items():
            hash_to_locations[digest].append(f"{split_name}/{stem}")

    cross_split: list[tuple[str, list[str]]] = []
    for digest, locations in hash_to_locations.items():
        split_names = {loc.split("/", 1)[0] for loc in locations}
        if len(split_names) > 1:
            cross_split.append((digest, sorted(locations)))

    return sorted(cross_split, key=lambda item: item[0])


def find_within_split_duplicates(splits: dict[str, SplitAudit]) -> list[tuple[str, list[str]]]:
    """找出同一 split 内的重复图（数据增强场景常见，非泄漏）。"""
    result: list[tuple[str, list[str]]] = []

    for split_name, audit in splits.items():
        by_hash: dict[str, list[str]] = defaultdict(list)
        for stem, digest in audit.image_hashes.items():
            by_hash[digest].append(stem)

        for digest, stems in by_hash.items():
            if len(stems) > 1:
                result.append((digest, sorted(f"{split_name}/{s}" for s in stems)))

    return sorted(result, key=lambda item: item[0])


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------


def _fmt_int(value: int) -> str:
    return f"{value:,}"


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def render_dataset_section(audit: DatasetAudit) -> str:
    """渲染单个数据集的 Markdown 片段。"""
    spec = audit.spec
    lines: list[str] = []

    lines.append(f"### 数据集 `{spec.name}`")
    lines.append("")
    lines.append(f"- 数据源目录：`{spec.root}`")
    lines.append(
        f"- `data.yaml` 声明 `nc: {spec.declared_nc}`，实际 `names` 数量：{len(spec.names)}"
    )
    names_desc = "、".join(f"`{i}` = {n}" for i, n in enumerate(spec.names))
    lines.append(f"- 类别映射：{names_desc}")
    lines.append("")

    # ---- 规模统计表 ----
    lines.append("| split | 图片数 | 标签数 | 实例总数 | 空标签文件数 | 空标签率 |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for split in SPLITS:
        s = audit.splits.get(split)
        if s is None:
            continue
        lines.append(
            f"| `{split}` | {_fmt_int(s.image_count)} | {_fmt_int(s.label_count)} | "
            f"{_fmt_int(s.total_instances)} | {_fmt_int(len(s.empty_label_files))} | "
            f"{_fmt_pct(s.empty_label_ratio)} |"
        )
    lines.append(
        f"| **合计** | **{_fmt_int(audit.total_images)}** | **{_fmt_int(audit.total_labels)}** | "
        f"**{_fmt_int(audit.total_instances)}** | | |"
    )
    lines.append("")

    # ---- 类别实例分布 ----
    lines.append("**每类实例数分布**")
    lines.append("")
    header = "| 类别 id | 类别名 |"
    divider = "| ---: | --- |"
    for split in SPLITS:
        header += f" {split} |"
        divider += " ---: |"
    header += " 合计 |"
    divider += " ---: |"
    lines.append(header)
    lines.append(divider)

    for class_id, class_name in enumerate(spec.names):
        row = f"| {class_id} | `{class_name}` |"
        total = 0
        for split in SPLITS:
            s = audit.splits.get(split)
            count = s.instance_counts.get(class_id, 0) if s else 0
            total += count
            row += f" {count:,} |"
        row += f" {total:,} |"
        lines.append(row)

    # 越界类别（若存在）
    unknown_total = sum(
        c
        for s in audit.splits.values()
        for cid, c in s.instance_counts.items()
        if cid >= len(spec.names)
    )
    if unknown_total:
        row = "| **越界** | （不在 names 范围内） |"
        for split in SPLITS:
            s = audit.splits.get(split)
            count = (
                sum(c for cid, c in s.instance_counts.items() if cid >= len(spec.names)) if s else 0
            )
            row += f" {count:,} |"
        row += f" {unknown_total:,} |"
        lines.append(row)
    lines.append("")

    return "\n".join(lines)


def render_issue_list(audit: DatasetAudit) -> list[str]:
    """渲染该数据集的问题清单；无问题时返回空列表。"""
    lines: list[str] = []
    spec = audit.spec

    for split in SPLITS:
        s = audit.splits.get(split)
        if s is None:
            continue

        if s.images_without_labels:
            lines.append(
                f"- ⚠️ `{split}`：{len(s.images_without_labels)} 个图片缺少对应标签文件"
                f"（示例：{', '.join(s.images_without_labels[:5])}）"
            )
        if s.labels_without_images:
            lines.append(
                f"- ⚠️ `{split}`：{len(s.labels_without_images)} 个标签文件缺少对应图片"
                f"（示例：{', '.join(s.labels_without_images[:5])}）"
            )
        if s.out_of_range_class_ids:
            unique_ids = sorted({cid for _, cid in s.out_of_range_class_ids})
            lines.append(
                f"- ❌ `{split}`：{len(s.out_of_range_class_ids)} 处类别 id 越界"
                f"（越界值：{unique_ids}，合法范围 0-{len(spec.names) - 1}）"
            )
        if s.out_of_range_coords:
            lines.append(
                f"- ❌ `{split}`：{len(s.out_of_range_coords)} 处坐标越界"
                f"（示例：{s.out_of_range_coords[0][0]} 第 {s.out_of_range_coords[0][1]} 行 "
                f"{s.out_of_range_coords[0][2]}）"
            )
        if s.malformed_lines:
            lines.append(
                f"- ❌ `{split}`：{len(s.malformed_lines)} 行标签格式非法"
                f"（示例：{s.malformed_lines[0][0]} 第 {s.malformed_lines[0][1]} 行）"
            )

    return lines


def build_report(audits: list[DatasetAudit], dataset_dir: Path) -> str:
    """汇总生成完整 Markdown 报告。"""
    lines: list[str] = []
    lines.append("# 数据集审计报告")
    lines.append("")
    lines.append("> 本报告由 `scripts/audit_dataset.py` 自动生成，所有数字均为实测值。")
    lines.append("> 审计过程对 `dataset/` **只读**，未修改任何数据文件。")
    lines.append("")

    # ---------------- 总览 ----------------
    lines.append("## 一、总览")
    lines.append("")
    lines.append("| 数据集 | split | 图片数 | 标签数 | 一一对应 | 实例总数 |")
    lines.append("| --- | --- | ---: | ---: | :---: | ---: |")
    for audit in audits:
        for split in SPLITS:
            s = audit.splits.get(split)
            if s is None:
                continue
            matched = "✅" if not s.images_without_labels and not s.labels_without_images else "❌"
            lines.append(
                f"| `{audit.spec.name}` | `{split}` | {_fmt_int(s.image_count)} | "
                f"{_fmt_int(s.label_count)} | {matched} | {_fmt_int(s.total_instances)} |"
            )
    lines.append("")

    grand_images = sum(a.total_images for a in audits)
    grand_labels = sum(a.total_labels for a in audits)
    grand_instances = sum(a.total_instances for a in audits)
    lines.append(
        f"**总计**：图片 {_fmt_int(grand_images)} 张、标签 {_fmt_int(grand_labels)} 个、"
        f"标注实例 {_fmt_int(grand_instances)} 个。"
    )
    lines.append("")

    # ---------------- 类别映射核实 ----------------
    lines.append("## 二、类别 id 映射核实")
    lines.append("")
    lines.append("下表为**从标签文件实际内容统计**得出的类别分布（非记忆或假设）。")
    lines.append("`data.yaml` 的 `names` 顺序与标签中出现的类别 id 共同确定映射关系。")
    lines.append("")
    for audit in audits:
        spec = audit.spec
        lines.append(f"**`{spec.name}`** — `names: {list(spec.names)}`")
        lines.append("")
        lines.append("| 类别 id | 类别名 | 全库实例数 | 该 id 是否真实出现 |")
        lines.append("| ---: | --- | ---: | :---: |")
        for class_id, class_name in enumerate(spec.names):
            count = sum(s.instance_counts.get(class_id, 0) for s in audit.splits.values())
            seen = "✅ 是" if count > 0 else "⚠️ 否"
            lines.append(f"| {class_id} | `{class_name}` | {count:,} | {seen} |")
        lines.append("")

    # ---------------- 分数据集详情 ----------------
    lines.append("## 三、分数据集详情")
    lines.append("")
    for audit in audits:
        lines.append(render_dataset_section(audit))
        lines.append("")

    # ---------------- 泄漏检测 ----------------
    lines.append("## 四、数据泄漏检测")
    lines.append("")
    lines.append("方法：按图片**文件内容 SHA256** 哈希，跨 split 比对完全相同的图片。")
    lines.append("")
    for audit in audits:
        lines.append(f"**`{audit.spec.name}`**")
        lines.append("")
        if audit.duplicate_groups:
            lines.append(
                f"- ❌ 发现 **{len(audit.duplicate_groups)}** 组跨 split 重复图片"
                f"（共 {sum(len(g) for _, g in audit.duplicate_groups)} 个文件）："
            )
            for digest, locations in audit.duplicate_groups[:20]:
                lines.append(f"  - `{digest[:16]}…` → {', '.join(f'`{loc}`' for loc in locations)}")
            if len(audit.duplicate_groups) > 20:
                lines.append(f"  - …（其余 {len(audit.duplicate_groups) - 20} 组略）")
        else:
            lines.append("- ✅ 未发现跨 split 内容重复图片")
        lines.append("")

        within = find_within_split_duplicates(audit.splits)
        if within:
            lines.append(
                f"- ℹ️ 同一 split 内存在 {len(within)} 组重复图片"
                f"（数据增强/连拍导致，非泄漏风险，但会略微影响该 split 的有效样本量）"
            )
        else:
            lines.append("- ℹ️ 同一 split 内无重复图片")
        lines.append("")

    # ---------------- 问题清单 ----------------
    lines.append("## 五、问题清单")
    lines.append("")
    all_issues: list[str] = []
    for audit in audits:
        issues = render_issue_list(audit)
        if issues:
            all_issues.append(f"**`{audit.spec.name}`**")
            all_issues.extend(issues)
            all_issues.append("")

    if all_issues:
        lines.extend(all_issues)
    else:
        lines.append("✅ 未发现任何问题：")
        lines.append("")
        lines.append("- 图片与标签全部一一对应，无缺失")
        lines.append("- 无类别 id 越界")
        lines.append("- 无坐标越界")
        lines.append("- 无格式非法标签行")
        lines.append("- 未发现跨 split 数据泄漏")
        lines.append("")

    # ---------------- 结论 ----------------
    lines.append("## 六、审计结论")
    lines.append("")
    all_matched = all(
        not s.images_without_labels and not s.labels_without_images
        for a in audits
        for s in a.splits.values()
    )
    total_leaks = sum(len(a.duplicate_groups) for a in audits)
    lines.append(f"- 图片/标签匹配：{'全部一一对应 ✅' if all_matched else '存在不匹配 ❌'}")
    lines.append(
        f"- 跨 split 泄漏：{'未发现 ✅' if total_leaks == 0 else f'发现 {total_leaks} 组 ❌'}"
    )
    lines.append(f"- 数据集目录：`{dataset_dir}`（审计只读，未修改）")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def discover_datasets(dataset_dir: Path) -> list[DatasetSpec]:
    """在 dataset_dir 下发现所有含 data.yaml 的数据集。"""
    specs: list[DatasetSpec] = []

    for yaml_path in sorted(dataset_dir.rglob("data.yaml")):
        names, nc = parse_data_yaml(yaml_path)
        if not names:
            print(f"[warn] {yaml_path} 未解析出 names，跳过", file=sys.stderr)
            continue
        specs.append(
            DatasetSpec(
                name=yaml_path.parent.name,
                root=yaml_path.parent,
                names=names,
                declared_nc=nc,
            )
        )

    return specs


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="数据集只读审计")
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=project_root / "dataset",
        help="数据集根目录（默认：<项目根>/dataset）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "docs文档" / "数据集审计报告.md",
        help="Markdown 报告输出路径",
    )
    args = parser.parse_args()

    dataset_dir = args.dataset_dir.resolve()
    if not dataset_dir.is_dir():
        print(f"[error] 数据集目录不存在：{dataset_dir}", file=sys.stderr)
        return 1

    specs = discover_datasets(dataset_dir)
    if not specs:
        print(f"[error] 在 {dataset_dir} 下未发现任何 data.yaml", file=sys.stderr)
        return 1

    audits: list[DatasetAudit] = []
    for spec in specs:
        print(f"[audit] {spec.name} …")
        audit = audit_dataset(spec)
        audits.append(audit)
        for split in SPLITS:
            s = audit.splits[split]
            print(
                f"  {split:>5}: 图片 {s.image_count:>5} / 标签 {s.label_count:>5} / "
                f"实例 {s.total_instances:>6} / 空标签 {len(s.empty_label_files)}"
            )
        print(f"  跨 split 重复组：{len(audit.duplicate_groups)}")

    report = build_report(audits, dataset_dir)

    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"[done] 报告已写入：{output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
