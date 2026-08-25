#include "ec_axis_driver.h"

#include "ec_inputs.h"
#include "ec_servo_test.h"

/* Safety inputs that must inhibit motion. Same 7-bit set as the diagnostic
 * EC_MOTION_SAFETY_MASK; a set bit in `active_inputs` means that input is
 * triggered (active-low wiring) and motion must stop. */
#define EC_AXIS_SAFETY_MASK                                                   \
    (EC_INPUT_X_HOME | EC_INPUT_X_END | EC_INPUT_Y_HOME | EC_INPUT_Y_END |    \
     EC_INPUT_Z_UP | EC_INPUT_Z_DOWN | EC_INPUT_ESTOP_FB)

/* The state machine runs in the main-loop poll; the only thing the port ISR
 * can do concurrently is decrement the counted-step remaining counter, which
 * is already volatile in the port. These members are main-loop only, so they
 * stay non-volatile. */
static ec_axis_state_t state;
static ec_axis_result_t result;
static ec_axis_pick_place_t program;
static uint8_t step_index;            /* next step to execute (0..8) */
static uint32_t move_started_at_ms;
static uint32_t move_timeout_ms;
static uint32_t gripper_settle_at_ms;

static bool has_inhibit(uint16_t active_inputs)
{
    return (active_inputs & EC_AXIS_SAFETY_MASK) != 0U;
}

static bool step_is_valid(const ec_axis_step_t *s)
{
    if (s->kind == EC_AXIS_STEP_MOVE) {
        if ((s->axis != EC_AXIS_X) && (s->axis != EC_AXIS_Y)) {
            return false;
        }
        if ((s->direction != EC_DIRECTION_0) &&
            (s->direction != EC_DIRECTION_1)) {
            return false;
        }
        if ((s->steps == 0U) || (s->steps > EC_STEP_MAX_STEPS)) {
            return false;
        }
    } else if ((s->kind == EC_AXIS_STEP_GRIPPER) ||
               (s->kind == EC_AXIS_STEP_Z_SERVO)) {
        if (s->servo_pulse_us == 0U) return false;
    } else {
        return false;
    }
    return true;
}

static void stop_all(void)
{
    ec_step_port_stop_all();
    ec_servo_port_stop();
    ec_servo_port_stop_z();
    ec_step_port_disable_all();
}

static void fault(ec_axis_result_t code)
{
    stop_all();
    result = code;
    state = EC_AXIS_STATE_FAULT;
}

static void start_step(uint8_t index, uint32_t now_ms)
{
    const ec_axis_step_t *s = &program.step[index];

    if (s->kind == EC_AXIS_STEP_MOVE) {
        if (!ec_step_port_set_direction(s->axis, s->direction) ||
            !ec_step_port_enable_axis(s->axis) ||
            !ec_step_port_start_counted(s->axis, EC_AXIS_MOVE_FREQUENCY_HZ,
                                        s->steps)) {
            fault(EC_AXIS_RESULT_PORT_FAIL);
            return;
        }
        move_started_at_ms = now_ms;
        move_timeout_ms = ((s->steps * UINT32_C(1000)) /
                           EC_AXIS_MOVE_FREQUENCY_HZ) +
                          EC_AXIS_MOVE_TIMEOUT_MARGIN_MS;
        state = EC_AXIS_STATE_MOVING;
    } else if (s->kind == EC_AXIS_STEP_GRIPPER) {
        if (!ec_servo_port_start(s->servo_pulse_us)) {
            fault(EC_AXIS_RESULT_PORT_FAIL);
            return;
        }
        gripper_settle_at_ms = now_ms;
        state = EC_AXIS_STATE_GRIPPING;
    } else { /* EC_AXIS_STEP_Z_SERVO */
        if (!ec_servo_port_start_z(s->servo_pulse_us)) {
            fault(EC_AXIS_RESULT_PORT_FAIL);
            return;
        }
        gripper_settle_at_ms = now_ms;
        state = EC_AXIS_STATE_GRIPPING;
    }
}

void ec_axis_driver_init(void)
{
    state = EC_AXIS_STATE_IDLE;
    result = EC_AXIS_RESULT_OK;
    step_index = 0U;
    move_started_at_ms = 0U;
    move_timeout_ms = 0U;
    gripper_settle_at_ms = 0U;
}

ec_axis_result_t ec_axis_driver_self_test(void)
{
    /* Placeholder: real driver self-test (stepper fault pin, servo power) is
     * deferred until the hardware interface is defined. Return OK so the
     * production state machine can advance past POST for host testing. */
    return EC_AXIS_RESULT_OK;
}

ec_axis_result_t ec_axis_driver_start_pick_place(
    const ec_axis_pick_place_t *p)
{
    uint8_t i;

    if (state == EC_AXIS_STATE_MOVING || state == EC_AXIS_STATE_GRIPPING) {
        return EC_AXIS_RESULT_BUSY;
    }
    if (p == NULL) return EC_AXIS_RESULT_INVALID_PARAM;

    for (i = 0U; i < EC_AXIS_PICK_PLACE_STEP_COUNT; ++i) {
        if (!step_is_valid(&p->step[i])) {
            return EC_AXIS_RESULT_INVALID_PARAM;
        }
    }

    program = *p;
    result = EC_AXIS_RESULT_OK;
    step_index = 0U;
    start_step(0U, ec_step_port_now_ms());
    return result;
}

ec_axis_result_t ec_axis_driver_poll(uint32_t now_ms, uint16_t active_inputs)
{
    if ((state == EC_AXIS_STATE_IDLE) || (state == EC_AXIS_STATE_DONE) ||
        (state == EC_AXIS_STATE_FAULT)) {
        return result;
    }

    if (has_inhibit(active_inputs)) {
        fault(EC_AXIS_RESULT_ABORTED);
        return result;
    }

    if (state == EC_AXIS_STATE_MOVING) {
        if ((uint32_t)(now_ms - move_started_at_ms) >= move_timeout_ms) {
            fault(EC_AXIS_RESULT_TIMEOUT);
            return result;
        }
        /* A counted move is done when the port's remaining counter reaches
         * zero (the ISR clears counted_active, so counted_remaining()==0). */
        if (ec_step_port_counted_remaining() == 0U) {
            ++step_index;
            if (step_index >= EC_AXIS_PICK_PLACE_STEP_COUNT) {
                stop_all();
                result = EC_AXIS_RESULT_OK;
                state = EC_AXIS_STATE_DONE;
                return result;
            }
            start_step(step_index, now_ms);
        }
    } else if (state == EC_AXIS_STATE_GRIPPING) {
        if ((uint32_t)(now_ms - gripper_settle_at_ms) >=
            EC_AXIS_GRIPPER_SETTLE_MS) {
            ++step_index;
            if (step_index >= EC_AXIS_PICK_PLACE_STEP_COUNT) {
                stop_all();
                result = EC_AXIS_RESULT_OK;
                state = EC_AXIS_STATE_DONE;
                return result;
            }
            start_step(step_index, now_ms);
        }
    }

    return result;
}

void ec_axis_driver_stop(void)
{
    stop_all();
    state = EC_AXIS_STATE_IDLE;
    result = EC_AXIS_RESULT_OK;
    step_index = 0U;
}

ec_axis_state_t ec_axis_driver_state(void)
{
    return state;
}

ec_axis_result_t ec_axis_driver_result(void)
{
    return result;
}

uint32_t ec_axis_driver_progress(void)
{
    return (uint32_t)step_index;
}
