"""Explicit cross-layer orchestration around the frozen host-side APIs."""

from __future__ import annotations

from dataclasses import dataclass

from electrical_control.protocol import (
    DisplayAckContextValidator,
    DisplayContent,
    Frame,
    ItemTaskPayload,
    PayloadError,
    ProtocolCodec,
    RoundSuccessCounter,
    build_display_content,
)
from electrical_control.state_machine import (
    EmergencyStop,
    ItemResultReceived,
    ItemTaskReceived,
    ManualReset,
    PureStateMachine,
    State,
)


def _capacity(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an explicit positive integer")
    if value <= 0:
        raise ValueError(f"{name} must be an explicit positive integer")
    return value


@dataclass(frozen=True, slots=True)
class NodeRestarted:
    node: str

    def __post_init__(self) -> None:
        if self.node not in {"RASPI", "STM32"}:
            raise ValueError("node must be RASPI or STM32")


class ControlFlowGuard:
    """Fail-closed adapter for restart and fixed-capacity identity history.

    The contained pure state machine retains its own native fault code.  This
    adapter exposes the more specific integration fault in ``fault_code``.
    """

    def __init__(
        self,
        machine: PureStateMachine,
        *,
        task_dedup_capacity: int,
        display_ack_dedup_capacity: int,
        result_dedup_capacity: int,
        validated_item_contexts: dict[tuple[int, int], ItemTaskPayload],
    ) -> None:
        self.machine = machine
        self._task_capacity = _capacity("task_dedup_capacity", task_dedup_capacity)
        self._display_ack_capacity = _capacity(
            "display_ack_dedup_capacity", display_ack_dedup_capacity
        )
        self._result_capacity = _capacity(
            "result_dedup_capacity", result_dedup_capacity
        )
        self._task_identities: dict[tuple[int, int], ItemTaskReceived] = {}
        self._display_ack_identities: dict[tuple[int, int], bytes] = {}
        self._result_identities: dict[tuple[int, int], bool] = {}
        self._validated_item_contexts = dict(validated_item_contexts)
        self._active_item_context: ItemTaskPayload | None = None
        self._expected_display_content: DisplayContent | None = None
        self._success_counter = RoundSuccessCounter()
        self.fault_code: str | None = None
        self._codec = ProtocolCodec()
        self._ack_validator = DisplayAckContextValidator()

    @property
    def task_identities(self) -> tuple[tuple[int, int], ...]:
        return tuple(self._task_identities)

    @property
    def display_ack_identities(self) -> tuple[tuple[int, int], ...]:
        return tuple(self._display_ack_identities)

    @property
    def result_identities(self) -> tuple[tuple[int, int], ...]:
        return tuple(self._result_identities)

    def consume(self, event: object, *, now: float) -> None:
        if isinstance(event, ManualReset):
            old_round = self.machine.context.round_id
            self.machine.consume(event, now=now)
            if self.machine.context.round_id != old_round:
                self._clear_for_verified_new_round()
            return
        if self.machine.context.state is State.FAULT_LOCK:
            return
        if isinstance(event, NodeRestarted):
            self._lock("NODE_RESTARTED_CONTEXT_LOST", now)
            return
        if isinstance(event, ItemTaskReceived):
            self._consume_task(event, now)
            return
        if isinstance(event, ItemResultReceived):
            self._consume_result(event, now)
            return
        self.machine.consume(event, now=now)

    def consume_display_ack(
        self,
        frame: Frame,
        *,
        now: float,
    ) -> None:
        if self.machine.context.state is State.FAULT_LOCK:
            return
        message = self._codec.to_validated_message(frame)
        expected = self._expected_display_content
        if expected is None:
            raise PayloadError("DISPLAY_ACK has no internally locked display context")
        event = self._ack_validator.to_domain_event(
            message, expected_display_content=expected
        )
        identity = (frame.task_id, frame.frame_seq)
        payload = bytes(frame.payload)
        known = self._display_ack_identities.get(identity)
        if known is not None:
            if known != payload:
                self._lock("DISPLAY_ACK_IDENTITY_CONFLICT", now)
                return
            self.machine.consume(event, now=now)
            return
        if len(self._display_ack_identities) >= self._display_ack_capacity:
            self._lock("DISPLAY_ACK_DEDUP_CAPACITY_EXHAUSTED", now)
            return
        if (
            self.machine.context.state is State.WAIT_DISPLAY_ACK
            and self.machine.context.active_task is not None
            and event.task_id == self.machine.context.active_task.task_id
        ):
            self._display_ack_identities[identity] = payload
        self.machine.consume(event, now=now)

    def _consume_task(self, event: ItemTaskReceived, now: float) -> None:
        identity = (event.task_id, event.frame_seq)
        known = self._task_identities.get(identity)
        if known is not None:
            if known != event:
                self._lock("TASK_IDENTITY_CONFLICT", now)
                return
            self.machine.consume(event, now=now)
            return
        eligible = (
            self.machine.context.state is State.WAIT_TASK
            and self.machine.context.active_task is None
            and event.task_id == self.machine.context.round_id
            and (
                self.machine.context.last_accepted_frame_seq is None
                or event.frame_seq > self.machine.context.last_accepted_frame_seq
            )
        )
        if eligible and len(self._task_identities) >= self._task_capacity:
            self._lock("TASK_DEDUP_CAPACITY_EXHAUSTED", now)
            return
        self.machine.consume(event, now=now)
        if eligible and self.machine.context.active_task == event:
            self._task_identities[identity] = event
            self._active_item_context = self._validated_item_contexts.get(identity)
            self._expected_display_content = None
            if self._active_item_context is None:
                self._lock("VALIDATED_ITEM_CONTEXT_MISSING", now)

    def _consume_result(self, event: ItemResultReceived, now: float) -> None:
        identity = (event.task_id, event.frame_seq)
        known = self._result_identities.get(identity)
        if known is not None:
            if known != event.success:
                self._lock("RESULT_IDENTITY_CONFLICT", now)
                return
            self.machine.consume(event, now=now)
            return
        relevant = (
            self.machine.context.state is State.WAIT_ITEM_RESULT
            and self.machine.context.active_task is not None
            and (event.task_id, event.frame_seq)
            == (
                self.machine.context.active_task.task_id,
                self.machine.context.active_task.frame_seq,
            )
        )
        if relevant and len(self._result_identities) >= self._result_capacity:
            self._lock("RESULT_DEDUP_CAPACITY_EXHAUSTED", now)
            return
        if relevant and self._active_item_context is None:
            self._lock("VALIDATED_ITEM_CONTEXT_MISSING", now)
            return
        if relevant:
            result_code = 0 if event.success else 1
            self._success_counter.record_item_result(
                task_id=event.task_id,
                frame_seq=event.frame_seq,
                result_code=result_code,
            )
            self._expected_display_content = build_display_content(
                item_task=self._active_item_context,
                success_count=self._success_counter.value,
                result_code=result_code,
            )
        self.machine.consume(event, now=now)
        if relevant and self.machine.context.state is State.WAIT_DISPLAY_ACK:
            self._result_identities[identity] = event.success

    def _lock(self, code: str, now: float) -> None:
        if self.machine.context.state is State.FAULT_LOCK:
            return
        self.fault_code = code
        self.machine.consume(EmergencyStop(), now=now)

    def _clear_for_verified_new_round(self) -> None:
        self._task_identities.clear()
        self._display_ack_identities.clear()
        self._result_identities.clear()
        self._active_item_context = None
        self._expected_display_content = None
        self._success_counter.reset_round(new_round_verified=True)
        self.fault_code = None
