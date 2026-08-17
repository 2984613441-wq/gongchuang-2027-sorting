#include "ec_step_test.h"
#include "test_support.h"
static unsigned start_count, stop_count;
static ec_axis_t last_axis;
static uint32_t fake_now_ms;
bool ec_step_port_start(ec_axis_t axis, uint32_t frequency_hz) { TEST_ASSERT(frequency_hz == 10U); start_count++; last_axis = axis; return true; }
void ec_step_port_stop_all(void) { stop_count++; }
void ec_step_port_disable_all(void) { }
uint32_t ec_step_port_now_ms(void) { return fake_now_ms; }
void test_step_test(void) {
  start_count = stop_count = 0U; fake_now_ms = 100U; ec_step_test_init();
  TEST_ASSERT(ec_step_test_start(EC_AXIS_X)); TEST_ASSERT(start_count == 1U); TEST_ASSERT(last_axis == EC_AXIS_X); TEST_ASSERT(ec_step_test_active_axis() == EC_AXIS_X);
  fake_now_ms = 200U; TEST_ASSERT(ec_step_test_start(EC_AXIS_Y)); TEST_ASSERT(stop_count == 1U); TEST_ASSERT(start_count == 2U); TEST_ASSERT(ec_step_test_active_axis() == EC_AXIS_Y);
  ec_step_test_poll(5199U); TEST_ASSERT(ec_step_test_active_axis() == EC_AXIS_Y);
  ec_step_test_poll(5200U); TEST_ASSERT(ec_step_test_active_axis() == EC_AXIS_NONE); TEST_ASSERT(stop_count == 2U);
  TEST_ASSERT(!ec_step_test_start((ec_axis_t)99)); TEST_ASSERT(start_count == 2U);
}
