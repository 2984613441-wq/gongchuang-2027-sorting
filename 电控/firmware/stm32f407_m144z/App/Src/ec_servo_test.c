#include "ec_servo_test.h"

#include "ec_inputs.h"

#define EC_SERVO_ARM_WINDOW_MS UINT32_C(10000)
#define EC_SERVO_RUN_MS        UINT32_C(2000)
#define EC_SERVO_SAFETY_MASK                                            \
    (EC_INPUT_X_HOME | EC_INPUT_X_END | EC_INPUT_Y_HOME | EC_INPUT_Y_END | \
     EC_INPUT_Z_UP | EC_INPUT_Z_DOWN | EC_INPUT_ESTOP_FB)

static ec_servo_test_mode_t mode;
static uint32_t armed_at_ms;
static uint32_t started_at_ms;
static uint16_t active_pulse_us;

static bool has_safety_inhibit(uint16_t active_inputs)
{
    return (active_inputs & EC_SERVO_SAFETY_MASK) != 0U;
}

static bool is_allowed_pulse(uint16_t pulse_us)
{
    return (pulse_us == UINT16_C(1000)) ||
           (pulse_us == UINT16_C(1100)) ||
           (pulse_us == UINT16_C(1200)) ||
           (pulse_us == UINT16_C(1300)) ||
           (pulse_us == UINT16_C(1500)) ||
           (pulse_us == UINT16_C(1700)) ||
           (pulse_us == UINT16_C(1900));
}

static void clear_state(void)
{
    mode = EC_SERVO_TEST_IDLE;
    armed_at_ms = 0U;
    started_at_ms = 0U;
    active_pulse_us = 0U;
}

void ec_servo_test_init(void)
{
    clear_state();
}

bool ec_servo_test_arm(uint16_t active_inputs, bool step_test_busy)
{
    ec_servo_test_stop();
    if (step_test_busy || has_safety_inhibit(active_inputs)) return false;

    armed_at_ms = ec_servo_port_now_ms();
    mode = EC_SERVO_TEST_ARMED;
    return true;
}

bool ec_servo_test_start(uint16_t pulse_us, uint16_t active_inputs,
                         bool step_test_busy)
{
    uint32_t now_ms = ec_servo_port_now_ms();
    bool authorized = (mode == EC_SERVO_TEST_ARMED) &&
                      ((uint32_t)(now_ms - armed_at_ms) <=
                       EC_SERVO_ARM_WINDOW_MS);

    if (!authorized) {
        if (mode == EC_SERVO_TEST_RUNNING) return false;
        clear_state();
        return false;
    }

    /* An authorization is single-use, including rejected start attempts. */
    clear_state();
    if (!is_allowed_pulse(pulse_us) || step_test_busy ||
        has_safety_inhibit(active_inputs)) {
        return false;
    }
    if (!ec_servo_port_start(pulse_us)) {
        ec_servo_port_stop();
        return false;
    }

    mode = EC_SERVO_TEST_RUNNING;
    started_at_ms = now_ms;
    active_pulse_us = pulse_us;
    return true;
}

void ec_servo_test_stop(void)
{
    ec_servo_port_stop();
    clear_state();
}

void ec_servo_test_poll(uint32_t now_ms, uint16_t active_inputs)
{
    if (mode == EC_SERVO_TEST_ARMED) {
        if (has_safety_inhibit(active_inputs) ||
            ((uint32_t)(now_ms - armed_at_ms) > EC_SERVO_ARM_WINDOW_MS)) {
            clear_state();
        }
        return;
    }

    if (mode == EC_SERVO_TEST_RUNNING) {
        if (has_safety_inhibit(active_inputs) ||
            ((uint32_t)(now_ms - started_at_ms) >= EC_SERVO_RUN_MS)) {
            ec_servo_test_stop();
        }
    }
}

bool ec_servo_test_is_armed(void)
{
    return mode == EC_SERVO_TEST_ARMED;
}

bool ec_servo_test_is_running(void)
{
    return mode == EC_SERVO_TEST_RUNNING;
}

bool ec_servo_test_blocks_step(void)
{
    return mode != EC_SERVO_TEST_IDLE;
}

uint16_t ec_servo_test_active_pulse_us(void)
{
    return active_pulse_us;
}

ec_servo_test_mode_t ec_servo_test_mode(void)
{
    return mode;
}
