#ifndef EC_MOTION_PLAN_H
#define EC_MOTION_PLAN_H

/* Motion planner: maps one ITEM_TASK drop coordinate (x_mm10/y_mm10, origin =
 * device center per interface-contract sec. 5.2) to the fixed 7-step
 * pick-place program executed by ec_axis_driver. Pure logic, no HAL.
 *
 * Every constant below is a PLACEHOLDER awaiting the mechanical interface. The
 * mm->steps ratio (80 steps/mm) is theoretically derived, not measured; the
 * direction convention, home/pick waypoints, and servo pulse widths are not
 * calibrated. They are collected here (not scattered in ec_app.c) so a single
 * file is the "待实机确认" calibration surface.
 */

#include "ec_axis_driver.h"

#include <stdbool.h>
#include <stdint.h>

/* Direction convention: which physical direction a POSITIVE mm coordinate maps
 * to. Not calibrated - flip one or both after a single DIR0/DIR1 jog test on
 * the real axes. The mapping is:
 *   delta_mm10 >= 0 -> EC_MOTION_POSITIVE_*_DIR
 *   delta_mm10 <  0 -> the opposite direction.
 */
#define EC_MOTION_POSITIVE_X_DIR EC_DIRECTION_0
#define EC_MOTION_POSITIVE_Y_DIR EC_DIRECTION_0

/* Frozen workspace: |X|,|Y| <= 145.0mm (interface-contract sec. 5.2). Mirrors
 * EC_PROTO_ITEM_TASK_X_LIMIT; duplicated so this module stays self-contained. */
#define EC_MOTION_WORKSPACE_LIMIT_MM10 1450

/* Pick waypoint = fixed feed circle center. Origin is device center, so this
 * defaults to (0,0); 待实机确认. */
#define EC_MOTION_PICK_X_MM10 0
#define EC_MOTION_PICK_Y_MM10 0

/* Home (rest) waypoint in the device-center frame. PLACEHOLDER: a safe corner
 * of the +/-145mm workspace; 待实机确认. */
#define EC_MOTION_HOME_X_MM10 (-1450)
#define EC_MOTION_HOME_Y_MM10 (-1450)

/* Build the pick-place program for one item: HOME -> PICK -> Z down (open) ->
 * Z up (close = grab) -> PLACE -> Z down (open = release) -> Z up (close =
 * ready) -> HOME. The three XY waypoint moves are simultaneous dual-axis
 * (MOVE_XY); step counts and directions are derived from the mm coordinates.
 *
 * Returns false (and leaves *out untouched) if the drop coordinate is outside
 * the frozen +/-145.0mm workspace. */
bool ec_motion_plan_build(ec_axis_pick_place_t *out,
                          int16_t place_x_mm10, int16_t place_y_mm10);

#endif
