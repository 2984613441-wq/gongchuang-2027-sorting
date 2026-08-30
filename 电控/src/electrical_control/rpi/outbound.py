"""Host-only outbound sender: encodes ITEM_TASK / DISPLAY_ACK over a SerialLink.

The gateway validates every task identity fail-closed (unsigned 16-bit range
and equality with the verified round's task id) before anything reaches the
wire, and keeps its own monotonically increasing tx_seq (1-based) that is
independent of the PiProtocolGateway inbound-side counter. All wire encoding
reuses the frozen electrical_control.protocol helpers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from electrical_control.protocol import (
    PayloadError,
    encode_display_ack_frame,
    encode_item_task_frame,
    encode_item_task_payload,
)

from . import DisplayAckIntent, ItemTaskContext
from .serial_link import SerialLink


def _u16(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFF:
        raise PayloadError(f"{name} must be an unsigned 16-bit integer")
    return value


@dataclass(frozen=True, slots=True)
class OutboundConfig:
    round_task_id: int  # 本轮任务号（来自 VerifiedNewRound，u16 范围校验）

    def __post_init__(self) -> None:
        _u16("round_task_id", self.round_task_id)


class OutboundGateway:
    """Encodes and sends ITEM_TASK / DISPLAY_ACK outer frames over a SerialLink."""

    def __init__(
        self,
        link: SerialLink,
        *,
        config: OutboundConfig,
        on_retransmit: Callable[[], None] | None = None,
    ) -> None:
        self.link = link
        self.config = config
        self._tx_seq = 0
        # D-1: cache of the exact bytes of the most recently sent ITEM_TASK
        # frame plus the (task_id, frame_seq) identity it was sent for, so a
        # timeout resend can replay the same wire bytes (same frame_seq) and
        # hit the STM32 dedup -> RESEND path.
        self._last_item_task_frame: bytes | None = None
        self._last_item_task_key: tuple[int, int] | None = None
        self._on_retransmit = on_retransmit

    @property
    def tx_seq(self) -> int:
        """Monotonically increasing outbound sequence (1-based); +1 per frame."""
        return self._tx_seq

    def send_item_task(self, task: ItemTaskContext) -> bytes:
        """Encode and send one ITEM_TASK; returns the raw frame bytes.

        Fail-closed: task.task_id must be an unsigned 16-bit integer equal to
        config.round_task_id, otherwise PayloadError is raised before anything
        is sent (tx_seq is not advanced either).
        """

        task_id = _u16("task_id", task.task_id)
        if task_id != self.config.round_task_id:
            raise PayloadError(
                f"task_id {task_id} does not match round_task_id "
                f"{self.config.round_task_id}"
            )
        payload = encode_item_task_payload(task.payload)
        self._tx_seq += 1
        frame = encode_item_task_frame(
            task_id=task_id,
            frame_seq=self._tx_seq,
            payload=payload,
        )
        # D-1: cache the exact frame bytes for resend_item_task. The key is the
        # task's own (task_id, frame_seq) identity (scheduler side), not the
        # wire frame_seq (the outbound tx counter), so a resend of the same
        # task is recognized even though the wire frame_seq differs.
        self._last_item_task_frame = frame
        self._last_item_task_key = (task_id, task.frame_seq)
        self.link.send(frame)
        return frame

    def resend_item_task(self, task: ItemTaskContext) -> bytes:
        """原样重放上次 send_item_task 的帧字节（不递增 tx_seq）。

        与 STM32 的 RESEND 路径配对：超时重传复用同一 (task_id, frame_seq)，
        STM32 按 dedup 判定为重复帧 → 重发缓存应答，不会重复执行。
        """

        cached = self._last_item_task_frame
        cached_key = self._last_item_task_key
        if cached is None or cached_key is None:
            raise ValueError("no cached ITEM_TASK frame")
        task_key = (task.task_id, task.frame_seq)
        if task_key != cached_key:
            raise ValueError(
                f"task ({task_key[0]}, {task_key[1]}) does not match cached "
                f"ITEM_TASK frame ({cached_key[0]}, {cached_key[1]})"
            )
        self.link.send(cached)
        if self._on_retransmit is not None:
            self._on_retransmit()
        return cached

    def send_display_ack(self, intent: DisplayAckIntent) -> bytes:
        """Encode and send one DISPLAY_ACK for a completed render receipt.

        Mirrors PiProtocolGateway.emit_display_ack semantics: only a RENDERED
        intent may be acknowledged, and the wire render_result is always 0x00.
        Returns the raw frame bytes.
        """

        if intent.render_result != "RENDERED":
            raise ValueError("DISPLAY_ACK requires render_result RENDERED")
        self._tx_seq += 1
        frame = encode_display_ack_frame(
            task_id=intent.task.task_id,
            frame_seq=self._tx_seq,
            target_seq=intent.target_seq,
            render_result=0x00,
            content_crc32=intent.content_crc32,
        )
        self.link.send(frame)
        return frame


__all__ = ["OutboundConfig", "OutboundGateway"]
