#include "ec_barrier_test.h"

#include "ec_inputs.h"

#define EC_BARRIER_ARM_WINDOW_MS UINT32_C(10000)
#define EC_BARRIER_HOLD_MS       UINT32_C(3000)
#define EC_BARRIER_ALL_MASK      UINT8_C(0x0F)

static ec_barrier_test_mode_t mode;
static uint32_t armed_at_ms;
static uint32_t started_at_ms;
static uint8_t active_mask;
static uint16_t active_pulse_us;

static bool has_inhibit(uint16_t active_inputs)
{
    return (active_inputs & EC_INPUT_ALL_MASK) != 0U;
}

static bool is_valid_mask(uint8_t channel_mask)
{
    return (channel_mask != 0U) &&
           ((channel_mask & (uint8_t)~EC_BARRIER_ALL_MASK) == 0U);
}

static bool is_valid_pulse(uint16_t pulse_us)
{
    return (pulse_us >= EC_BARRIER_PULSE_MIN_US) &&
           (pulse_us <= EC_BARRIER_PULSE_MAX_US);
}

static void clear_state(void)
{
    mode = EC_BARRIER_TEST_IDLE;
    armed_at_ms = 0U;
    started_at_ms = 0U;
    active_mask = 0U;
    active_pulse_us = 0U;
}

void ec_barrier_test_init(void)
{
    clear_state();
}

bool ec_barrier_test_arm(uint16_t active_inputs, bool any_test_busy)
{
    if ((mode != EC_BARRIER_TEST_IDLE) || has_inhibit(active_inputs) ||
        any_test_busy) {
        return false;
    }

    armed_at_ms = ec_barrier_port_now_ms();
    mode = EC_BARRIER_TEST_ARMED;
    return true;
}

bool ec_barrier_test_start(uint8_t channel_mask, uint16_t pulse_us,
                           uint16_t active_inputs, bool any_test_busy)
{
    uint32_t now_ms = ec_barrier_port_now_ms();
    bool authorized = (mode == EC_BARRIER_TEST_ARMED) &&
                      ((uint32_t)(now_ms - armed_at_ms) <=
                       EC_BARRIER_ARM_WINDOW_MS);

    if (!authorized) {
        if (mode != EC_BARRIER_TEST_RUNNING) {
            clear_state();
        }
        return false;
    }

    /* Every accepted START consumes the authorization, even on failure. */
    clear_state();
    if (!is_valid_mask(channel_mask) || !is_valid_pulse(pulse_us) ||
        has_inhibit(active_inputs) || any_test_busy) {
        return false;
    }
    if (!ec_barrier_port_start_mask(channel_mask, pulse_us)) {
        ec_barrier_port_stop();
        return false;
    }

    mode = EC_BARRIER_TEST_RUNNING;
    started_at_ms = now_ms;
    active_mask = channel_mask;
    active_pulse_us = pulse_us;
    return true;
}

void ec_barrier_test_stop(void)
{
    if (mode == EC_BARRIER_TEST_RUNNING) {
        ec_barrier_port_stop();
    }
    clear_state();
}

void ec_barrier_test_poll(uint32_t now_ms, uint16_t active_inputs)
{
    if (mode == EC_BARRIER_TEST_ARMED) {
        if (has_inhibit(active_inputs) ||
            ((uint32_t)(now_ms - armed_at_ms) >
             EC_BARRIER_ARM_WINDOW_MS)) {
            clear_state();
        }
        return;
    }

    if (mode == EC_BARRIER_TEST_RUNNING) {
        if (has_inhibit(active_inputs) ||
            ((uint32_t)(now_ms - started_at_ms) >=
             EC_BARRIER_HOLD_MS)) {
            ec_barrier_test_stop();
        }
    }
}

bool ec_barrier_test_is_armed(void)
{
    return mode == EC_BARRIER_TEST_ARMED;
}

bool ec_barrier_test_is_active(void)
{
    return mode == EC_BARRIER_TEST_RUNNING;
}

bool ec_barrier_test_blocks_other(void)
{
    return mode != EC_BARRIER_TEST_IDLE;
}

ec_barrier_test_mode_t ec_barrier_test_mode(void)
{
    return mode;
}

uint8_t ec_barrier_test_active_mask(void)
{
    return active_mask;
}

uint16_t ec_barrier_test_pulse_us(void)
{
    return active_pulse_us;
}
