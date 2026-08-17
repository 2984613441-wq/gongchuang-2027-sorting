import unittest

from electrical_control.drivers import (
    Direction,
    DriverDisabledError,
    DriverStoppedError,
    FakePulsePort,
    MotionParametersNotConfigured,
    MotionSegment,
    PulsePortFault,
    StepDirAxisDriver,
)


class StepDirAxisDriverTests(unittest.TestCase):
    def setUp(self):
        self.port = FakePulsePort()
        self.driver = StepDirAxisDriver(self.port)
        self.driver.enable()

    def test_drv_skel_001_direction_precedes_first_step(self):
        self.driver.start_segment(MotionSegment(Direction.FORWARD, step_requests=1))
        self.driver.emit_step()

        self.assertEqual(
            self.port.events,
            [("ENABLE", True), ("DIR", Direction.FORWARD), ("STEP", None)],
        )

    def test_drv_skel_002_stop_prevents_additional_steps(self):
        self.driver.start_segment(MotionSegment(Direction.REVERSE, step_requests=2))
        self.driver.emit_step()
        self.driver.stop()
        count_at_stop = self.port.step_count

        with self.assertRaises(DriverStoppedError):
            self.driver.emit_step()

        self.assertEqual(self.port.step_count, count_at_stop)
        self.assertEqual(self.port.events[-1], ("STOP", None))

    def test_disable_rejects_motion(self):
        self.driver.disable()

        with self.assertRaises(DriverDisabledError):
            self.driver.start_segment(
                MotionSegment(Direction.FORWARD, step_requests=1)
            )

        self.assertEqual(self.port.step_count, 0)

    def test_pulse_port_fault_propagates_to_caller(self):
        self.port.fail_next("STEP", PulsePortFault("pulse request rejected"))
        self.driver.start_segment(MotionSegment(Direction.FORWARD, step_requests=1))

        with self.assertRaisesRegex(PulsePortFault, "pulse request rejected"):
            self.driver.emit_step()

    def test_stop_fault_still_latches_local_stop_before_propagating(self):
        self.driver.start_segment(MotionSegment(Direction.FORWARD, step_requests=2))
        self.driver.emit_step()
        count_before_stop = self.port.step_count
        self.port.fail_next("STOP", PulsePortFault("stop request rejected"))

        with self.assertRaisesRegex(PulsePortFault, "stop request rejected"):
            self.driver.stop()
        with self.assertRaises(DriverStoppedError):
            self.driver.emit_step()

        self.assertEqual(self.port.step_count, count_before_stop)

    def test_disable_fault_still_latches_local_disable_before_propagating(self):
        self.port.fail_next("ENABLE", PulsePortFault("disable request rejected"))

        with self.assertRaisesRegex(PulsePortFault, "disable request rejected"):
            self.driver.disable()
        with self.assertRaises(DriverDisabledError):
            self.driver.start_segment(
                MotionSegment(Direction.FORWARD, step_requests=1)
            )

        self.assertEqual(self.port.step_count, 0)

    def test_direction_fault_discards_old_segment_and_rejects_later_steps(self):
        self.driver.start_segment(MotionSegment(Direction.FORWARD, step_requests=2))
        self.driver.emit_step()
        count_before_fault = self.port.step_count
        self.port.fail_next("DIR", PulsePortFault("direction request rejected"))

        with self.assertRaisesRegex(PulsePortFault, "direction request rejected"):
            self.driver.start_segment(
                MotionSegment(Direction.REVERSE, step_requests=1)
            )
        with self.assertRaises(PulsePortFault):
            self.driver.emit_step()

        self.assertEqual(self.port.step_count, count_before_fault)

    def test_enable_fault_leaves_adapter_disabled_and_rejects_later_steps(self):
        self.driver.disable()
        self.port.fail_next("ENABLE", PulsePortFault("enable request rejected"))

        with self.assertRaisesRegex(PulsePortFault, "enable request rejected"):
            self.driver.enable()
        with self.assertRaisesRegex(PulsePortFault, "enable request rejected"):
            self.driver.start_segment(
                MotionSegment(Direction.FORWARD, step_requests=1)
            )

        self.assertEqual(self.port.step_count, 0)

    def test_enable_fault_is_latched_and_rejects_enable_retry(self):
        self.driver.disable()
        self.port.fail_next("ENABLE", PulsePortFault("enable request rejected"))

        with self.assertRaisesRegex(PulsePortFault, "enable request rejected"):
            self.driver.enable()
        with self.assertRaisesRegex(PulsePortFault, "enable request rejected"):
            self.driver.enable()

        self.assertEqual(self.port.step_count, 0)

    def test_pulse_port_fault_is_latched_and_rejects_later_steps(self):
        self.port.fail_next("STEP", PulsePortFault("pulse request rejected"))
        self.driver.start_segment(MotionSegment(Direction.FORWARD, step_requests=2))

        with self.assertRaisesRegex(PulsePortFault, "pulse request rejected"):
            self.driver.emit_step()

        with self.assertRaises(PulsePortFault):
            self.driver.emit_step()
        self.assertEqual(0, self.port.step_count)

    def test_repeated_poll_does_not_generate_extra_pulses(self):
        self.driver.start_segment(MotionSegment(Direction.FORWARD, step_requests=1))
        before = self.port.step_count

        first = self.driver.poll()
        second = self.driver.poll()

        self.assertEqual(first, second)
        self.assertEqual(self.port.step_count, before)

    def test_missing_motion_parameters_are_rejected_without_defaults(self):
        with self.assertRaises(MotionParametersNotConfigured):
            self.driver.start_segment(None)

        self.assertEqual(self.port.events, [("ENABLE", True)])


if __name__ == "__main__":
    unittest.main()
