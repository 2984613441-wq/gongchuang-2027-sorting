#include "ec_step_test.h"
#include "ec_inputs.h"
#include "test_support.h"
static unsigned start_count, stop_count, direction_count, enable_count;
static unsigned counted_start_count;
static ec_axis_t last_axis;
static uint32_t last_frequency_hz;
static uint32_t last_counted_steps;
static uint32_t last_counted_hz;
static uint32_t fake_counted_remaining;
static uint32_t fake_now_ms;
static unsigned counted_xy_start_count;
static unsigned enable_xy_count;
static uint32_t fake_x_remaining;
static uint32_t fake_y_remaining;
static uint32_t fake_x_target;
static uint32_t fake_y_target;
static ec_direction_t last_x_direction;
static ec_direction_t last_y_direction;
bool ec_step_port_start(ec_axis_t axis, uint32_t frequency_hz) { TEST_ASSERT((frequency_hz == 10U) || (frequency_hz == 100U)); start_count++; last_axis = axis; last_frequency_hz = frequency_hz; return true; }
bool ec_step_port_start_counted(ec_axis_t axis, uint32_t frequency_hz, uint32_t steps) { counted_start_count++; last_axis = axis; last_counted_steps = steps; last_counted_hz = frequency_hz; fake_counted_remaining = steps; return true; }
bool ec_step_port_set_direction(ec_axis_t axis, ec_direction_t direction) { TEST_ASSERT((direction == EC_DIRECTION_0) || (direction == EC_DIRECTION_1)); direction_count++; last_axis = axis; if (axis == EC_AXIS_X) last_x_direction = direction; else if (axis == EC_AXIS_Y) last_y_direction = direction; return true; }
bool ec_step_port_enable_axis(ec_axis_t axis) { enable_count++; last_axis = axis; return true; }
void ec_step_port_stop_all(void) { stop_count++; }
void ec_step_port_disable_all(void) { }
uint32_t ec_step_port_now_ms(void) { return fake_now_ms; }
uint32_t ec_step_port_counted_remaining(void) { return fake_counted_remaining; }
uint32_t ec_step_port_counted_target(void) { return last_counted_steps; }
bool ec_step_port_start_counted_xy(uint32_t x_steps, uint32_t x_frequency_hz, uint32_t y_steps, uint32_t y_frequency_hz) { (void)x_frequency_hz; (void)y_frequency_hz; counted_xy_start_count++; fake_x_target = fake_x_remaining = x_steps; fake_y_target = fake_y_remaining = y_steps; return true; }
bool ec_step_port_enable_xy(void) { enable_xy_count++; return true; }
uint32_t ec_step_port_counted_remaining_for(ec_axis_t axis) { return (axis == EC_AXIS_X) ? fake_x_remaining : fake_y_remaining; }
uint32_t ec_step_port_counted_target_for(ec_axis_t axis) { return (axis == EC_AXIS_X) ? fake_x_target : fake_y_target; }
bool ec_step_port_counted_all_done(void) { return (fake_x_remaining == 0U) && (fake_y_remaining == 0U); }
void test_step_test(void) {
  start_count = stop_count = direction_count = enable_count = 0U;
  counted_start_count = 0U;
  last_counted_steps = 0U;
  last_counted_hz = 0U;
  fake_counted_remaining = 0U;
  last_frequency_hz = 0U;
  fake_now_ms = 100U; ec_step_test_init();
  TEST_ASSERT(ec_step_test_start(EC_AXIS_X));
  TEST_ASSERT(start_count == 1U); TEST_ASSERT(last_axis == EC_AXIS_X);
  TEST_ASSERT(last_frequency_hz == 10U);
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
  TEST_ASSERT(last_frequency_hz == 100U);
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_MOTION_RUNNING);
  ec_step_test_poll(6021U, EC_INPUT_X_HOME);
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_IDLE);
  TEST_ASSERT(ec_step_test_active_axis() == EC_AXIS_NONE);

  fake_now_ms = 7000U; TEST_ASSERT(ec_motion_test_arm(0U));
  fake_now_ms = 17001U;
  TEST_ASSERT(!ec_motion_test_start(EC_AXIS_Y, EC_DIRECTION_1, 0U));
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_IDLE);

  fake_now_ms = 18000U; TEST_ASSERT(ec_motion_test_arm(0U));
  TEST_ASSERT(!ec_motion_test_start(EC_AXIS_Z, EC_DIRECTION_1, 0U));
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_IDLE);
  ec_step_test_stop(); /* clear the unconsumed arm from the rejected Z start */

  fake_now_ms = 25000U;
  counted_start_count = 0U;
  last_counted_steps = 0U;
  last_counted_hz = 0U;
  fake_counted_remaining = 0U;
  TEST_ASSERT(!ec_motion_test_start_steps(EC_AXIS_X, EC_DIRECTION_0,
                                          2000U, 500U, 0U));
  TEST_ASSERT(ec_motion_test_arm(0U));
  TEST_ASSERT(ec_motion_test_start_steps(EC_AXIS_Y, EC_DIRECTION_1,
                                         2000U, 500U, 0U));
  TEST_ASSERT(counted_start_count == 1U);
  TEST_ASSERT(last_axis == EC_AXIS_Y);
  TEST_ASSERT(last_counted_steps == 2000U);
  TEST_ASSERT(last_counted_hz == 500U);
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_MOTION_COUNTED);
  TEST_ASSERT(ec_motion_test_step_target() == 2000U);
  TEST_ASSERT(ec_motion_test_step_remaining() == 2000U);
  TEST_ASSERT(ec_motion_test_step_result() == EC_STEP_RESULT_NONE);
  TEST_ASSERT(!ec_motion_test_start_steps(EC_AXIS_X, EC_DIRECTION_0,
                                          100U, 100U, 0U));
  ec_step_test_poll(25001U, EC_INPUT_X_HOME);
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_IDLE);
  TEST_ASSERT(ec_motion_test_step_result() == EC_STEP_RESULT_ABORTED);

  fake_now_ms = 26000U;
  TEST_ASSERT(ec_motion_test_arm(0U));
  TEST_ASSERT(ec_motion_test_start_steps(EC_AXIS_X, EC_DIRECTION_0,
                                         500U, 100U, 0U));
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_MOTION_COUNTED);
  ec_motion_test_on_counted_done();
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_IDLE);
  TEST_ASSERT(ec_motion_test_step_result() == EC_STEP_RESULT_DONE);

  fake_now_ms = 27000U;
  TEST_ASSERT(ec_motion_test_arm(0U));
  TEST_ASSERT(!ec_motion_test_start_steps(EC_AXIS_X, EC_DIRECTION_0,
                                          0U, 100U, 0U));
  TEST_ASSERT(!ec_motion_test_start_steps(EC_AXIS_X, EC_DIRECTION_0,
                                          100U, 5U, 0U));
  TEST_ASSERT(!ec_motion_test_start_steps(EC_AXIS_X, EC_DIRECTION_0,
                                          100U, 10001U, 0U));
  TEST_ASSERT(!ec_motion_test_start_steps(EC_AXIS_X, EC_DIRECTION_0,
                                          1000001U, 100U, 0U));
  TEST_ASSERT(ec_motion_test_is_armed());
  TEST_ASSERT(ec_motion_test_start_steps(EC_AXIS_X, EC_DIRECTION_0,
                                         100U, 100U, 0U));
  TEST_ASSERT(!ec_motion_test_is_armed());
  ec_motion_test_on_counted_done();

  fake_now_ms = 28000U;
  TEST_ASSERT(ec_motion_test_arm(0U));
  TEST_ASSERT(ec_motion_test_start_steps(EC_AXIS_X, EC_DIRECTION_0,
                                         1000000U, 100U, 0U));
  TEST_ASSERT(last_counted_steps == 1000000U);
  ec_motion_test_on_counted_done();

  fake_now_ms = 29000U;
  TEST_ASSERT(ec_motion_test_arm(0U));
  TEST_ASSERT(ec_motion_test_start_steps(EC_AXIS_X, EC_DIRECTION_0,
                                         500U, 100U, 0U));
  TEST_ASSERT(ec_motion_test_step_result() == EC_STEP_RESULT_NONE);
  ec_step_test_poll(34999U, 0U);
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_MOTION_COUNTED);
  ec_step_test_poll(35000U, 0U);
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_IDLE);
  TEST_ASSERT(ec_motion_test_step_result() == EC_STEP_RESULT_TIMEOUT);
  ec_step_test_stop();
  TEST_ASSERT(ec_motion_test_step_result() == EC_STEP_RESULT_NONE);

  /* ec_motion_inhibit_from_raw: active-low safety inputs (P2-3). */
  {
    const uint16_t safety = (uint16_t)(EC_INPUT_X_HOME | EC_INPUT_X_END |
                                       EC_INPUT_Y_HOME | EC_INPUT_Y_END |
                                       EC_INPUT_Z_UP | EC_INPUT_Z_DOWN |
                                       EC_INPUT_ESTOP_FB);
    TEST_ASSERT(!ec_motion_inhibit_from_raw(safety));        /* all HIGH -> no inhibit */
    TEST_ASSERT(ec_motion_inhibit_from_raw(0U));             /* all LOW -> inhibit */
    TEST_ASSERT(ec_motion_inhibit_from_raw(safety & (uint16_t)~EC_INPUT_ESTOP_FB)); /* ESTOP LOW -> inhibit */
  }

  /* --- dual-axis counted move (COUNTED_XY) --- */
  {
    direction_count = 0U;
    enable_xy_count = 0U;
    counted_xy_start_count = 0U;
    fake_x_remaining = fake_y_remaining = 0U;
    fake_x_target = fake_y_target = 0U;
    last_x_direction = last_y_direction = EC_DIRECTION_0;

    fake_now_ms = 30000U;
    TEST_ASSERT(!ec_motion_test_start_steps_xy(EC_DIRECTION_0, 100U,
                                               EC_DIRECTION_1, 200U, 500U, 0U));
    TEST_ASSERT(ec_motion_test_arm(0U));

    /* invalid params do not consume the arm */
    TEST_ASSERT(!ec_motion_test_start_steps_xy((ec_direction_t)9, 100U,
                                               EC_DIRECTION_1, 200U, 500U, 0U));
    TEST_ASSERT(!ec_motion_test_start_steps_xy(EC_DIRECTION_0, 0U,
                                               EC_DIRECTION_1, 200U, 500U, 0U));
    TEST_ASSERT(!ec_motion_test_start_steps_xy(EC_DIRECTION_0, 100U,
                                               EC_DIRECTION_1, 0U, 500U, 0U));
    TEST_ASSERT(!ec_motion_test_start_steps_xy(EC_DIRECTION_0, 100U,
                                               EC_DIRECTION_1, 200U, 5U, 0U));
    TEST_ASSERT(!ec_motion_test_start_steps_xy(EC_DIRECTION_0, 100U,
                                               EC_DIRECTION_1, 200U, 10001U, 0U));
    TEST_ASSERT(ec_motion_test_is_armed());

    TEST_ASSERT(ec_motion_test_start_steps_xy(EC_DIRECTION_0, 400U,
                                              EC_DIRECTION_1, 300U, 500U, 0U));
    TEST_ASSERT(!ec_motion_test_is_armed());
    TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_MOTION_COUNTED_XY);
    TEST_ASSERT(direction_count == 2U);
    TEST_ASSERT(last_x_direction == EC_DIRECTION_0);
    TEST_ASSERT(last_y_direction == EC_DIRECTION_1);
    TEST_ASSERT(enable_xy_count == 1U);
    TEST_ASSERT(counted_xy_start_count == 1U);
    TEST_ASSERT(ec_motion_test_x_step_target() == 400U);
    TEST_ASSERT(ec_motion_test_y_step_target() == 300U);
    TEST_ASSERT(ec_motion_test_x_step_remaining() == 400U);
    TEST_ASSERT(ec_motion_test_y_step_remaining() == 300U);
    TEST_ASSERT(ec_motion_test_step_result() == EC_STEP_RESULT_NONE);

    ec_motion_test_on_counted_done();
    TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_IDLE);
    TEST_ASSERT(ec_motion_test_step_result() == EC_STEP_RESULT_DONE);

    /* Abort on inhibit. */
    fake_now_ms = 40000U;
    TEST_ASSERT(ec_motion_test_arm(0U));
    TEST_ASSERT(ec_motion_test_start_steps_xy(EC_DIRECTION_0, 100U,
                                              EC_DIRECTION_0, 100U, 100U, 0U));
    TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_MOTION_COUNTED_XY);
    ec_step_test_poll(40001U, EC_INPUT_X_HOME);
    TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_IDLE);
    TEST_ASSERT(ec_motion_test_step_result() == EC_STEP_RESULT_ABORTED);

    /* Timeout: 400 steps @ 500 Hz = 800 ms + 1000 ms margin = 1800 ms. */
    fake_now_ms = 50000U;
    TEST_ASSERT(ec_motion_test_arm(0U));
    TEST_ASSERT(ec_motion_test_start_steps_xy(EC_DIRECTION_0, 400U,
                                              EC_DIRECTION_0, 400U, 500U, 0U));
    TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_MOTION_COUNTED_XY);
    ec_step_test_poll(51799U, 0U);
    TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_MOTION_COUNTED_XY);
    ec_step_test_poll(51800U, 0U);
    TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_IDLE);
    TEST_ASSERT(ec_motion_test_step_result() == EC_STEP_RESULT_TIMEOUT);
    ec_step_test_stop();
  }
}
