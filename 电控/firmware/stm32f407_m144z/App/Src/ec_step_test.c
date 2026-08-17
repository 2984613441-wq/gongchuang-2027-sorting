#include "ec_step_test.h"

#include "ec_inputs.h"

#define EC_STEP_TEST_FREQUENCY_HZ UINT32_C(10)
#define EC_STEP_TEST_DURATION_MS  UINT32_C(5000)
#define EC_MOTION_ARM_WINDOW_MS   UINT32_C(10000)
#define EC_MOTION_SETTLE_MS       UINT32_C(20)
#define EC_MOTION_DURATION_MS     UINT32_C(2000)
#define EC_MOTION_SAFETY_MASK                                             \
    (EC_INPUT_X_HOME | EC_INPUT_X_END | EC_INPUT_Y_HOME | EC_INPUT_Y_END | \
     EC_INPUT_Z_UP | EC_INPUT_Z_DOWN | EC_INPUT_ESTOP_FB)

static ec_axis_t active_axis;
static uint32_t started_at_ms;
static uint32_t armed_at_ms;
static ec_step_test_mode_t mode;
static uint8_t motion_armed;

static bool is_valid_axis(ec_axis_t axis)
{
    return (axis == EC_AXIS_X) || (axis == EC_AXIS_Y) ||
           (axis == EC_AXIS_Z);
}

static bool has_motion_inhibit(uint16_t active_inputs)
{
    return (active_inputs & EC_MOTION_SAFETY_MASK) != 0U;
}

static void stop_active_test(void)
{
    ec_step_port_stop_all();
    ec_step_port_disable_all();
    active_axis = EC_AXIS_NONE;
    mode = EC_STEP_TEST_IDLE;
    started_at_ms = 0U;
}

void ec_step_test_init(void)
{
    active_axis = EC_AXIS_NONE;
    started_at_ms = 0U;
    armed_at_ms = 0U;
    mode = EC_STEP_TEST_IDLE;
    motion_armed = 0U;
}

bool ec_step_test_start(ec_axis_t axis)
{
    if (!is_valid_axis(axis)) return false;

    ec_step_test_stop();
    ec_step_port_disable_all();
    if (!ec_step_port_start(axis, EC_STEP_TEST_FREQUENCY_HZ)) {
        return false;
    }

    active_axis = axis;
    started_at_ms = ec_step_port_now_ms();
    mode = EC_STEP_TEST_SIGNAL_ONLY;
    return true;
}

bool ec_motion_test_arm(uint16_t active_inputs)
{
    ec_step_test_stop();
    if (has_motion_inhibit(active_inputs)) return false;

    motion_armed = 1U;
    armed_at_ms = ec_step_port_now_ms();
    return true;
}

bool ec_motion_test_start(ec_axis_t axis, ec_direction_t direction,
                          uint16_t active_inputs)
{
    uint32_t now_ms = ec_step_port_now_ms();

    if (!is_valid_axis(axis)) return false;
    if ((direction != EC_DIRECTION_0) && (direction != EC_DIRECTION_1)) {
        return false;
    }
    if ((motion_armed == 0U) ||
        ((uint32_t)(now_ms - armed_at_ms) > EC_MOTION_ARM_WINDOW_MS) ||
        has_motion_inhibit(active_inputs)) {
        motion_armed = 0U;
        return false;
    }

    motion_armed = 0U;
    stop_active_test();
    if (!ec_step_port_set_direction(axis, direction) ||
        !ec_step_port_enable_axis(axis)) {
        stop_active_test();
        return false;
    }

    active_axis = axis;
    started_at_ms = now_ms;
    mode = EC_STEP_TEST_MOTION_ARMING;
    return true;
}

void ec_step_test_stop(void)
{
    stop_active_test();
    motion_armed = 0U;
    armed_at_ms = 0U;
}

void ec_step_test_poll(uint32_t now_ms, uint16_t active_inputs)
{
    if ((motion_armed != 0U) &&
        ((uint32_t)(now_ms - armed_at_ms) > EC_MOTION_ARM_WINDOW_MS)) {
        motion_armed = 0U;
    }

    if ((mode == EC_STEP_TEST_MOTION_ARMING) ||
        (mode == EC_STEP_TEST_MOTION_RUNNING)) {
        if (has_motion_inhibit(active_inputs)) {
            stop_active_test();
            return;
        }
    }

    if ((mode == EC_STEP_TEST_MOTION_ARMING) &&
        ((uint32_t)(now_ms - started_at_ms) >= EC_MOTION_SETTLE_MS)) {
        if (!ec_step_port_start(active_axis, EC_STEP_TEST_FREQUENCY_HZ)) {
            stop_active_test();
            return;
        }
        mode = EC_STEP_TEST_MOTION_RUNNING;
        started_at_ms = now_ms;
    } else if ((mode == EC_STEP_TEST_MOTION_RUNNING) &&
               ((uint32_t)(now_ms - started_at_ms) >=
                EC_MOTION_DURATION_MS)) {
        stop_active_test();
    } else if ((mode == EC_STEP_TEST_SIGNAL_ONLY) &&
               ((uint32_t)(now_ms - started_at_ms) >=
                EC_STEP_TEST_DURATION_MS)) {
        stop_active_test();
    }
}

ec_axis_t ec_step_test_active_axis(void)
{
    return active_axis;
}

ec_step_test_mode_t ec_step_test_mode(void)
{
    return mode;
}

bool ec_motion_test_is_armed(void)
{
    return motion_armed != 0U;
}
