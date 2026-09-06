"""Host-side tests for the SocketVisionSource bridge.

Verifies the MaixCAM -> Pi bridge logic without any hardware: parse the frozen
BATCH_TARGETS region, stage it fail-closed against the verified round task_id,
and pull one ItemTaskContext at a time through the Scheduler's seam.
"""

from __future__ import annotations

import pytest

from electrical_control.protocol import encode_item_task_payload
from electrical_control.rpi.socket_vision_source import SocketVisionSource


# 真实现场样本（2026-09-03 调试总结）：count=1, task_id=0, class_id=4,
# conf=90, x=94, y=284, angle=0xFF。
_SAMPLE_TASK0 = bytes.fromhex("010000045a005e011cff")
# 同一样本但 task_id=1（已验证轮次）。
_SAMPLE_TASK1 = bytes.fromhex("010001045a005e011cff")


def _make_source(task_id: int = 1) -> SocketVisionSource:
    return SocketVisionSource(
        round_id="round-1",
        task_id=task_id,
        image_id_for_class=lambda class_id: class_id,
        drop_point_for_box=lambda box_id: (100, 200),
    )


def test_task_id_zero_is_rejected_fail_closed():
    """Unconfigured task_id 0 (MaixCAM default) must not leak into the round."""
    source = _make_source(task_id=1)
    source.ingest(_SAMPLE_TASK0)
    source.set_permitted(True)
    assert source.next_if_permitted() is None


def test_matching_task_id_yields_serializable_context():
    source = _make_source(task_id=1)
    source.ingest(_SAMPLE_TASK1)
    source.set_permitted(True)
    ctx = source.next_if_permitted()
    assert ctx is not None
    assert ctx.round_id == "round-1"
    assert ctx.task_id == 1
    assert ctx.frame_seq == 1
    payload = ctx.payload
    assert payload.class_id == 4
    assert payload.image_id == 4  # image_id == class_id frozen 1:1
    assert payload.grip_angle == 0xFF
    assert payload.x_position == 100  # 占位落点
    assert payload.y_position == 200
    # 可序列化（grip_angle=0xFF + image_id==class_id 才不被 wire 边界拒绝）
    assert len(encode_item_task_payload(payload)) == 8


def test_single_slot_latest_batch_overwrites_stale():
    """A newer batch replaces an un-consumed one (scene-snapshot semantics)."""
    source = _make_source(task_id=1)
    source.ingest(_SAMPLE_TASK1)
    # 两目标 batch 覆盖前一个单目标 batch（仍用 task_id=1）
    two = bytes.fromhex("020001045a005e011cff025a005f011dff")
    source.ingest(two)
    source.set_permitted(True)
    first = source.next_if_permitted()
    second = source.next_if_permitted()
    third = source.next_if_permitted()
    assert first is not None and first.payload.target_seq == 1
    assert second is not None and second.payload.target_seq == 2
    assert third is None  # 批次消费完，无更多


def test_malformed_batch_is_dropped_fail_closed():
    source = _make_source(task_id=1)
    source.ingest(b"\x02\x00\x01")  # 声明 2 目标但缺字节
    source.set_permitted(True)
    assert source.next_if_permitted() is None


def test_without_permit_returns_none():
    source = _make_source(task_id=1)
    source.ingest(_SAMPLE_TASK1)
    # 未 set_permitted(True) 前，next_if_permitted 不产出
    assert source.next_if_permitted() is None


def test_recv_batch_delimits_stream():
    """长连接下 recv_batch 必须按 count 首字节正确切分字节流。"""
    import socket

    from electrical_control.rpi.socket_vision_source import recv_batch

    client, server = socket.socketpair()
    try:
        # 连续两个 batch（模拟长连接连续 sendall，无消息边界）
        client.sendall(_SAMPLE_TASK1 + _SAMPLE_TASK1)
        assert recv_batch(server) == _SAMPLE_TASK1
        assert recv_batch(server) == _SAMPLE_TASK1
    finally:
        client.close()
        server.close()
