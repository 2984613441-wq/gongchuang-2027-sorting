#include "ec_demo.h"

#include "ec_inputs.h"
#include "ec_servo_test.h"
#include "ec_step_test.h"

/* Config (PLACEHOLDER, not calibrated): 800 Hz is a clearly-visible demo
 * speed; 13200 steps = 165 mm = 16.5 s/leg at 80 steps/mm (1/16 microstep,
 * 20-tooth GT2). 165 mm matches the observed mechanical end-stop — going past
 * it caused the axis to jam. */
#define EC_DEMO_STEP_HZ          UINT32_C(800)
#define EC_DEMO_STEPS_PER_LEG    UINT32_C(13200)
#define EC_DEMO_SERVO_OPEN_US    UINT16_C(1100)
#define EC_DEMO_SERVO_CLOSE_US   UINT16_C(1900)
#define EC_DEMO_SERVO_SETTLE_MS  UINT32_C(200)
#define EC_DEMO_MOVE_TIMEOUT_MARGIN_MS UINT32_C(1000)

/* 2026-09-15 用户裁决：X/Y 不装限位开关 → 遮罩收敛为仅 ESTOP。
 * 与 ec_axis_driver.c / ec_servo_test.c / ec_step_test.c 的三处遮罩保持一致。 */
#define EC_DEMO_SAFETY_MASK  (EC_INPUT_ESTOP_FB)

typedef enum {
    EC_DEMO_PHASE_X_OUT = 0,
    EC_DEMO_PHASE_X_BACK,
    EC_DEMO_PHASE_Y_OUT,
    EC_DEMO_PHASE_Y_BACK,
    EC_DEMO_PHASE_Z_OPEN,
    EC_DEMO_PHASE_Z_CLOSE,
    EC_DEMO_PHASE_COUNT
} ec_demo_phase_t;

static bool active;
static uint8_t phase;
static uint32_t phase_started_ms;
static uint32_t move_timeout_ms;

static bool has_inhibit(uint16_t active_inputs)
{
    return (active_inputs & EC_DEMO_SAFETY_MASK) != 0U;
}

static bool phase_is_move(uint8_t p)
{
    return (p == EC_DEMO_PHASE_X_OUT) || (p == EC_DEMO_PHASE_X_BACK) ||
           (p == EC_DEMO_PHASE_Y_OUT) || (p == EC_DEMO_PHASE_Y_BACK);
}

static void stop_all(void)
{
    ec_step_port_stop_all();
    ec_servo_port_stop_z();
    ec_step_port_disable_all();
}

static void begin_phase(uint32_t now_ms)
{
    ec_axis_t axis = EC_AXIS_NONE;
    ec_direction_t direction = EC_DIRECTION_0;
    uint16_t pulse_us;

    switch (phase) {
    case EC_DEMO_PHASE_X_OUT:
        axis = EC_AXIS_X;
        direction = EC_DIRECTION_0;
        break;
    case EC_DEMO_PHASE_X_BACK:
        axis = EC_AXIS_X;
        direction = EC_DIRECTION_1;
        break;
    case EC_DEMO_PHASE_Y_OUT:
        axis = EC_AXIS_Y;
        direction = EC_DIRECTION_0;
        break;
    case EC_DEMO_PHASE_Y_BACK:
        axis = EC_AXIS_Y;
        direction = EC_DIRECTION_1;
        break;
    default:
        break;
    }

    if (phase_is_move(phase)) {
        if (!ec_step_port_set_direction(axis, direction) ||
            !ec_step_port_enable_axis(axis) ||
            !ec_step_port_start_counted(axis, EC_DEMO_STEP_HZ,
                                        EC_DEMO_STEPS_PER_LEG)) {
            stop_all();
            active = false;
            return;
        }
        move_timeout_ms = ((EC_DEMO_STEPS_PER_LEG * UINT32_C(1000)) /
                           EC_DEMO_STEP_HZ) + EC_DEMO_MOVE_TIMEOUT_MARGIN_MS;
    } else {
        pulse_us = (phase == EC_DEMO_PHASE_Z_OPEN) ?
                   EC_DEMO_SERVO_OPEN_US : EC_DEMO_SERVO_CLOSE_US;
        if (!ec_servo_port_start_z(pulse_us)) {
            stop_all();
            active = false;
            return;
        }
    }
    phase_started_ms = now_ms;
}

static void advance_phase(uint32_t now_ms)
{
    phase = (uint8_t)(phase + 1U);
    if (phase >= EC_DEMO_PHASE_COUNT) {
        phase = 0U;
    }
    begin_phase(now_ms);
}

void ec_demo_init(void)
{
    active = false;
    phase = 0U;
    phase_started_ms = 0U;
    move_timeout_ms = 0U;
}

bool ec_demo_start(uint16_t active_inputs)
{
    if (active || has_inhibit(active_inputs)) return false;

    stop_all();
    active = true;
    phase = EC_DEMO_PHASE_X_OUT;
    begin_phase(ec_step_port_now_ms());
    return active;
}

void ec_demo_stop(void)
{
    if (active) {
        stop_all();
    }
    active = false;
    phase = 0U;
    phase_started_ms = 0U;
    move_timeout_ms = 0U;
}

void ec_demo_poll(uint32_t now_ms, uint16_t active_inputs)
{
    if (!active) return;

    if (has_inhibit(active_inputs)) {
        ec_demo_stop();
        return;
    }

    if (phase_is_move(phase)) {
        if ((uint32_t)(now_ms - phase_started_ms) >= move_timeout_ms) {
            ec_demo_stop();
            return;
        }
        if (ec_step_port_counted_remaining() == 0U) {
            advance_phase(now_ms);
        }
    } else {
        if ((uint32_t)(now_ms - phase_started_ms) >= EC_DEMO_SERVO_SETTLE_MS) {
            advance_phase(now_ms);
        }
    }
}

bool ec_demo_is_active(void)
{
    return active;
}
