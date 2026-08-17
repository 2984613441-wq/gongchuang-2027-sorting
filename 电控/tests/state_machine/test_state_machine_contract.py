from __future__ import annotations

import unittest

from electrical_control.protocol import DisplayAckReceived

from electrical_control.state_machine import (
    ActionKind,
    BarrierAvoidanceVerified,
    EmergencyStop,
    FakeHal,
    ItemResultReceived,
    ItemTaskReceived,
    ManualReset,
    MotionDone,
    NoiseReceived,
    ObservableMotionProgress,
    PowerPermissionLost,
    PureStateMachine,
    State,
    TaskSafetyValidated,
    TimeObserved,
)


class PureStateMachineContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hal = FakeHal()
        self.machine = PureStateMachine.ready_for_task(self.hal, round_id=7, now=10.0)
        self.task = ItemTaskReceived(7, 11, target="BIN_BLUE")

    def accept_task(self) -> None:
        self.machine.consume(self.task, now=11.0)
        self.machine.consume(TaskSafetyValidated(7, 11, valid=True), now=11.5)

    def test_wait_task_requires_explicit_safety_validation_before_motion(self) -> None:
        self.machine.consume(self.task, now=11.0)
        self.assertEqual(State.VALIDATE_TASK, self.machine.context.state)
        self.assertEqual(0, self.hal.count(ActionKind.START_MOTION))

        self.machine.consume(TaskSafetyValidated(7, 11, valid=True), now=11.5)
        self.assertEqual(State.EXECUTING, self.machine.context.state)
        self.assertEqual(1, self.hal.count(ActionKind.START_MOTION))

    def test_invalid_current_task_safety_validation_faults(self) -> None:
        self.machine.consume(self.task, now=11.0)
        self.machine.consume(TaskSafetyValidated(7, 11, valid=False), now=11.5)

        self.assertEqual(State.FAULT_LOCK, self.machine.context.state)
        self.assertEqual("TASK_SAFETY_VALIDATION_FAILED", self.machine.context.fault_code)
        self.assertEqual(0, self.hal.count(ActionKind.START_MOTION))

    def finish_motion(self, *, success: bool = True) -> None:
        self.accept_task()
        self.machine.consume(MotionDone(7, 11), now=12.0)
        self.machine.consume(ItemResultReceived(7, 11, success=success), now=13.0)

    def test_sm_once_001_duplicate_identity_resends_without_motion(self) -> None:
        self.accept_task()
        self.machine.consume(self.task, now=12.0)

        self.assertEqual(1, self.hal.count(ActionKind.START_MOTION))
        self.assertEqual(1, self.hal.count(ActionKind.RESEND_CACHED_RESPONSE))

    def test_sm_once_002_identity_payload_conflict_faults(self) -> None:
        self.accept_task()
        self.machine.consume(ItemTaskReceived(7, 11, target="BIN_RED"), now=12.0)

        self.assertEqual(State.FAULT_LOCK, self.machine.context.state)
        self.assertEqual("TASK_IDENTITY_CONFLICT", self.machine.context.fault_code)
        self.assertEqual(1, self.hal.count(ActionKind.START_MOTION))

    def test_sm_gate_001_next_task_is_rejected_and_not_hidden(self) -> None:
        self.accept_task()
        self.machine.consume(ItemTaskReceived(8, 12, target="BIN_RED"), now=12.0)

        self.assertEqual(self.task, self.machine.context.active_task)
        self.assertEqual(1, self.hal.count(ActionKind.REJECT_NEW_TASK))
        self.assertFalse(hasattr(self.machine.context, "pending_task"))

    def test_sm_gate_002_first_valid_display_ack_reopens_gate(self) -> None:
        self.finish_motion()
        self.machine.consume(
            DisplayAckReceived(task_id=7, frame_seq=21, target_seq=1, crc_match=True),
            now=14.0,
        )

        self.assertEqual(State.PREPARE_BARRIER, self.machine.context.state)
        self.assertIsNone(self.machine.context.active_task)
        self.machine.consume(BarrierAvoidanceVerified(), now=14.5)
        self.assertEqual(State.WAIT_TASK, self.machine.context.state)
        self.machine.consume(ItemTaskReceived(7, 12, target="BIN_RED"), now=15.0)
        self.machine.consume(TaskSafetyValidated(7, 12, valid=True), now=15.5)
        self.assertEqual(2, self.hal.count(ActionKind.START_MOTION))

    def test_old_round_task_is_rejected_without_becoming_active(self) -> None:
        self.machine.consume(ItemTaskReceived(6, 10, target="BIN_BLUE"), now=11.0)

        self.assertEqual(State.WAIT_TASK, self.machine.context.state)
        self.assertIsNone(self.machine.context.active_task)
        self.assertEqual(1, self.hal.count(ActionKind.REJECT_NEW_TASK))
        self.assertEqual(0, self.hal.count(ActionKind.START_MOTION))

    def test_unseen_non_increasing_frame_sequence_is_rejected(self) -> None:
        self.finish_motion()
        self.machine.consume(DisplayAckReceived(7, 21, 1, True), now=14.0)
        self.machine.consume(BarrierAvoidanceVerified(), now=14.5)

        self.machine.consume(ItemTaskReceived(7, 10, target="BIN_RED"), now=15.0)
        self.assertEqual(State.WAIT_TASK, self.machine.context.state)
        self.assertIsNone(self.machine.context.active_task)
        self.assertEqual(1, self.hal.count(ActionKind.REJECT_NEW_TASK))
        self.assertEqual(1, self.hal.count(ActionKind.START_MOTION))

    def test_sm_event_001_motion_done_is_not_item_success(self) -> None:
        self.accept_task()
        self.machine.consume(MotionDone(7, 11), now=12.0)

        self.assertEqual(State.WAIT_ITEM_RESULT, self.machine.context.state)
        self.assertIsNone(self.machine.context.active_item_succeeded)
        self.assertEqual(1, self.hal.count(ActionKind.EMIT_MOTION_DONE))

    def test_sm_event_002_only_success_result_updates_success_then_waits_ack(self) -> None:
        self.finish_motion(success=True)

        self.assertTrue(self.machine.context.active_item_succeeded)
        self.assertFalse(hasattr(self.machine.context, "success_count"))
        self.assertEqual(State.WAIT_DISPLAY_ACK, self.machine.context.state)
        self.assertEqual(1, self.hal.count(ActionKind.START_MOTION))
        self.assertEqual("SUCCESS", self.hal.actions[-1].detail)
        self.assertEqual(ActionKind.EMIT_ITEM_RESULT, self.hal.actions[-1].kind)

        failed_hal = FakeHal()
        failed = PureStateMachine.ready_for_task(failed_hal, round_id=7, now=10.0)
        failed.consume(self.task, now=11.0)
        failed.consume(TaskSafetyValidated(7, 11, valid=True), now=11.5)
        failed.consume(MotionDone(7, 11), now=12.0)
        failed.consume(ItemResultReceived(7, 11, success=False), now=13.0)
        self.assertFalse(failed.context.active_item_succeeded)
        self.assertEqual("FAILURE", failed_hal.actions[-1].detail)
        self.assertEqual(State.WAIT_DISPLAY_ACK, failed.context.state)

    def test_sm_estop_001_estop_faults_every_active_state(self) -> None:
        active_states = (
            State.POWER_ON,
            State.POST,
            State.HOMING,
            State.READY,
            State.PREPARE_BARRIER,
            State.WAIT_TASK,
            State.VALIDATE_TASK,
            State.EXECUTING,
            State.WAIT_ITEM_RESULT,
            State.REPORT_RESULT,
            State.WAIT_DISPLAY_ACK,
            State.COMPLETE,
        )
        for state in active_states:
            with self.subTest(state=state):
                hal = FakeHal()
                machine = PureStateMachine.for_test(hal, state=state, now=1.0)
                machine.consume(EmergencyStop(), now=2.0)
                self.assertEqual(State.FAULT_LOCK, machine.context.state)
                self.assertEqual(1, hal.count(ActionKind.STOP_ALL))
                self.assertEqual(1, hal.count(ActionKind.DISABLE_DRIVERS))
                self.assertEqual(1, hal.count(ActionKind.INHIBIT_POWER))

        locked_hal = FakeHal()
        locked = PureStateMachine.for_test(locked_hal, state=State.FAULT_LOCK, now=1.0)
        locked.consume(EmergencyStop(), now=2.0)
        self.assertEqual(State.FAULT_LOCK, locked.context.state)
        self.assertEqual(0, locked_hal.count(ActionKind.STOP_ALL))

    def test_expired_round_rejects_task_before_motion(self) -> None:
        self.machine.consume(self.task, now=25.0)

        self.assertEqual(State.FAULT_LOCK, self.machine.context.state)
        self.assertEqual("ROUND_TIME_EXHAUSTED", self.machine.context.fault_code)
        self.assertEqual(0, self.hal.count(ActionKind.START_MOTION))

    def test_expired_round_cannot_be_refreshed_by_progress(self) -> None:
        self.accept_task()
        self.machine.consume(ObservableMotionProgress("too-late"), now=25.0)

        self.assertEqual(State.FAULT_LOCK, self.machine.context.state)
        self.assertEqual(10.0, self.machine.context.last_observable_at)

    def test_expired_round_rejects_ack_before_reopening_gate(self) -> None:
        self.finish_motion()
        self.machine.consume(
            DisplayAckReceived(task_id=7, frame_seq=21, target_seq=1, crc_match=True),
            now=25.0,
        )

        self.assertEqual(State.FAULT_LOCK, self.machine.context.state)
        self.assertEqual("ROUND_TIME_EXHAUSTED", self.machine.context.fault_code)
        self.assertIsNotNone(self.machine.context.active_task)
        self.assertEqual(10.0, self.machine.context.last_observable_at)

    def test_homing_and_ready_do_not_use_round_deadline_before_round_start(self) -> None:
        for state in (State.HOMING, State.READY):
            with self.subTest(state=state):
                machine = PureStateMachine.for_test(FakeHal(), state=state, now=0.0)
                machine.consume(TimeObserved(), now=16.0)
                self.assertEqual(state, machine.context.state)

    def test_sm_power_001_power_permission_loss_faults_active_machine(self) -> None:
        self.accept_task()
        self.machine.consume(PowerPermissionLost(), now=12.0)

        self.assertEqual(State.FAULT_LOCK, self.machine.context.state)
        self.assertEqual("ACTUATOR_POWER_PERMISSION_LOST", self.machine.context.fault_code)

    def test_sm_time_001_noise_and_duplicates_do_not_refresh_baseline(self) -> None:
        self.accept_task()
        baseline = self.machine.context.last_observable_at
        for kind in ("heartbeat", "log", "retransmit"):
            self.machine.consume(NoiseReceived(kind), now=12.0)
        self.machine.consume(self.task, now=13.0)

        ack = DisplayAckReceived(task_id=7, frame_seq=21, target_seq=1, crc_match=True)
        self.finish_motion()
        self.machine.consume(ack, now=14.0)
        ack_baseline = self.machine.context.last_observable_at
        self.machine.consume(ack, now=15.0)

        self.assertEqual(ack_baseline, self.machine.context.last_observable_at)
        self.assertEqual(14.0, ack_baseline)

    def test_sm_time_002_only_new_progress_refreshes_and_deadline_faults(self) -> None:
        self.accept_task()
        self.machine.consume(ObservableMotionProgress("p1"), now=12.0)
        self.machine.consume(ObservableMotionProgress("p1"), now=13.0)
        self.assertEqual(12.0, self.machine.context.last_observable_at)

        self.machine.consume(TimeObserved(), now=27.0)
        self.assertEqual(State.FAULT_LOCK, self.machine.context.state)
        self.assertEqual("ROUND_TIME_EXHAUSTED", self.machine.context.fault_code)

    def test_sm_reset_001_manual_reset_clears_task_and_requires_new_startup(self) -> None:
        self.finish_motion(success=True)
        self.assertTrue(self.machine.context.active_item_succeeded)
        self.machine.consume(EmergencyStop(), now=14.0)
        self.machine.consume(ManualReset(round_closed=True, danger_area_clear=True, estop_released=True), now=15.0)

        self.assertEqual(State.POWER_ON, self.machine.context.state)
        self.assertIsNone(self.machine.context.active_task)
        self.assertEqual(8, self.machine.context.round_id)
        self.assertIsNone(self.machine.context.active_item_succeeded)
        self.assertTrue(self.machine.context.self_test_required)
        self.assertTrue(self.machine.context.homing_required)
        self.assertEqual(1, self.hal.count(ActionKind.BEGIN_NEW_STARTUP))


if __name__ == "__main__":
    unittest.main()
