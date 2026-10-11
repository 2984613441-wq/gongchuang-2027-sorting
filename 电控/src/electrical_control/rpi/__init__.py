"""Offline Raspberry Pi scheduler skeleton; no hardware adapters live here."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterable, Mapping

from electrical_control.protocol import (
    DisplayContent,
    ItemTaskPayload,
    ResultIdentityConflict,
    RoundSuccessCounter,
    SuccessCountOverflow,
    build_display_content,
)
from .vision_ingest import (
    BatchTargets,
    FakeVisionSource,
    ImageIdMap,
    TargetReacquireResponse,
    VisionTarget,
    build_item_task_queue,
)


class SchedulerState(Enum):
    RECOVERY_LOCK = auto()
    READY = auto()
    ACTIVE = auto()
    WAIT_MOTION_DONE = auto()
    WAIT_ITEM_RESULT = auto()
    WAIT_RENDER = auto()
    FAULT = auto()


class SchedulerFault(RuntimeError):
    pass


@dataclass(frozen=True)
class VerifiedNewRound:
    round_id: str
    human_confirmed: bool
    stm32_safe: bool
    both_nodes_initialized: bool


@dataclass(frozen=True)
class ItemTaskContext:
    round_id: str
    task_id: int
    frame_seq: int
    payload: ItemTaskPayload


@dataclass(frozen=True)
class ItemResult:
    round_id: str
    task_id: int
    frame_seq: int
    target_seq: int
    result_code: int


@dataclass(frozen=True)
class RenderReceipt:
    round_id: str
    task_id: int
    target_seq: int
    content_crc32: int


# Bounded provenance history: one entry per completed render receipt. The
# one-byte round success counter bounds items per round, but across many
# rounds an unbounded module-level list would grow forever; cap it globally.
_COMPLETED_RECEIPT_CAPACITY = 512
_completed_receipts: deque[RenderReceipt] = deque(maxlen=_COMPLETED_RECEIPT_CAPACITY)


def _record_completed_receipt(receipt: RenderReceipt) -> RenderReceipt:
    _completed_receipts.append(receipt)
    return receipt


def _was_completed_by_pending(receipt: RenderReceipt) -> bool:
    return any(receipt is completed for completed in _completed_receipts)


@dataclass(frozen=True)
class DisplayAckIntent:
    task: ItemTaskContext
    target_seq: int
    render_result: str
    content_crc32: int

    @property
    def content_crc32_bytes(self) -> bytes:
        return self.content_crc32.to_bytes(4, "big")


class PendingRender:
    def __init__(self, model: DisplayContent, task: ItemTaskContext) -> None:
        self._model = model
        self._task = task
        self.receipt: RenderReceipt | None = None
        self._closed = False

    def complete(self) -> RenderReceipt:
        if self._closed:
            raise RuntimeError("render is already closed")
        self._closed = True
        self.receipt = _record_completed_receipt(
            RenderReceipt(
                self._task.round_id,
                self._task.task_id,
                self._task.payload.target_seq,
                self._model.crc32,
            )
        )
        return self.receipt

    def failed(self) -> None:
        self._closed = True

    def cancelled(self) -> None:
        self._closed = True


class FakeRenderer:
    def __init__(self, task: ItemTaskContext) -> None:
        self._task = task

    def present(self, model: DisplayContent) -> PendingRender:
        return PendingRender(model, self._task)


class FakeTaskSource:
    def __init__(self, tasks: Iterable[ItemTaskPayload | ItemTaskContext]) -> None:
        self._tasks = iter(tuple(tasks))
        self._permitted = False

    def set_permitted(self, permitted: bool) -> None:
        self._permitted = permitted

    def next_if_permitted(self) -> ItemTaskPayload | ItemTaskContext | None:
        if not self._permitted:
            return None
        return next(self._tasks, None)


class Scheduler:
    """Offline scheduler; starts in RECOVERY_LOCK until a verified new round.

    diagnostic_snapshot is a read-only mapping from a previous process (for
    example round_id, success_count, last_task) used only for diagnostics. It
    never restores, resumes, or clears state, and it cannot authorize an old
    round to continue after a restart.
    """

    def __init__(self, *, diagnostic_snapshot: Mapping[str, object] | None = None) -> None:
        self.state = SchedulerState.RECOVERY_LOCK
        self._counter = RoundSuccessCounter()
        self.diagnostic_snapshot = dict(diagnostic_snapshot or {})
        self._source: FakeTaskSource | None = None
        self.current_task: ItemTaskContext | None = None
        self.display_model: DisplayContent | None = None
        self.display_ack_intent: DisplayAckIntent | None = None
        self._round_id: str | None = None
        self._seen_tasks: dict[tuple[str, int, int], ItemTaskPayload] = {}
        self._estop_active = False

    @property
    def success_count(self) -> int:
        return self._counter.value

    @property
    def is_faulted(self) -> bool:
        return self.state is SchedulerState.FAULT

    @property
    def estop_active(self) -> bool:
        return self._estop_active

    def load_source(self, source: FakeTaskSource) -> None:
        self._source = source

    def note_estop(self) -> None:
        """Stop dispatching new tasks until a verified new round.

        The physical e-stop circuit belongs to STM32; this flag only makes the
        scheduler fail closed so it never hands out another ITEM_TASK while the
        machine is stopped (competition rule: e-stop ends the round).
        """

        self._estop_active = True

    def next_task(self) -> ItemTaskPayload | ItemTaskContext | None:
        if self.state is not SchedulerState.READY or self._source is None:
            return None
        if self._estop_active:
            return None
        self._source.set_permitted(True)
        candidate = self._source.next_if_permitted()
        self._source.set_permitted(False)
        if candidate is None:
            return None
        if not self._counter.can_accept_new_item:
            self._fault("success counter cannot admit another potentially successful item")
        if isinstance(candidate, ItemTaskContext):
            if candidate.round_id != self._round_id:
                self._fault("task does not belong to verified round")
            identity = (candidate.round_id, candidate.task_id, candidate.frame_seq)
            previous = self._seen_tasks.get(identity)
            if previous is not None and previous != candidate.payload:
                self._fault("same task identity has conflicting payloads")
            self._seen_tasks[identity] = candidate.payload
            self.current_task = candidate
            self.display_ack_intent = None
            # Transition to WAIT_MOTION_DONE after accepting task
            self.state = SchedulerState.WAIT_MOTION_DONE
        return candidate

    def accept_motion_done(self, **event_identity: object) -> None:
        """Enforce that motion has completed for the current task.

        This is the first gate in the MOTION_DONE → ITEM_RESULT → DISPLAY_ACK
        sequence. Must be called before accept_item_result.

        Validates:
        - Current task exists
        - State is WAIT_MOTION_DONE
        - event_identity matches current task (round_id, task_id, frame_seq)

        Transitions to WAIT_ITEM_RESULT state.
        """
        task = self.current_task
        if task is None:
            self._fault("motion_done arrived without an active item")
        if self.state is not SchedulerState.WAIT_MOTION_DONE:
            self._fault(f"motion_done arrived in wrong state: {self.state}")

        # Validate event_identity matches task (round_id, task_id, frame_seq)
        expected_round_id = task.round_id
        expected_task_id = task.task_id
        expected_frame_seq = task.frame_seq

        actual_round_id = event_identity.get("round_id")
        actual_task_id = event_identity.get("task_id")
        actual_frame_seq = event_identity.get("frame_seq")

        if (actual_round_id != expected_round_id or
            actual_task_id != expected_task_id or
            actual_frame_seq != expected_frame_seq):
            self._fault(
                f"motion_done identity mismatch: "
                f"expected ({expected_round_id}, {expected_task_id}, {expected_frame_seq}), "
                f"got ({actual_round_id}, {actual_task_id}, {actual_frame_seq})"
            )

        # Transition to WAIT_ITEM_RESULT
        self.state = SchedulerState.WAIT_ITEM_RESULT
        return None

    def note_reconnect(self) -> None:
        return None

    def note_retransmission(self) -> None:
        return None

    def note_display_retry(self) -> None:
        return None

    def accept_item_result(self, result: ItemResult) -> DisplayContent:
        task = self.current_task
        # Enforce MOTION_DONE → ITEM_RESULT sequence: only accept in WAIT_ITEM_RESULT.
        # WAIT_RENDER is allowed for idempotent re-sends of the same result.
        if task is None or self.state not in (SchedulerState.WAIT_ITEM_RESULT, SchedulerState.WAIT_RENDER):
            self._fault(f"result arrived in wrong state: {self.state}")
        assert task is not None
        expected = (task.round_id, task.task_id, task.frame_seq, task.payload.target_seq)
        actual = (result.round_id, result.task_id, result.frame_seq, result.target_seq)
        if actual != expected:
            raise SchedulerFault("result does not match active item")
        if self.display_model is not None:
            if self.display_model.result_code != result.result_code:
                self._fault("same item identity has conflicting results")
            return self.display_model
        try:
            self._counter.record_item_result(
                task_id=result.task_id,
                frame_seq=result.frame_seq,
                result_code=result.result_code,
            )
        except (ResultIdentityConflict, SuccessCountOverflow) as exc:
            self._fault(str(exc))
        self.display_model = build_display_content(
            item_task=task.payload,
            success_count=self._counter.value,
            result_code=result.result_code,
        )
        self.state = SchedulerState.WAIT_RENDER
        return self.display_model

    def accept_render_receipt(self, receipt: RenderReceipt) -> DisplayAckIntent:
        if not _was_completed_by_pending(receipt):
            raise SchedulerFault("receipt lacks PendingRender completion provenance")
        if self.display_ack_intent is not None:
            if receipt.content_crc32 == self.display_ack_intent.content_crc32:
                return self.display_ack_intent
            raise SchedulerFault("duplicate receipt conflicts with cached intent")
        task, model = self.current_task, self.display_model
        if task is None or model is None or self.state is not SchedulerState.WAIT_RENDER:
            raise SchedulerFault("receipt arrived without pending display")
        expected = (task.round_id, task.task_id, task.payload.target_seq, model.crc32)
        actual = (receipt.round_id, receipt.task_id, receipt.target_seq, receipt.content_crc32)
        if actual != expected:
            raise SchedulerFault("receipt does not match current display model")
        self.display_ack_intent = DisplayAckIntent(
            task=task,
            target_seq=task.payload.target_seq,
            render_result="RENDERED",
            content_crc32=model.crc32,
        )
        self.current_task = None
        self.display_model = None
        self.state = SchedulerState.READY
        return self.display_ack_intent

    def _fault(self, message: str) -> None:
        self.state = SchedulerState.FAULT
        raise SchedulerFault(message)

    def start_verified_new_round(self, context: VerifiedNewRound) -> None:
        if not (
            context.human_confirmed
            and context.stm32_safe
            and context.both_nodes_initialized
        ):
            raise PermissionError("verified new round requires all independent authorities")
        self._counter.reset_round(new_round_verified=True)
        self._round_id = context.round_id
        self.current_task = None
        self.display_model = None
        self.display_ack_intent = None
        self._seen_tasks.clear()
        self._estop_active = False
        self.state = SchedulerState.READY


__all__ = [
    "DisplayAckIntent",
    "BatchTargets",
    "FakeRenderer",
    "FakeTaskSource",
    "FakeVisionSource",
    "ImageIdMap",
    "ItemResult",
    "ItemTaskContext",
    "PendingRender",
    "RenderReceipt",
    "Scheduler",
    "SchedulerFault",
    "SchedulerState",
    "TargetReacquireResponse",
    "VerifiedNewRound",
    "VisionTarget",
    "build_item_task_queue",
]
