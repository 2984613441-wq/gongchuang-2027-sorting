"""Host-only Raspberry Pi protocol gateway.

This assembles STM32 -> Pi outer frames and dispatches the frozen commands to
the offline Scheduler. It never opens a serial port, renders a screen, or moves
an actuator. Display rendering remains an explicit, separately-owned step.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass

from electrical_control.protocol import (
    ACK_REASONS,
    CRC_LEN,
    HEADER_0,
    HEADER_1,
    HEADER_LEN,
    NACK_REASONS,
    Command,
    Device,
    PayloadError,
    decode_ack_nack_payload,
    decode_item_result_payload,
    decode_outer_frame,
    encode_display_ack_frame,
)

from . import DisplayAckIntent, ItemResult, SchedulerFault
from .log import STAGE, CentralLog


# Bounded inbound dedup history: a replayed frame within the window is
# answered with the cached outbound; older identities age out so the cache
# cannot grow without bound across a long demo run.
_INBOUND_CACHE_CAPACITY = 256


@dataclass(frozen=True, slots=True)
class PiGatewayOutcome:
    event: str
    outbound: bytes | None = None
    fault: str | None = None


class PiProtocolGateway:
    """Wire-facing gateway around an offline Scheduler."""

    def __init__(self, scheduler, *, logger: CentralLog | None = None) -> None:
        self.scheduler = scheduler
        self.logger = logger
        self._rx = bytearray()
        self.tx_seq = 0
        self.estop_active = False
        self._inbound_cache: OrderedDict[tuple[int, int], bytes | None] = OrderedDict()
        self._last_outbound: bytes | None = None

    @property
    def last_outbound(self) -> bytes | None:
        return self._last_outbound

    def feed_frame(self, data: bytes) -> PiGatewayOutcome:
        """Dispatch one already-delimited frame."""

        try:
            frame = decode_outer_frame(data)
        except PayloadError as exc:
            return PiGatewayOutcome("FRAME_REJECTED", fault=str(exc))
        return self._dispatch(frame)

    def feed_byte(self, byte: int) -> PiGatewayOutcome | None:
        """Feed one RX byte; returns an outcome only when a frame completes."""

        self._rx.append(byte & 0xFF)
        while True:
            if len(self._rx) < 2:
                return None
            if self._rx[0] != HEADER_0:
                self._rx.pop(0)
                continue
            if self._rx[1] != HEADER_1:
                self._rx.pop(0)
                continue
            if len(self._rx) < HEADER_LEN:
                return None
            data_len = int.from_bytes(self._rx[10:12], "big")
            total = HEADER_LEN + data_len + CRC_LEN
            if len(self._rx) < total:
                return None
            raw = bytes(self._rx[:total])
            del self._rx[:total]
            try:
                frame = decode_outer_frame(raw)
            except PayloadError as exc:
                return PiGatewayOutcome("FRAME_REJECTED", fault=str(exc))
            return self._dispatch(frame)

    def emit_display_ack(self, intent: DisplayAckIntent) -> bytes:
        """Encode the first valid DISPLAY_ACK for a completed render receipt."""

        if intent.render_result != "RENDERED":
            raise ValueError("DISPLAY_ACK requires render_result RENDERED")
        self.tx_seq += 1
        outbound = encode_display_ack_frame(
            task_id=intent.task.task_id,
            frame_seq=self.tx_seq,
            target_seq=intent.target_seq,
            render_result=0x00,
            content_crc32=intent.content_crc32,
        )
        self._last_outbound = outbound
        return outbound

    def _dispatch(self, frame) -> PiGatewayOutcome:
        if frame.sender is not Device.STM32 or frame.receiver is not Device.RASPI:
            return PiGatewayOutcome("DIRECTION_REJECTED", fault="illegal Scheme-B direction")

        identity = (frame.task_id, frame.frame_seq)
        cached = self._inbound_cache.get(identity, _MISSING)
        if cached is not _MISSING:
            return PiGatewayOutcome("DUPLICATE", outbound=cached)

        try:
            outcome = self._handle(frame)
        except SchedulerFault as exc:  # defensive: never leak scheduler faults
            outcome = PiGatewayOutcome("FAULT", fault=str(exc))
        except Exception as exc:  # fail closed instead of crashing the loop
            outcome = PiGatewayOutcome("CRASH", fault=f"{type(exc).__name__}: {exc}")
        self._inbound_cache[identity] = outcome.outbound
        if len(self._inbound_cache) > _INBOUND_CACHE_CAPACITY:
            self._inbound_cache.popitem(last=False)
        return outcome

    def _handle(self, frame) -> PiGatewayOutcome:
        command = frame.command
        if command == int(Command.BARRIER_READY):
            if frame.payload:
                return PiGatewayOutcome("FRAME_REJECTED", fault="BARRIER_READY payload must be empty")
            return PiGatewayOutcome("BARRIER_READY")

        if command == int(Command.MOTION_DONE):
            if frame.payload:
                return PiGatewayOutcome("FRAME_REJECTED", fault="MOTION_DONE payload must be empty")
            task = self.scheduler.current_task
            if task is None:
                return PiGatewayOutcome("MOTION_DONE_IGNORED")
            # The wire frame_seq belongs to the STM32's own tx counter, not the
            # Pi-side task identity; the scheduler gate is entered with the
            # active task's identity and the wire task_id is checked against it.
            if frame.task_id != task.task_id:
                return PiGatewayOutcome(
                    "FAULT", fault="MOTION_DONE task_id does not match active item"
                )
            try:
                self.scheduler.accept_motion_done(
                    round_id=task.round_id,
                    task_id=task.task_id,
                    frame_seq=task.frame_seq,
                )
            except SchedulerFault as exc:
                return PiGatewayOutcome("FAULT", fault=str(exc))
            return PiGatewayOutcome("MOTION_DONE")

        if command == int(Command.ITEM_RESULT):
            try:
                payload = decode_item_result_payload(frame.payload)
            except PayloadError as exc:
                return PiGatewayOutcome("FRAME_REJECTED", fault=str(exc))
            task = self.scheduler.current_task
            if task is None:
                return PiGatewayOutcome("ITEM_RESULT_IGNORED")
            result = ItemResult(
                task.round_id,
                frame.task_id,
                task.frame_seq,
                payload.target_seq,
                payload.result_code,
            )
            try:
                self.scheduler.accept_item_result(result)
            except SchedulerFault as exc:
                return PiGatewayOutcome("FAULT", fault=str(exc))
            return PiGatewayOutcome("ITEM_RESULT")

        if command == int(Command.ESTOP):
            self.estop_active = True
            note_estop = getattr(self.scheduler, "note_estop", None)
            if callable(note_estop):
                note_estop()
            return PiGatewayOutcome("ESTOP")

        if command in (int(Command.ACK), int(Command.NACK)):
            return self._handle_ack_nack(frame, command)

        return PiGatewayOutcome("IGNORED")

    def _handle_ack_nack(self, frame, command: int) -> PiGatewayOutcome:
        """Parse an inbound ACK(0x05)/NACK(0x06) two-byte response payload.

        D-2: STM32 replies to our requests with reason(1) + target_seq(1).
        The frozen reason code is mapped to its name (``ACK_ACCEPTED`` /
        ``NACK_SINGLE_TASK_ONLY`` ...) for the outcome event; an as-yet
        unknown code stays observable as ``UNKNOWN(0xNN)``. When a CentralLog
        is injected, a STAGE entry is recorded so integration debugging can
        see the STM32 rejection reason (STALE_OR_ORDER / SINGLE_TASK_ONLY /
        ACK_NOT_APPLICABLE ...) without guessing from silence.
        """

        try:
            reason_code, target_seq = decode_ack_nack_payload(frame.payload)
        except PayloadError as exc:
            return PiGatewayOutcome("FRAME_REJECTED", fault=str(exc))
        kind = "ACK" if command == int(Command.ACK) else "NACK"
        reasons = ACK_REASONS if command == int(Command.ACK) else NACK_REASONS
        reason_name = reasons.get(reason_code)
        if reason_name is None:
            reason_name = f"UNKNOWN(0x{reason_code:02X})"
        if self.logger is not None:
            self.logger.record(
                STAGE,
                now=time.monotonic(),
                task_id=frame.task_id,
                frame_seq=frame.frame_seq,
                target_seq=target_seq,
                detail=f"{kind}:{reason_name} seq={target_seq}",
            )
        return PiGatewayOutcome(f"{kind}_{reason_name}")


_MISSING = object()


__all__ = ["PiGatewayOutcome", "PiProtocolGateway"]
