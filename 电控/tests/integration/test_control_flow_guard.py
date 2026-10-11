"""Cross-layer host tests for the compensating integration guard.

These tests exercise the real protocol codec, active-content validator, pure
state machine, and fake HAL.  ITEM_TASK starts at the validated logical event
because its complete wire format is deliberately not frozen.
"""

from __future__ import annotations

import unittest

from electrical_control.integration import ControlFlowGuard, NodeRestarted
from electrical_control.protocol import (
    Command,
    Device,
    DirectionError,
    DisplayContent,
    Frame,
    ItemTaskPayload,
    PayloadError,
    encode_display_ack_payload,
)
from electrical_control.state_machine import (
    ActionKind,
    BarrierAvoidanceVerified,
    FakeHal,
    ItemResultReceived,
    ItemTaskReceived,
    ManualReset,
    MotionDone,
    PureStateMachine,
    State,
    TaskSafetyValidated,
)


class ControlFlowGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hal = FakeHal()
        machine = PureStateMachine.ready_for_task(self.hal, round_id=7, now=10.0)
        self.guard = ControlFlowGuard(
            machine,
            task_dedup_capacity=2,
            display_ack_dedup_capacity=2,
            result_dedup_capacity=2,
            validated_item_contexts={
                (7, 11): ItemTaskPayload(1, 2, 3, 0, 0, 0, None, None),
                (7, 12): ItemTaskPayload(2, 4, 5, 0, 0, 0, None, None),
            },
        )
        self.task = ItemTaskReceived(7, 11, target="BIN_RED")
        self.content = DisplayContent(1, 2, 3, 1, 0)

    def accept_task(self) -> None:
        self.guard.consume(self.task, now=11.0)
        self.guard.consume(TaskSafetyValidated(7, 11, valid=True), now=11.5)

    def wait_for_ack(self) -> None:
        self.accept_task()
        self.guard.consume(MotionDone(7, 11), now=12.0)
        self.guard.consume(ItemResultReceived(7, 11, success=True), now=13.0)

    def ack_frame(
        self,
        *,
        frame_seq: int = 21,
        task_id: int = 7,
        sender: Device = Device.RASPI,
        receiver: Device = Device.STM32,
        content: DisplayContent | None = None,
        payload: bytes | None = None,
    ) -> Frame:
        actual_content = self.content if content is None else content
        return Frame(
            sender=sender,
            receiver=receiver,
            task_id=task_id,
            frame_seq=frame_seq,
            command=Command.DISPLAY_ACK,
            payload=(
                encode_display_ack_payload(actual_content, render_result=0)
                if payload is None
                else payload
            ),
        )

    def test_xl_ack_001_valid_ack_alone_reopens_barrier_preparation(self) -> None:
        self.wait_for_ack()

        self.guard.consume_display_ack(
            self.ack_frame(), now=14.0
        )

        self.assertEqual(State.PREPARE_BARRIER, self.guard.machine.context.state)
        self.assertIsNone(self.guard.machine.context.active_task)
        self.assertEqual(1, self.hal.count(ActionKind.START_MOTION))

    def test_xl_ack_002_bad_crc_never_reaches_state_machine(self) -> None:
        self.wait_for_ack()
        actions_before = list(self.hal.actions)
        bad = bytearray(encode_display_ack_payload(self.content, render_result=0))
        bad[-1] ^= 1

        with self.assertRaises(PayloadError):
            self.guard.consume_display_ack(
                self.ack_frame(payload=bytes(bad)),
                now=14.0,
            )

        self.assertEqual(State.WAIT_DISPLAY_ACK, self.guard.machine.context.state)
        self.assertIsNotNone(self.guard.machine.context.active_task)
        self.assertEqual(actions_before, self.hal.actions)

    def test_xl_ack_003_wrong_target_never_reaches_state_machine(self) -> None:
        self.wait_for_ack()
        actions_before = list(self.hal.actions)
        wrong = DisplayContent(2, 2, 3, 1, 0)

        with self.assertRaises(PayloadError):
            self.guard.consume_display_ack(
                self.ack_frame(content=wrong),
                now=14.0,
            )

        self.assertEqual(State.WAIT_DISPLAY_ACK, self.guard.machine.context.state)
        self.assertEqual(actions_before, self.hal.actions)

    def test_review_ack_context_cannot_be_self_asserted_by_caller(self) -> None:
        self.wait_for_ack()
        forged = DisplayContent(99, 88, 77, 66, 55)

        with self.assertRaises(PayloadError):
            self.guard.consume_display_ack(self.ack_frame(content=forged), now=14.0)

        self.assertEqual(State.WAIT_DISPLAY_ACK, self.guard.machine.context.state)
        self.assertIsNotNone(self.guard.machine.context.active_task)

    def test_xl_ack_004_reverse_direction_never_reaches_state_machine(self) -> None:
        self.wait_for_ack()
        actions_before = list(self.hal.actions)

        with self.assertRaises(DirectionError):
            self.guard.consume_display_ack(
                self.ack_frame(sender=Device.STM32, receiver=Device.RASPI),
                now=14.0,
            )

        self.assertEqual(State.WAIT_DISPLAY_ACK, self.guard.machine.context.state)
        self.assertEqual(actions_before, self.hal.actions)

    def test_xl_ack_005_duplicate_valid_ack_is_idempotent(self) -> None:
        self.wait_for_ack()
        frame = self.ack_frame()
        self.guard.consume_display_ack(
            frame, now=14.0
        )
        self.guard.consume_display_ack(
            frame, now=14.5
        )

        self.assertEqual(State.PREPARE_BARRIER, self.guard.machine.context.state)
        self.assertEqual(1, self.hal.count(ActionKind.START_MOTION))
        self.assertEqual(1, self.hal.count(ActionKind.RESEND_CACHED_RESPONSE))

    def test_xl_once_001_duplicate_logical_task_moves_only_once(self) -> None:
        self.guard.consume(self.task, now=11.0)
        self.guard.consume(self.task, now=11.1)
        self.guard.consume(TaskSafetyValidated(7, 11, valid=True), now=11.5)

        self.assertEqual(1, self.hal.count(ActionKind.START_MOTION))
        self.assertEqual(1, self.hal.count(ActionKind.RESEND_CACHED_RESPONSE))

    def test_xl_gate_001_next_task_waits_for_ack_and_barrier_verification(self) -> None:
        self.wait_for_ack()
        self.guard.consume(ItemTaskReceived(7, 12, target="BIN_BLUE"), now=13.5)
        self.assertEqual(1, self.hal.count(ActionKind.REJECT_NEW_TASK))

        self.guard.consume_display_ack(
            self.ack_frame(), now=14.0
        )
        self.guard.consume(ItemTaskReceived(7, 12, target="BIN_BLUE"), now=14.1)
        self.assertEqual(2, self.hal.count(ActionKind.REJECT_NEW_TASK))
        self.guard.consume(BarrierAvoidanceVerified(), now=14.2)
        self.assertEqual(State.WAIT_TASK, self.guard.machine.context.state)
        self.assertEqual(1, self.hal.count(ActionKind.START_MOTION))

    def test_xl_restart_locks_once_and_rejects_old_round_after_manual_reset(self) -> None:
        self.accept_task()
        self.guard.consume(NodeRestarted("RASPI"), now=12.0)
        self.guard.consume(NodeRestarted("STM32"), now=12.1)
        self.guard.consume(MotionDone(7, 11), now=12.2)

        self.assertEqual(State.FAULT_LOCK, self.guard.machine.context.state)
        self.assertEqual("NODE_RESTARTED_CONTEXT_LOST", self.guard.fault_code)
        self.assertEqual(1, self.hal.count(ActionKind.STOP_ALL))
        self.assertEqual(1, self.hal.count(ActionKind.DISABLE_DRIVERS))
        self.assertEqual(1, self.hal.count(ActionKind.INHIBIT_POWER))

        self.guard.consume(
            ManualReset(True, True, True),
            now=13.0,
        )
        self.guard.machine.context.state = State.WAIT_TASK
        self.guard.consume(self.task, now=14.0)
        self.assertEqual(State.WAIT_TASK, self.guard.machine.context.state)
        self.assertEqual(1, self.hal.count(ActionKind.START_MOTION))
        self.assertEqual(1, self.hal.count(ActionKind.REJECT_NEW_TASK))

    def test_xl_old_round_and_non_increasing_frames_never_move(self) -> None:
        self.guard.consume(ItemTaskReceived(6, 10, target="BIN_OLD"), now=11.0)
        self.guard.consume(self.task, now=11.1)
        self.guard.consume(TaskSafetyValidated(7, 11, valid=True), now=11.2)
        self.guard.consume(MotionDone(7, 11), now=11.3)
        self.guard.consume(ItemResultReceived(7, 11, success=True), now=11.4)
        self.guard.consume_display_ack(
            self.ack_frame(), now=11.5
        )
        self.guard.consume(BarrierAvoidanceVerified(), now=11.6)
        self.guard.consume(ItemTaskReceived(7, 10, target="BIN_STALE"), now=11.7)

        self.assertEqual(State.WAIT_TASK, self.guard.machine.context.state)
        self.assertEqual(2, self.hal.count(ActionKind.REJECT_NEW_TASK))
        self.assertEqual(1, self.hal.count(ActionKind.START_MOTION))

    def test_xl_cache_capacity_is_explicit_positive_non_boolean(self) -> None:
        for value in (None, 0, -1, True, False):
            with self.subTest(value=value):
                with self.assertRaises((TypeError, ValueError)):
                    ControlFlowGuard(
                        PureStateMachine.ready_for_task(FakeHal(), round_id=1, now=0),
                        task_dedup_capacity=value,
                        display_ack_dedup_capacity=1,
                        result_dedup_capacity=1,
                        validated_item_contexts={},
                    )

    def test_xl_cache_full_preserves_known_identity_and_locks_on_new_identity(self) -> None:
        guard = ControlFlowGuard(
            PureStateMachine.ready_for_task(self.hal, round_id=7, now=10.0),
            task_dedup_capacity=1,
            display_ack_dedup_capacity=1,
            result_dedup_capacity=1,
            validated_item_contexts={(7, 11): ItemTaskPayload(1, 2, 3, 0, 0, 0, None, None)},
        )
        guard.consume(self.task, now=11.0)
        guard.consume(self.task, now=11.1)
        self.assertIsNone(guard.fault_code)
        self.assertEqual(1, self.hal.count(ActionKind.RESEND_CACHED_RESPONSE))

        guard.machine.context.state = State.WAIT_TASK
        guard.machine.context.active_task = None
        guard.consume(ItemTaskReceived(7, 12, target="BIN_BLUE"), now=11.2)

        self.assertEqual(State.FAULT_LOCK, guard.machine.context.state)
        self.assertEqual("TASK_DEDUP_CAPACITY_EXHAUSTED", guard.fault_code)
        self.assertIn((7, 11), guard.task_identities)
        self.assertNotIn((7, 12), guard.task_identities)
        self.assertEqual(0, self.hal.count(ActionKind.START_MOTION))

    def test_xl_ack_cache_full_locks_before_release_and_keeps_old_identity(self) -> None:
        guard = ControlFlowGuard(
            PureStateMachine.ready_for_task(self.hal, round_id=7, now=10.0),
            task_dedup_capacity=2,
            display_ack_dedup_capacity=1,
            result_dedup_capacity=2,
            validated_item_contexts={
                (7, 11): ItemTaskPayload(1, 2, 3, 0, 0, 0, None, None),
                (7, 12): ItemTaskPayload(2, 4, 5, 0, 0, 0, None, None),
            },
        )
        guard.consume(self.task, now=11.0)
        guard.consume(TaskSafetyValidated(7, 11, valid=True), now=11.5)
        guard.consume(MotionDone(7, 11), now=12.0)
        guard.consume(ItemResultReceived(7, 11, success=True), now=13.0)
        guard.consume_display_ack(
            self.ack_frame(), now=14.0
        )
        guard.consume(BarrierAvoidanceVerified(), now=14.1)
        second = ItemTaskReceived(7, 12, target="BIN_BLUE")
        guard.consume(second, now=14.2)
        guard.consume(TaskSafetyValidated(7, 12, valid=True), now=14.3)
        guard.consume(MotionDone(7, 12), now=14.4)
        guard.consume(ItemResultReceived(7, 12, success=True), now=14.5)
        second_content = DisplayContent(2, 4, 5, 2, 0)
        guard.consume_display_ack(
            self.ack_frame(frame_seq=22, content=second_content),
            now=14.6,
        )

        self.assertEqual(State.FAULT_LOCK, guard.machine.context.state)
        self.assertEqual("DISPLAY_ACK_DEDUP_CAPACITY_EXHAUSTED", guard.fault_code)
        self.assertIsNotNone(guard.machine.context.active_task)
        self.assertEqual({(7, 21)}, set(guard.display_ack_identities))

    def test_xl_result_cache_full_locks_before_second_result_or_release(self) -> None:
        guard = ControlFlowGuard(
            PureStateMachine.ready_for_task(self.hal, round_id=7, now=10.0),
            task_dedup_capacity=2,
            display_ack_dedup_capacity=2,
            result_dedup_capacity=1,
            validated_item_contexts={
                (7, 11): ItemTaskPayload(1, 2, 3, 0, 0, 0, None, None),
                (7, 12): ItemTaskPayload(2, 4, 5, 0, 0, 0, None, None),
            },
        )
        guard.consume(self.task, now=11.0)
        guard.consume(TaskSafetyValidated(7, 11, valid=True), now=11.5)
        guard.consume(MotionDone(7, 11), now=12.0)
        guard.consume(ItemResultReceived(7, 11, success=True), now=13.0)
        guard.consume_display_ack(
            self.ack_frame(), now=14.0
        )
        guard.consume(BarrierAvoidanceVerified(), now=14.1)
        guard.consume(ItemTaskReceived(7, 12, target="BIN_BLUE"), now=14.2)
        guard.consume(TaskSafetyValidated(7, 12, valid=True), now=14.3)
        guard.consume(MotionDone(7, 12), now=14.4)
        guard.consume(ItemResultReceived(7, 12, success=True), now=14.5)

        self.assertEqual(State.FAULT_LOCK, guard.machine.context.state)
        self.assertEqual("RESULT_DEDUP_CAPACITY_EXHAUSTED", guard.fault_code)
        self.assertEqual(2, self.hal.count(ActionKind.START_MOTION))
        self.assertEqual(1, self.hal.count(ActionKind.EMIT_ITEM_RESULT))
        self.assertEqual({(7, 11)}, set(guard.result_identities))

    def test_xl_count_overflow_locks_on_256th_success(self) -> None:
        def target_of(seq: int) -> int:
            return ((seq - 1) % 255) + 1

        guard = ControlFlowGuard(
            PureStateMachine.ready_for_task(self.hal, round_id=7, now=10.0),
            task_dedup_capacity=256,
            display_ack_dedup_capacity=256,
            result_dedup_capacity=256,
            validated_item_contexts={
                (7, seq): ItemTaskPayload(
                    target_of(seq), target_of(seq), target_of(seq), 0, 0, 0,
                    None, None,
                )
                for seq in range(1, 257)
            },
        )
        for seq in range(1, 256):
            now = 10.0 + seq * 0.001
            target = target_of(seq)
            guard.consume(
                ItemTaskReceived(7, seq, target=f"BIN_{target}"), now=now
            )
            guard.consume(TaskSafetyValidated(7, seq, valid=True), now=now + 0.001)
            guard.consume(MotionDone(7, seq), now=now + 0.002)
            guard.consume(ItemResultReceived(7, seq, success=True), now=now + 0.003)
            content = DisplayContent(target, target, target, seq, 0)
            guard.consume_display_ack(
                self.ack_frame(frame_seq=seq + 100, content=content),
                now=now + 0.004,
            )
            guard.consume(BarrierAvoidanceVerified(), now=now + 0.005)

        self.assertEqual(State.WAIT_TASK, guard.machine.context.state)
        self.assertIsNone(guard.fault_code)

        # The 256th potentially-successful item is already in flight when the
        # one-byte counter is at 255; its result must fail closed, not raise.
        now = 10.0 + 256 * 0.001
        guard.consume(ItemTaskReceived(7, 256, target="BIN_1"), now=now)
        guard.consume(TaskSafetyValidated(7, 256, valid=True), now=now + 0.001)
        guard.consume(MotionDone(7, 256), now=now + 0.002)
        guard.consume(ItemResultReceived(7, 256, success=True), now=now + 0.003)

        self.assertEqual(State.FAULT_LOCK, guard.machine.context.state)
        self.assertEqual("SUCCESS_COUNT_OVERFLOW", guard.fault_code)


if __name__ == "__main__":
    unittest.main()
