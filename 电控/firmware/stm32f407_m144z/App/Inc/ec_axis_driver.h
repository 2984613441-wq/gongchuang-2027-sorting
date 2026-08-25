#ifndef EC_AXIS_DRIVER_H
#define EC_AXIS_DRIVER_H

/* Production pick-place executor (stm32-state-machine-pseudocode.md sec. 2
 * "AxisDriver" + sec. 6 "EXECUTE_PICK_PLACE").
 *
 * This is a polled state machine that drives the fixed 8-step pick-place
 * sequence through the existing `ec_step_port_*` (PWM + counted steps) and
 * `ec_servo_port_*` (gripper) ports. It does NOT depend on the diagnostic
 * `ec_step_test` / `ec_motion_test_*` machinery; both share only the port
 * layer, and the "one counted move at a time" invariant is enforced by the
 * port's own re-entry guard (P2-5).
 *
 * NOTE: the per-move axis/direction/step-count are supplied by the caller
 * (they are the product of the pixel->steps coordinate mapping, which is
 * BLOCKED on the mechanical transmission + A4988 MS1-3 microstepping). The
 * constants below are placeholders and are explicitly NOT calibrated.
 */

#include "ec_step_test.h"

#include <stdbool.h>
#include <stdint.h>

/* --- Config constants (PLACEHOLDERS, not calibrated) ---
 * steps_per_mm depends on the mechanical transmission (lead screw vs belt)
 * and the A4988 MS1-3 microstepping selection. Replace once the mechanical
 * group supplies the real ratios. */
#define EC_AXIS_STEPS_PER_MM_X UINT32_C(100)
#define EC_AXIS_STEPS_PER_MM_Y UINT32_C(100)
#define EC_AXIS_MOVE_FREQUENCY_HZ UINT32_C(500)
/* Gripper servo pulse widths + settle time (PLACEHOLDERS). */
#define EC_AXIS_GRIPPER_OPEN_US UINT16_C(1000)
#define EC_AXIS_GRIPPER_CLOSE_US UINT16_C(1900)
#define EC_AXIS_GRIPPER_SETTLE_MS UINT32_C(200)
/* Z-axis lift servo pulse widths (PLACEHOLDERS, not calibrated). Settle time
 * reuses EC_AXIS_GRIPPER_SETTLE_MS. */
#define EC_AXIS_Z_UP_US UINT16_C(1000)
#define EC_AXIS_Z_DOWN_US UINT16_C(1900)
/* Counted-move timeout margin, mirroring ec_step_test.c. */
#define EC_AXIS_MOVE_TIMEOUT_MARGIN_MS UINT32_C(1000)

typedef enum {
    EC_AXIS_RESULT_OK = 0,
    EC_AXIS_RESULT_BUSY,
    EC_AXIS_RESULT_INVALID_PARAM,
    EC_AXIS_RESULT_INHIBITED,
    EC_AXIS_RESULT_TIMEOUT,
    EC_AXIS_RESULT_ABORTED,
    EC_AXIS_RESULT_PORT_FAIL
} ec_axis_result_t;

typedef enum {
    EC_AXIS_STATE_IDLE = 0,
    EC_AXIS_STATE_MOVING,
    EC_AXIS_STATE_GRIPPING,
    EC_AXIS_STATE_DONE,
    EC_AXIS_STATE_FAULT
} ec_axis_state_t;

typedef enum {
    EC_AXIS_STEP_MOVE = 0,
    EC_AXIS_STEP_GRIPPER,
    EC_AXIS_STEP_Z_SERVO
} ec_axis_step_kind_t;

/* One step of the pick-place program: a single-axis counted move (X/Y), a
 * gripper servo command, or a Z-axis lift servo command. */
typedef struct {
    ec_axis_step_kind_t kind;
    ec_axis_t axis;            /* MOVE only */
    ec_direction_t direction;  /* MOVE only */
    uint32_t steps;            /* MOVE only, 1..EC_STEP_MAX_STEPS */
    uint16_t servo_pulse_us;   /* GRIPPER / Z_SERVO only */
} ec_axis_step_t;

/* Fixed 8-step program (sec. 6 EXECUTE_PICK_PLACE):
 *   0 move pickApproach, 1 move pick, 2 gripper close, 3 move safeTransfer,
 *   4 move placeApproach, 5 move place, 6 gripper open, 7 move home. */
#define EC_AXIS_PICK_PLACE_STEP_COUNT 8U

typedef struct {
    ec_axis_step_t step[EC_AXIS_PICK_PLACE_STEP_COUNT];
} ec_axis_pick_place_t;

void ec_axis_driver_init(void);
ec_axis_result_t ec_axis_driver_self_test(void);
ec_axis_result_t ec_axis_driver_start_pick_place(
    const ec_axis_pick_place_t *program);
ec_axis_result_t ec_axis_driver_poll(uint32_t now_ms, uint16_t active_inputs);
void ec_axis_driver_stop(void);
ec_axis_state_t ec_axis_driver_state(void);
ec_axis_result_t ec_axis_driver_result(void);
/* Number of completed program steps (0..8). This is the observable progress
 * fed to the 15-second deadline rule; each completed move increments it. */
uint32_t ec_axis_driver_progress(void);

#endif
