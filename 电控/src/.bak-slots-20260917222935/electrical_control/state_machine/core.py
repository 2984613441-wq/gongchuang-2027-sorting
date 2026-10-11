"""Hardware-independent state transitions for the frozen control semantics.

This module deliberately contains no clocks, GPIO, UART, timers, or motor
parameters. Callers supply monotonic timestamps and already validated events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from electrical_control.protocol import DisplayAckReceived, DomainEvent


class State(Enum):
    POWER_ON = auto()
    POST = auto()
    HOMING = auto()
    READY = auto()
    PREPARE_BARRIER = auto()
    WAIT_TASK = auto()
    VALIDATE_TASK = auto()
    EXECUTING = auto()
    WAIT_ITEM_RESULT = auto()
    REPORT_RESULT = auto()
    WAIT_DISPLAY_ACK = auto()
    COMPLETE = auto()
    FAULT_LOCK = auto()


class ActionKind(Enum):
    START_MOTION = auto()
    RESEND_CACHED_RESPONSE = auto()
    REJECT_NEW_TASK = auto()
    STOP_ALL = auto()
    DISABLE_DRIVERS = auto()
    INHIBIT_POWER = auto()
    BEGIN_NEW_STARTUP = auto()
    BARRIER_READY = auto()
    EMIT_MOTION_DONE = auto()
    EMIT_ITEM_RESULT = auto()


@dataclass(frozen=True, slots=True)
class ActionIntent:
    kind: ActionKind
    task_id: int | None = None
    frame_seq: int | None = None
    detail: str | None = None


class FakeHal:
    """Records requested effects without performing movement or I/O."""

    def __init__(self) -> None:
        self.actions: list[ActionIntent] = []

    def request(self, action: ActionIntent) -> None:
        self.actions.append(action)

    def count(self, kind: ActionKind) -> int:
        return sum(action.kind is kind for action in self.actions)


@dataclass(frozen=True, slots=True)
class ItemTaskReceived(DomainEvent):
    task_id: int
    frame_seq: int
    target: str


@dataclass(frozen=True, slots=True)
class MotionDone(DomainEvent):
    task_id: int
    frame_seq: int


@dataclass(frozen=True, slots=True)
class TaskSafetyValidated(DomainEvent):
    """Result of upstream validation against frozen safety configuration."""

    task_id: int
    frame_seq: int
    valid: bool


@dataclass(frozen=True, slots=True)
class ItemResultReceived(DomainEvent):
    task_id: int
    frame_seq: int
    success: bool


@dataclass(frozen=True, slots=True)
class EmergencyStop(DomainEvent):
    pass


@dataclass(frozen=True, slots=True)
class BarrierAvoidanceVerified(DomainEvent):
    """The barrier is physically verified at its avoidance position."""

    pass


@dataclass(frozen=True, slots=True)
class PowerPermissionLost(DomainEvent):
    pass


@dataclass(frozen=True, slots=True)
class ObservableMotionProgress(DomainEvent):
    token: str


@dataclass(frozen=True, slots=True)
class NoiseReceived(DomainEvent):
    kind: str


@dataclass(frozen=True, slots=True)
class TimeObserved(DomainEvent):
    pass


@dataclass(frozen=True, slots=True)
class ManualReset(DomainEvent):
    round_closed: bool
    danger_area_clear: bool
    estop_released: bool


@dataclass(slots=True)
class StateContext:
    state: State
    round_id: int
    last_observable_at: float
    active_task: ItemTaskReceived | None = None
    active_item_succeeded: bool | None = None
    fault_code: str | None = None
    last_progress_token: str | None = None
    self_test_required: bool = False
    homing_required: bool = False
    last_accepted_frame_seq: int | None = None
    accepted_tasks: dict[tuple[int, int], ItemTaskReceived] = field(default_factory=dict)
    consumed_display_acks: set[tuple[int, int]] = field(default_factory=set)


class PureStateMachine:
    POWER_MONITORED_STATES = frozenset(
        {
            State.HOMING,
            State.READY,
            State.PREPARE_BARRIER,
            State.WAIT_TASK,
            State.VALIDATE_TASK,
            State.EXECUTING,
            State.WAIT_ITEM_RESULT,
            State.REPORT_RESULT,
            State.WAIT_DISPLAY_ACK,
        }
    )
    ESTOP_MONITORED_STATES = frozenset(State) - {State.FAULT_LOCK}
    ROUND_TIMED_STATES = frozenset(
        {
            State.PREPARE_BARRIER,
            State.WAIT_TASK,
            State.VALIDATE_TASK,
            State.EXECUTING,
            State.WAIT_ITEM_RESULT,
            State.REPORT_RESULT,
            State.WAIT_DISPLAY_ACK,
        }
    )
    OBSERVABLE_WINDOW = 15.0

    def __init__(self, hal: FakeHal, context: StateContext) -> None:
        self.hal = hal
        self.context = context

    @classmethod
    def ready_for_task(cls, hal: FakeHal, *, round_id: int, now: float) -> "PureStateMachine":
        return cls(hal, StateContext(State.WAIT_TASK, round_id, now))

    @classmethod
    def for_test(cls, hal: FakeHal, *, state: State, now: float) -> "PureStateMachine":
        return cls(hal, StateContext(state, 1, now))

    def consume(self, event: DomainEvent, *, now: float) -> None:
        if isinstance(event, EmergencyStop) and self.context.state in self.ESTOP_MONITORED_STATES:
            self._fault("ESTOP_ACTIVE")
            return
        if isinstance(event, PowerPermissionLost) and self.context.state in self.POWER_MONITORED_STATES:
            self._fault("ACTUATOR_POWER_PERMISSION_LOST")
            return
        if isinstance(event, ManualReset):
            self._manual_reset(event)
            return
        if self.context.state is State.FAULT_LOCK:
            return
        if (
            self.context.state in self.ROUND_TIMED_STATES
            and now - self.context.last_observable_at >= self.OBSERVABLE_WINDOW
        ):
            self._fault("ROUND_TIME_EXHAUSTED")
            return
        if isinstance(event, TimeObserved):
            return
        if isinstance(event, ItemTaskReceived):
            self._item_task(event)
            return
        if isinstance(event, BarrierAvoidanceVerified):
            if self.context.state is State.PREPARE_BARRIER:
                self.context.state = State.WAIT_TASK
                self.hal.request(ActionIntent(ActionKind.BARRIER_READY))
            return
        if isinstance(event, TaskSafetyValidated):
            if self.context.state is State.VALIDATE_TASK and self._matches(event.task_id, event.frame_seq):
                if not event.valid:
                    self._fault("TASK_SAFETY_VALIDATION_FAILED")
                else:
                    self.context.state = State.EXECUTING
                    self.hal.request(ActionIntent(ActionKind.START_MOTION, event.task_id, event.frame_seq))
            return
        if isinstance(event, ObservableMotionProgress):
            if self.context.state is State.EXECUTING and event.token != self.context.last_progress_token:
                self.context.last_progress_token = event.token
                self.context.last_observable_at = now
            return
        if isinstance(event, MotionDone):
            if self.context.state is State.EXECUTING and self._matches(event.task_id, event.frame_seq):
                self.hal.request(ActionIntent(ActionKind.EMIT_MOTION_DONE, event.task_id, event.frame_seq))
                self.context.state = State.WAIT_ITEM_RESULT
            return
        if isinstance(event, ItemResultReceived):
            if self.context.state is State.WAIT_ITEM_RESULT and self._matches(event.task_id, event.frame_seq):
                self.context.active_item_succeeded = event.success
                self.hal.request(
                    ActionIntent(
                        ActionKind.EMIT_ITEM_RESULT,
                        event.task_id,
                        event.frame_seq,
                        detail="SUCCESS" if event.success else "FAILURE",
                    )
                )
                self.context.state = State.WAIT_DISPLAY_ACK
            return
        if isinstance(event, DisplayAckReceived):
            self._display_ack(event, now)
            return
        if isinstance(event, NoiseReceived):
            return

    def _item_task(self, event: ItemTaskReceived) -> None:
        identity = (event.task_id, event.frame_seq)
        accepted = self.context.accepted_tasks.get(identity)
        if accepted is not None:
            if accepted != event:
                self._fault("TASK_IDENTITY_CONFLICT")
            else:
                self.hal.request(ActionIntent(ActionKind.RESEND_CACHED_RESPONSE, *identity))
            return
        if event.task_id != self.context.round_id:
            self.hal.request(ActionIntent(ActionKind.REJECT_NEW_TASK, *identity))
            return
        if (
            self.context.last_accepted_frame_seq is not None
            and event.frame_seq <= self.context.last_accepted_frame_seq
        ):
            self.hal.request(ActionIntent(ActionKind.REJECT_NEW_TASK, *identity))
            return
        if self.context.state is not State.WAIT_TASK or self.context.active_task is not None:
            self.hal.request(ActionIntent(ActionKind.REJECT_NEW_TASK, *identity))
            return
        self.context.active_task = event
        self.context.accepted_tasks[identity] = event
        self.context.last_accepted_frame_seq = event.frame_seq
        self.context.state = State.VALIDATE_TASK

    def _display_ack(self, event: DisplayAckReceived, now: float) -> None:
        """Consume an ACK already content-validated by the upstream validator."""

        ack_identity = (event.task_id, event.frame_seq)
        if ack_identity in self.context.consumed_display_acks:
            self.hal.request(ActionIntent(ActionKind.RESEND_CACHED_RESPONSE, *ack_identity))
            return
        if (
            self.context.state is not State.WAIT_DISPLAY_ACK
            or not event.crc_match
            or self.context.active_task is None
            or event.task_id != self.context.active_task.task_id
        ):
            return
        self.context.consumed_display_acks.add(ack_identity)
        self.context.last_observable_at = now
        self.context.active_task = None
        self.context.active_item_succeeded = None
        self.context.state = State.PREPARE_BARRIER

    def _matches(self, task_id: int, frame_seq: int) -> bool:
        task = self.context.active_task
        return task is not None and (task.task_id, task.frame_seq) == (task_id, frame_seq)

    def _fault(self, code: str) -> None:
        if self.context.state is State.FAULT_LOCK:
            return
        self.hal.request(ActionIntent(ActionKind.STOP_ALL))
        self.hal.request(ActionIntent(ActionKind.DISABLE_DRIVERS))
        self.hal.request(ActionIntent(ActionKind.INHIBIT_POWER))
        self.context.fault_code = code
        self.context.state = State.FAULT_LOCK

    def _manual_reset(self, event: ManualReset) -> None:
        if self.context.state not in {State.FAULT_LOCK, State.COMPLETE}:
            return
        if not (event.round_closed and event.danger_area_clear and event.estop_released):
            return
        self.context.active_task = None
        self.context.accepted_tasks.clear()
        self.context.consumed_display_acks.clear()
        self.context.last_progress_token = None
        self.context.last_accepted_frame_seq = None
        self.context.active_item_succeeded = None
        self.context.fault_code = None
        self.context.round_id += 1
        self.context.self_test_required = True
        self.context.homing_required = True
        self.context.state = State.POWER_ON
        self.hal.request(ActionIntent(ActionKind.BEGIN_NEW_STARTUP))
