"""车辆外观领域层与服务层测试：直方图/形状/嵌入/匹配/集成。"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest
from alembic import command
from alembic.config import Config
from numpy.typing import NDArray
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.vehicle_appearance import (
    COLOR_HIST_DIM,
    EMBEDDING_DIM,
    MATCH_MARGIN,
    MATCH_THRESHOLD,
    SHAPE_SIG_DIM,
    compute_embedding,
    cosine_similarity,
    extract_color_histogram,
    extract_shape_signature,
    match_candidates,
)

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _solid_rgb(color: tuple[int, int, int], size: int = 64) -> NDArray[np.uint8]:
    """构造纯色 RGB 图（带轻微噪声，模拟真实裁剪）。"""
    rng = np.random.RandomState(abs(hash(color)) % (2**31))
    base = np.zeros((size, size, 3), dtype=np.uint8)
    base[:, :] = np.array(color, dtype=np.uint8)
    noise = rng.randint(-4, 5, size=(size, size, 3)).astype(np.int16)
    return np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def _make_frame_with_vehicle(
    vehicle_color: tuple[int, int, int],
    rider_color: tuple[int, int, int] = (200, 200, 200),
) -> tuple[NDArray[np.uint8], tuple[float, float, float, float]]:
    """构造仿真 BGR 帧：上部骑行者色块 + 下部车辆色块，返回帧与框。"""
    height, width = 200, 100
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    rider_bgr = (rider_color[2], rider_color[1], rider_color[0])
    vehicle_bgr = (vehicle_color[2], vehicle_color[1], vehicle_color[0])
    frame[20:110] = np.array(rider_bgr, dtype=np.uint8)  # 上部：骑手
    frame[110:190] = np.array(vehicle_bgr, dtype=np.uint8)  # 下部：车辆
    box = (10.0, 20.0, 90.0, 190.0)
    return frame, box


def test_same_crop_twice_similarity_above_099() -> None:
    """同一张图的两次裁剪 → 相似度 > 0.99。"""
    crop = _solid_rgb((220, 30, 30))
    box = (10.0, 10.0, 50.0, 110.0)
    hist = extract_color_histogram(crop)
    shape = extract_shape_signature(box)
    first = compute_embedding(hist, shape)
    second = compute_embedding(extract_color_histogram(crop.copy()), extract_shape_signature(box))
    assert cosine_similarity(first, second) > 0.99


def test_different_colors_similarity_below_07() -> None:
    """不同颜色的车 → 相似度 < 0.7。"""
    box = (10.0, 10.0, 50.0, 110.0)
    shape = extract_shape_signature(box)
    red = compute_embedding(extract_color_histogram(_solid_rgb((220, 30, 30))), shape)
    blue = compute_embedding(extract_color_histogram(_solid_rgb((30, 60, 220))), shape)
    black = compute_embedding(extract_color_histogram(_solid_rgb((25, 25, 25))), shape)
    assert cosine_similarity(red, blue) < 0.7
    assert cosine_similarity(red, black) < 0.7
    assert cosine_similarity(blue, black) < 0.7


def test_match_candidates_margin_rule() -> None:
    """margin 规则：双候选接近时拒绝，拉开差距后命中。"""
    rng = np.random.RandomState(7)
    query = rng.normal(size=EMBEDDING_DIM)
    query = query / np.linalg.norm(query)
    near = query + rng.normal(scale=0.01, size=EMBEDDING_DIM)
    near = near / np.linalg.norm(near)
    # 构造与 near 极接近的干扰项：相似度差 < margin。
    rival = near + rng.normal(scale=0.001, size=EMBEDDING_DIM)
    rival = rival / np.linalg.norm(rival)
    assert cosine_similarity(query, near) >= MATCH_THRESHOLD
    assert cosine_similarity(query, rival) >= MATCH_THRESHOLD

    ambiguous = match_candidates(
        query, [("veh_a", near), ("veh_b", rival)], threshold=0.5, margin=MATCH_MARGIN
    )
    assert ambiguous.vehicle_id is None
    assert ambiguous.is_ambiguous is True

    # 单候选且达阈值 → 直接命中（无次高可比）。
    single = match_candidates(query, [("veh_a", near)], threshold=0.5, margin=MATCH_MARGIN)
    assert single.vehicle_id == "veh_a"
    assert single.is_ambiguous is False

    # 最佳未达阈值 → 拒绝。
    low = match_candidates(query, [("veh_a", near)], threshold=0.9999, margin=MATCH_MARGIN)
    assert low.vehicle_id is None
    assert low.is_ambiguous is True

    # 空候选 → 拒绝。
    assert match_candidates(query, []).vehicle_id is None


def test_dimension_validation_errors() -> None:
    """维度校验：非 128 维输入必须报错。"""
    good_hist = np.zeros(COLOR_HIST_DIM)
    good_hist[0] = 1.0
    good_shape = np.zeros(SHAPE_SIG_DIM)
    good_emb = np.zeros(EMBEDDING_DIM)

    with pytest.raises(ValueError):
        compute_embedding(np.zeros(32), good_shape)
    with pytest.raises(ValueError):
        compute_embedding(good_hist, np.zeros(8))
    with pytest.raises(ValueError):
        cosine_similarity(np.zeros(64), good_emb)
    with pytest.raises(ValueError):
        match_candidates(np.zeros(64), [("v", good_emb)])
    with pytest.raises(ValueError):
        match_candidates(good_emb, [("v", np.zeros(32))])


def test_service_extract_vehicle_embedding_shape() -> None:
    """服务层：BGR 帧 + 框 → 128 维 L2 归一化向量。"""
    from app.services.identity.appearance import extract_vehicle_embedding

    frame, box = _make_frame_with_vehicle((220, 30, 30))
    embedding = extract_vehicle_embedding(frame, box)
    assert embedding.shape == (EMBEDDING_DIM,)
    assert abs(float(np.linalg.norm(embedding)) - 1.0) < 1e-6


def _alembic_config(db_path: Path) -> Config:
    config = Config(str(PROJECT_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return config


def test_repository_embedding_methods(tmp_path: Path) -> None:
    """仓储增补：update/list/add_embedding_sample。"""
    from app.models.identity import Vehicle
    from app.repositories.vehicle import VehicleRepository

    db_path = tmp_path / "emb-repo.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as session:
            repo = VehicleRepository(session)
            repo.create(
                Vehicle(
                    vehicle_id="veh_001",
                    plate_no=None,
                    plate_type=None,
                    owner_id="2022110508",
                    owner_bind_type="manual",
                    confidence=0.9,
                    color_hist=None,
                    embedding=None,
                    first_seen=None,
                    last_seen=None,
                    status="active",
                )
            )
            session.commit()

            vector = [0.1] * EMBEDDING_DIM
            assert repo.update_embedding("veh_001", vector) == 1
            assert repo.update_embedding("missing", vector) == 0
            with pytest.raises(ValueError):
                repo.update_embedding("veh_001", [0.1] * 64)
            session.commit()

            owned = repo.list_embeddings_by_owner("2022110508")
            assert len(owned) == 1
            assert owned[0][0] == "veh_001"
            assert owned[0][1].shape == (EMBEDDING_DIM,)
            assert repo.list_embeddings_by_owner("nobody") == []

            # 追加样本：均值更新后向量变为 (0.1+0.3)/2=0.2。
            assert repo.add_embedding_sample("veh_001", [0.3] * EMBEDDING_DIM) == 1
            assert repo.add_embedding_sample("missing", [0.3] * EMBEDDING_DIM) == 0
            with pytest.raises(ValueError):
                repo.add_embedding_sample("veh_001", [0.3] * 10)
            session.commit()

            stored = session.get(Vehicle, "veh_001")
            assert stored is not None and stored.embedding is not None
            decoded = struct.unpack("<128f", stored.embedding)
            assert abs(decoded[0] - 0.2) < 1e-6
    finally:
        engine.dispose()


def test_integration_three_vehicles_rematch(tmp_path: Path) -> None:
    """集成：红/蓝/黑三车登记后，第 2/3 次通行正确匹配回同一 vehicle_id。"""
    from app.models.identity import Vehicle
    from app.repositories.vehicle import VehicleRepository
    from app.services.identity.appearance import extract_vehicle_embedding

    colors = {
        "veh_red": (220, 30, 30),
        "veh_blue": (30, 60, 220),
        "veh_black": (25, 25, 25),
    }
    db_path = tmp_path / "emb-int.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as session:
            repo = VehicleRepository(session)
            for vehicle_id in colors:
                repo.create(
                    Vehicle(
                        vehicle_id=vehicle_id,
                        plate_no=None,
                        plate_type=None,
                        owner_id=None,
                        owner_bind_type=None,
                        confidence=0.0,
                        color_hist=None,
                        embedding=None,
                        first_seen=None,
                        last_seen=None,
                        status="unbound",
                    )
                )
            session.commit()

            # 第 1 次通行：登记 embedding。
            first_embeddings: dict[str, NDArray[np.float64]] = {}
            for vehicle_id, color in colors.items():
                frame, box = _make_frame_with_vehicle(color)
                embedding = extract_vehicle_embedding(frame, box)
                first_embeddings[vehicle_id] = embedding
                assert repo.update_embedding(vehicle_id, [float(v) for v in embedding]) == 1
            session.commit()

            # 第 2/3 次通行：带位移与亮度抖动的同车帧必须匹配回自身。
            for round_no in (2, 3):
                for vehicle_id, color in colors.items():
                    frame, box = _make_frame_with_vehicle(color)
                    jitter = np.random.RandomState(round_no * 100 + hash(vehicle_id) % 97).randint(
                        -8, 9, size=frame.shape
                    )
                    frame = np.clip(frame.astype(np.int16) + jitter, 0, 255).astype(np.uint8)
                    box = (box[0] + 2.0, box[1] + 1.0, box[2] - 2.0, box[3] - 1.0)
                    query = extract_vehicle_embedding(frame, box)
                    hits = repo.find_similar_by_embedding(
                        [float(v) for v in query], threshold=MATCH_THRESHOLD
                    )
                    assert hits, f"{vehicle_id} 第 {round_no} 次通行无候选"
                    assert hits[0][0].vehicle_id == vehicle_id, (
                        f"{vehicle_id} 第 {round_no} 次通行误匹配为 {hits[0][0].vehicle_id}"
                    )
                    assert repo.add_embedding_sample(
                        vehicle_id, [float(v) for v in query]
                    ) == 1
            session.commit()

            # 跨车验证：红车查询的 top-1 必须是红车而非蓝/黑。
            query_red = first_embeddings["veh_red"]
            hits = repo.find_similar_by_embedding(
                [float(v) for v in query_red], threshold=0.0
            )
            assert [vehicle.vehicle_id for vehicle, _ in hits][0] == "veh_red"
    finally:
        engine.dispose()
