#include "ec_motion_plan.h"

#include <stddef.h>
#include <string.h>

static ec_direction_t opposite_direction(ec_direction_t d)
{
    return (d == EC_DIRECTION_0) ? EC_DIRECTION_1 : EC_DIRECTION_0;
}

/* Convert one axis's waypoint-to-waypoint displacement (both mm10, device-
 * center frame) into a (positive steps, direction) pair. */
static void plan_axis_move(ec_axis_t axis, int16_t from_mm10, int16_t to_mm10,
                           ec_direction_t positive_dir,
                           uint32_t *steps, ec_direction_t *direction)
{
    int16_t delta_mm10 = (int16_t)(to_mm10 - from_mm10);

    *steps = ec_axis_mm10_to_steps(axis, delta_mm10);
    *direction = (delta_mm10 >= 0) ? positive_dir
                                   : opposite_direction(positive_dir);
}

static void set_move_xy(ec_axis_step_t *step,
                        int16_t from_x, int16_t from_y,
                        int16_t to_x, int16_t to_y)
{
    step->kind = EC_AXIS_STEP_MOVE_XY;
    plan_axis_move(EC_AXIS_X, from_x, to_x, EC_MOTION_POSITIVE_X_DIR,
                   &step->steps, &step->direction);
    plan_axis_move(EC_AXIS_Y, from_y, to_y, EC_MOTION_POSITIVE_Y_DIR,
                   &step->y_steps, &step->y_direction);
}

static void set_z_servo(ec_axis_step_t *step, uint16_t pulse_us)
{
    step->kind = EC_AXIS_STEP_Z_SERVO;
    step->servo_pulse_us = pulse_us;
}

bool ec_motion_plan_build(ec_axis_pick_place_t *out,
                          int16_t place_x_mm10, int16_t place_y_mm10)
{
    if (out == NULL) {
        return false;
    }
    if ((place_x_mm10 > EC_MOTION_WORKSPACE_LIMIT_MM10) ||
        (place_x_mm10 < -EC_MOTION_WORKSPACE_LIMIT_MM10) ||
        (place_y_mm10 > EC_MOTION_WORKSPACE_LIMIT_MM10) ||
        (place_y_mm10 < -EC_MOTION_WORKSPACE_LIMIT_MM10)) {
        return false;
    }

    (void)memset(out, 0, sizeof(*out));

    /* 0: MOVE_XY HOME -> PICK. */
    set_move_xy(&out->step[0],
                EC_MOTION_HOME_X_MM10, EC_MOTION_HOME_Y_MM10,
                EC_MOTION_PICK_X_MM10, EC_MOTION_PICK_Y_MM10);

    /* 1: Z down (lower = claw open). */
    set_z_servo(&out->step[1], EC_AXIS_Z_DOWN_US);

    /* 2: Z up (raise = claw close = grab). */
    set_z_servo(&out->step[2], EC_AXIS_Z_UP_US);

    /* 3: MOVE_XY PICK -> PLACE. */
    set_move_xy(&out->step[3],
                EC_MOTION_PICK_X_MM10, EC_MOTION_PICK_Y_MM10,
                place_x_mm10, place_y_mm10);

    /* 4: Z down (lower = claw open = release). */
    set_z_servo(&out->step[4], EC_AXIS_Z_DOWN_US);

    /* 5: Z up (raise = claw close = ready). */
    set_z_servo(&out->step[5], EC_AXIS_Z_UP_US);

    /* 6: MOVE_XY PLACE -> HOME. */
    set_move_xy(&out->step[6],
                place_x_mm10, place_y_mm10,
                EC_MOTION_HOME_X_MM10, EC_MOTION_HOME_Y_MM10);

    return true;
}
