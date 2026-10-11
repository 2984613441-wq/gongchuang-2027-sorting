#include "ec_interp.h"

#include <stdlib.h>

void interp_init(interp_state_t *state,
                 int32_t x0, int32_t y0,
                 int32_t x1, int32_t y1)
{
    state->x0 = x0;
    state->y0 = y0;
    state->x1 = x1;
    state->y1 = y1;
    state->x_current = x0;
    state->y_current = y0;

    state->dx = abs((int)(x1 - x0));
    state->dy = abs((int)(y1 - y0));

    state->sx = (x0 < x1) ? 1 : -1;
    state->sy = (y0 < y1) ? 1 : -1;

    state->error = state->dx - state->dy;
    state->finished = false;
}

interp_axis_t interp_step(interp_state_t *state)
{
    if (state->finished) {
        return INTERP_AXIS_NONE;
    }

    /* Check if target reached */
    if (state->x_current == state->x1 && state->y_current == state->y1) {
        state->finished = true;
        return INTERP_AXIS_NONE;
    }

    /* Bresenham decision logic */
    int32_t e2 = 2 * state->error;
    interp_axis_t axis_to_move = INTERP_AXIS_NONE;

    /* Should we step X? */
    if (e2 > -state->dy && state->x_current != state->x1) {
        state->error -= state->dy;
        state->x_current += state->sx;
        axis_to_move |= INTERP_AXIS_X;
    }

    /* Should we step Y? */
    if (e2 < state->dx && state->y_current != state->y1) {
        state->error += state->dx;
        state->y_current += state->sy;
        axis_to_move |= INTERP_AXIS_Y;
    }

    return axis_to_move;
}

bool interp_is_finished(const interp_state_t *state)
{
    return state->finished;
}
