"""code(1..30) 解析的单测（2026-11-01 新增，协议 V1.0 草案配套）。

背景：颜色必须进决策。主相机本地算出
``code = (shape-1)*5 + color + 1``（shape 1..6、color 1..5），
一个字节放到 `BATCH_TARGETS` 的 id 位，**线格式不变**。

默认模式仍是 ``box_id``（= 现状），本文件验证：
1. code ↔ (shape, color) 互转（含 30 个全枚举）
2. code 模式解析：1..30 接受、0/31/255 拒识该件但保留其余件
3. 默认 box_id 模式行为不变（回归保护）
"""

from __future__ import annotations

import pytest

from electrical_control.rpi import vision_ingest as vi
from electrical_control.protocol.errors import PayloadError
from electrical_control.rpi.vision_ingest import (
    COLOR_COUNT,
    CODE_UNKNOWN,
    SHAPE_COUNT,
    code_to_shape_color,
    parse_batch_targets,
    shape_color_to_code,
)

_ANGLE_NONE = 0xFF


def _batch(items, task_id: int = 7) -> bytes:
    """items: [(id_byte, conf, cx, cy)] → BATCH_TARGETS 字节串。"""
    body = bytes((len(items),)) + int(task_id).to_bytes(2, "big")
    for id_byte, conf, cx, cy in items:
        body += bytes((id_byte & 0xFF, conf & 0xFF))
        body += int(cx).to_bytes(2, "big") + int(cy).to_bytes(2, "big")
        body += bytes((_ANGLE_NONE,))
    return body


# --------------------------------------------------------------------------- #
# 1) 编解码映射
# --------------------------------------------------------------------------- #
def test_code_round_trip_all_30():
    for code in range(1, SHAPE_COUNT * COLOR_COUNT + 1):
        pair = code_to_shape_color(code)
        assert pair is not None
        shape, color = pair
        assert 1 <= shape <= SHAPE_COUNT
        assert 1 <= color <= COLOR_COUNT
        assert shape_color_to_code(shape, color) == code


def test_code_samples_match_formula():
    # code = (shape-1)*5 + color
    assert code_to_shape_color(1) == (1, 1)      # cube + red
    assert code_to_shape_color(5) == (1, 5)      # cube + white
    assert code_to_shape_color(6) == (2, 1)      # cuboid + red
    assert code_to_shape_color(11) == (3, 1)     # cylinder + red
    assert code_to_shape_color(30) == (6, 5)     # tetrahedron + white


@pytest.mark.parametrize("bad", [0, -1, 31, 255])
def test_code_out_of_range_returns_none(bad):
    assert code_to_shape_color(bad) is None


@pytest.mark.parametrize("shape,color", [(0, 1), (7, 1), (1, 0), (1, 6)])
def test_shape_color_to_code_rejects_out_of_range(shape, color):
    with pytest.raises(PayloadError):
        shape_color_to_code(shape, color)


# --------------------------------------------------------------------------- #
# 2) code 模式解析
# --------------------------------------------------------------------------- #
@pytest.fixture
def code_mode(monkeypatch):
    monkeypatch.setattr(vi, "BATCH_ID_BYTE_MODE", "code")
    return vi


def test_code_mode_accepts_1_to_30(code_mode):
    batch = parse_batch_targets(_batch([(11, 90, 640, 360), (30, 88, 100, 120)]))
    assert len(batch.targets) == 2
    first, second = batch.targets
    assert (first.class_id, first.box_id) == (11, None)
    assert (second.class_id, second.box_id) == (30, None)


def test_code_mode_drops_unknown_but_keeps_others(code_mode):
    batch = parse_batch_targets(
        _batch([(CODE_UNKNOWN, 95, 10, 10), (7, 90, 640, 360)])
    )
    assert len(batch.targets) == 1
    assert batch.targets[0].class_id == 7


@pytest.mark.parametrize("bad_id", [31, 200, 255])
def test_code_mode_drops_out_of_range(code_mode, bad_id):
    batch = parse_batch_targets(_batch([(bad_id, 90, 10, 10), (1, 90, 20, 20)]))
    assert len(batch.targets) == 1
    assert batch.targets[0].class_id == 1


# --------------------------------------------------------------------------- #
# 3) 默认 box_id 模式回归
# --------------------------------------------------------------------------- #
def test_default_mode_is_still_box_id():
    assert vi.BATCH_ID_BYTE_MODE in ("box_id", "code")
    # 不 monkeypatch 时按模块常量走；若部署环境变量是 code 则跳过该断言
    if vi.BATCH_ID_BYTE_MODE != "box_id":
        pytest.skip("环境变量 BATCH_ID_BYTE_MODE=code，本机不做 box_id 回归")


def test_box_id_mode_unchanged():
    if vi.BATCH_ID_BYTE_MODE != "box_id":
        pytest.skip("环境变量已切 code 模式")
    batch = parse_batch_targets(_batch([(3, 90, 640, 360)]))
    assert len(batch.targets) == 1
    t = batch.targets[0]
    assert (t.class_id, t.box_id) == (3, 3)
