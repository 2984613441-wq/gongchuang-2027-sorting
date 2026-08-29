"""Host-only outbound sender: encodes ITEM_TASK / DISPLAY_ACK over a SerialLink.

The gateway validates every task identity fail-closed (unsigned 16-bit range
and equality with the verified round's task id) before anything reaches the
wire, and keeps its own monotonically increasing tx_seq (1-based) that is
independent of the PiProtocolGateway inbound-side counter. All wire encoding
reuses the frozen electrical_control.protocol helpers.
"""

from __future__ import annotations

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

    def __init__(self, link: SerialLink, *, config: OutboundConfig) -> None:
        self.link = link
        self.config = config
        self._tx_seq = 0

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
        self.link.send(frame)
        return frame

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
