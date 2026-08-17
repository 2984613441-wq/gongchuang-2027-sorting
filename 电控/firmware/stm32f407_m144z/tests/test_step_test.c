#include "ec_step_test.h"
#include "ec_inputs.h"
#include "test_support.h"
static unsigned start_count, stop_count, direction_count, enable_count;
static ec_axis_t last_axis;
static uint32_t fake_now_ms;
bool ec_step_port_start(ec_axis_t axis, uint32_t frequency_hz) { TEST_ASSERT(frequency_hz == 10U); start_count++; last_axis = axis; return true; }
bool ec_step_port_set_direction(ec_axis_t axis, ec_direction_t direction) { TEST_ASSERT((direction == EC_DIRECTION_0) || (direction == EC_DIRECTION_1)); direction_count++; last_axis = axis; return true; }
bool ec_step_port_enable_axis(ec_axis_t axis) { enable_count++; last_axis = axis; return true; }
void ec_step_port_stop_all(void) { stop_count++; }
void ec_step_port_disable_all(void) { }
uint32_t ec_step_port_now_ms(void) { return fake_now_ms; }
void test_step_test(void) {
  start_count = stop_count = direction_count = enable_count = 0U;
  fake_now_ms = 100U; ec_step_test_init();
  TEST_ASSERT(ec_step_test_start(EC_AXIS_X));
  TEST_ASSERT(start_count == 1U); TEST_ASSERT(last_axis == EC_AXIS_X);
  TEST_ASSERT(ec_step_test_active_axis() == EC_AXIS_X);
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_SIGNAL_ONLY);
  fake_now_ms = 200U; TEST_ASSERT(ec_step_test_start(EC_AXIS_Y));
  TEST_ASSERT(start_count == 2U); TEST_ASSERT(ec_step_test_active_axis() == EC_AXIS_Y);
  ec_step_test_poll(5199U, 0U); TEST_ASSERT(ec_step_test_active_axis() == EC_AXIS_Y);
  ec_step_test_poll(5200U, 0U); TEST_ASSERT(ec_step_test_active_axis() == EC_AXIS_NONE);
  TEST_ASSERT(!ec_step_test_start((ec_axis_t)99)); TEST_ASSERT(start_count == 2U);

  fake_now_ms = 6000U;
  TEST_ASSERT(!ec_motion_test_arm(EC_INPUT_ESTOP_FB));
  TEST_ASSERT(!ec_motion_test_is_armed());
  TEST_ASSERT(ec_motion_test_arm(0U));
  TEST_ASSERT(ec_motion_test_is_armed());
  TEST_ASSERT(ec_motion_test_start(EC_AXIS_X, EC_DIRECTION_0, 0U));
  TEST_ASSERT(!ec_motion_test_is_armed());
  TEST_ASSERT(direction_count == 1U); TEST_ASSERT(enable_count == 1U);
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_MOTION_ARMING);
  TEST_ASSERT(start_count == 2U);
  ec_step_test_poll(6019U, 0U); TEST_ASSERT(start_count == 2U);
  ec_step_test_poll(6020U, 0U); TEST_ASSERT(start_count == 3U);
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_MOTION_RUNNING);
  ec_step_test_poll(6021U, EC_INPUT_X_HOME);
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_IDLE);
  TEST_ASSERT(ec_step_test_active_axis() == EC_AXIS_NONE);

  fake_now_ms = 7000U; TEST_ASSERT(ec_motion_test_arm(0U));
  fake_now_ms = 17001U;
  TEST_ASSERT(!ec_motion_test_start(EC_AXIS_Y, EC_DIRECTION_1, 0U));
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_IDLE);

  fake_now_ms = 18000U; TEST_ASSERT(ec_motion_test_arm(0U));
  TEST_ASSERT(ec_motion_test_start(EC_AXIS_Z, EC_DIRECTION_1, 0U));
  ec_step_test_poll(18020U, 0U);
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_MOTION_RUNNING);
  ec_step_test_poll(20019U, 0U);
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_MOTION_RUNNING);
  ec_step_test_poll(20020U, 0U);
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_IDLE);
}
