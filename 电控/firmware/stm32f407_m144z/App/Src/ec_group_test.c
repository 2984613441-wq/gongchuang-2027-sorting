#include "ec_group_test.h"

#include "ec_inputs.h"

#define EC_GROUP_ARM_WINDOW_MS UINT32_C(10000)
#define EC_GROUP_SETTLE_MS     UINT32_C(20)
#define EC_GROUP_RUN_MS        UINT32_C(10000)
#define EC_GROUP_STEP_HZ       UINT32_C(100)
#define EC_GROUP_OPEN_US       UINT16_C(1000)
#define EC_GROUP_CLOSE_US      UINT16_C(1900)

static ec_group_test_mode_t mode;
static uint32_t armed_at_ms;
static uint32_t phase_started_at_ms;
static ec_direction_t x_direction;
static ec_direction_t y_direction;
static uint16_t servo_pulse_us;

static bool is_valid_direction(ec_direction_t direction)
{
    return (direction == EC_DIRECTION_0) ||
           (direction == EC_DIRECTION_1);
}

static bool is_valid_servo_pulse(uint16_t pulse_us)
{
    return (pulse_us == EC_GROUP_OPEN_US) ||
           (pulse_us == EC_GROUP_CLOSE_US);
}

static bool has_inhibit(uint16_t active_inputs)
{
    return (active_inputs & EC_INPUT_ALL_MASK) != 0U;
}

static void clear_state(void)
{
    mode = EC_GROUP_TEST_IDLE;
    armed_at_ms = 0U;
    phase_started_at_ms = 0U;
    x_direction = EC_DIRECTION_0;
    y_direction = EC_DIRECTION_0;
    servo_pulse_us = 0U;
}

void ec_group_test_init(void)
{
    clear_state();
}

bool ec_group_test_arm(uint16_t active_inputs, bool step_busy,
                       bool servo_busy)
{
    if ((mode != EC_GROUP_TEST_IDLE) || has_inhibit(active_inputs) ||
        step_busy || servo_busy) {
        return false;
    }

    armed_at_ms = ec_group_port_now_ms();
    mode = EC_GROUP_TEST_ARMED;
    return true;
}

bool ec_group_test_start(ec_direction_t requested_x_direction,
                         ec_direction_t requested_y_direction,
                         uint16_t requested_servo_pulse_us,
                         uint16_t active_inputs, bool step_busy,
                         bool servo_busy)
{
    uint32_t now_ms = ec_group_port_now_ms();
    bool authorized = (mode == EC_GROUP_TEST_ARMED) &&
                      ((uint32_t)(now_ms - armed_at_ms) <=
                       EC_GROUP_ARM_WINDOW_MS);

    if (!authorized) {
        if ((mode != EC_GROUP_TEST_SETTLING) &&
            (mode != EC_GROUP_TEST_RUNNING)) {
            clear_state();
        }
        return false;
    }

    /* Every accepted START line consumes the authorization, even on failure. */
    clear_state();
    if (!is_valid_direction(requested_x_direction) ||
        !is_valid_direction(requested_y_direction) ||
        !is_valid_servo_pulse(requested_servo_pulse_us) ||
        has_inhibit(active_inputs) || step_busy || servo_busy) {
        return false;
    }

    if (!ec_group_port_set_direction(EC_AXIS_X, requested_x_direction) ||
        !ec_group_port_set_direction(EC_AXIS_Y, requested_y_direction) ||
        !ec_group_port_enable_xy()) {
        ec_group_port_stop_all();
        return false;
    }

    x_direction = requested_x_direction;
    y_direction = requested_y_direction;
    servo_pulse_us = requested_servo_pulse_us;
    phase_started_at_ms = now_ms;
    mode = EC_GROUP_TEST_SETTLING;
    return true;
}

void ec_group_test_stop(void)
{
    if ((mode == EC_GROUP_TEST_SETTLING) ||
        (mode == EC_GROUP_TEST_RUNNING)) {
        ec_group_port_stop_all();
    }
    clear_state();
}

void ec_group_test_poll(uint32_t now_ms, uint16_t active_inputs)
{
    if (mode == EC_GROUP_TEST_ARMED) {
        if (has_inhibit(active_inputs) ||
            ((uint32_t)(now_ms - armed_at_ms) >
             EC_GROUP_ARM_WINDOW_MS)) {
            clear_state();
        }
        return;
    }

    if ((mode == EC_GROUP_TEST_SETTLING) ||
        (mode == EC_GROUP_TEST_RUNNING)) {
        if (has_inhibit(active_inputs)) {
            ec_group_test_stop();
            return;
        }
    }

    if ((mode == EC_GROUP_TEST_SETTLING) &&
        ((uint32_t)(now_ms - phase_started_at_ms) >= EC_GROUP_SETTLE_MS)) {
        if (!ec_group_port_start_step(EC_AXIS_X, EC_GROUP_STEP_HZ) ||
            !ec_group_port_start_step(EC_AXIS_Y, EC_GROUP_STEP_HZ) ||
            !ec_group_port_start_servo(servo_pulse_us)) {
            ec_group_test_stop();
            return;
        }
        phase_started_at_ms = now_ms;
        mode = EC_GROUP_TEST_RUNNING;
    } else if ((mode == EC_GROUP_TEST_RUNNING) &&
               ((uint32_t)(now_ms - phase_started_at_ms) >=
                EC_GROUP_RUN_MS)) {
        ec_group_test_stop();
    }
}

bool ec_group_test_is_armed(void)
{
    return mode == EC_GROUP_TEST_ARMED;
}

bool ec_group_test_is_active(void)
{
    return (mode == EC_GROUP_TEST_SETTLING) ||
           (mode == EC_GROUP_TEST_RUNNING);
}

bool ec_group_test_blocks_single(void)
{
    return mode != EC_GROUP_TEST_IDLE;
}

ec_group_test_mode_t ec_group_test_mode(void)
{
    return mode;
}

ec_direction_t ec_group_test_x_direction(void)
{
    return x_direction;
}

ec_direction_t ec_group_test_y_direction(void)
{
    return y_direction;
}

uint16_t ec_group_test_servo_pulse_us(void)
{
    return servo_pulse_us;
}
