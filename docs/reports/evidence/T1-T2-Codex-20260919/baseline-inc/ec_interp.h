#ifndef EC_INTERP_H
#define EC_INTERP_H

/* XY-axis linear interpolation (Bresenham algorithm) for simultaneous dual-axis
 * motion. Reduces pick-place travel time by up to 29% (diagonal vs. serial).
 *
 * This module is a pure algorithm state machine: it takes start/end coordinates
 * in steps and yields which axis to move at each iteration. The caller (axis
 * driver) is responsible for actual PWM generation and safety checks.
 *
 * Usage:
 *   1. Call interp_init() with start/end positions (in steps)
 *   2. Poll interp_step() at the interpolation frequency
 *   3. Drive the returned axis (X, Y, or BOTH)
 *   4. Check interp_is_finished() for completion
 *
 * Thread safety: single-threaded only (main loop poll).
 */

#include <stdbool.h>
#include <stdint.h>

/* Axis selection bitmask returned by interp_step().
 * BOTH means both axes should step simultaneously this cycle. */
typedef enum {
    INTERP_AXIS_NONE = 0,
    INTERP_AXIS_X    = 1,
    INTERP_AXIS_Y    = 2,
    INTERP_AXIS_BOTH = 3
} interp_axis_t;

/* Interpolation state machine. Opaque to caller; initialize with interp_init(). */
typedef struct {
    int32_t x0, y0;          /* start position (steps) */
    int32_t x1, y1;          /* end position (steps) */
    int32_t x_current;       /* current X position (steps) */
    int32_t y_current;       /* current Y position (steps) */
    int32_t dx, dy;          /* absolute deltas */
    int32_t sx, sy;          /* step direction: +1 or -1 */
    int32_t error;           /* Bresenham error accumulator */
    bool finished;
} interp_state_t;

/* Initialize interpolation from (x0, y0) to (x1, y1). Positions are in steps,
 * not mm. The caller must convert mm coordinates to steps before calling this.
 *
 * Example:
 *   int32_t x0_steps = -145 * EC_AXIS_STEPS_PER_MM_X / 10;
 *   int32_t y0_steps = -145 * EC_AXIS_STEPS_PER_MM_Y / 10;
 *   interp_init(&state, x0_steps, y0_steps, target_x_steps, target_y_steps);
 */
void interp_init(interp_state_t *state,
                 int32_t x0, int32_t y0,
                 int32_t x1, int32_t y1);

/* Compute the next interpolation step using Bresenham's line algorithm.
 * Returns a bitmask indicating which axis to move:
 *   INTERP_AXIS_NONE: trajectory complete
 *   INTERP_AXIS_X:    step X only
 *   INTERP_AXIS_Y:    step Y only
 *   INTERP_AXIS_BOTH: step both X and Y simultaneously
 *
 * The caller must drive the returned axis immediately, then call interp_step()
 * again at the next interpolation cycle. Do NOT call this faster than the
 * stepper frequency allows.
 */
interp_axis_t interp_step(interp_state_t *state);

/* Check if interpolation is complete. Once finished, interp_step() will always
 * return INTERP_AXIS_NONE. */
bool interp_is_finished(const interp_state_t *state);

#endif
