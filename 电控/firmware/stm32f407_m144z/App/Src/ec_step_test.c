#include "ec_step_test.h"

#define EC_STEP_TEST_FREQUENCY_HZ UINT32_C(10)
#define EC_STEP_TEST_DURATION_MS  UINT32_C(5000)

static ec_axis_t active_axis;
static uint32_t started_at_ms;

void ec_step_test_init(void)
{
    active_axis = EC_AXIS_NONE;
    started_at_ms = 0U;
}

bool ec_step_test_start(ec_axis_t axis)
{
    if ((axis != EC_AXIS_X) && (axis != EC_AXIS_Y) &&
        (axis != EC_AXIS_Z)) {
        return false;
    }

    ec_step_test_stop();
    ec_step_port_disable_all();
    if (!ec_step_port_start(axis, EC_STEP_TEST_FREQUENCY_HZ)) {
        return false;
    }

    active_axis = axis;
    started_at_ms = ec_step_port_now_ms();
    return true;
}

void ec_step_test_stop(void)
{
    if (active_axis != EC_AXIS_NONE) {
        ec_step_port_stop_all();
        active_axis = EC_AXIS_NONE;
    }
    ec_step_port_disable_all();
}

void ec_step_test_poll(uint32_t now_ms)
{
    if ((active_axis != EC_AXIS_NONE) &&
        ((uint32_t)(now_ms - started_at_ms) >= EC_STEP_TEST_DURATION_MS)) {
        ec_step_test_stop();
    }
}

ec_axis_t ec_step_test_active_axis(void)
{
    return active_axis;
}
