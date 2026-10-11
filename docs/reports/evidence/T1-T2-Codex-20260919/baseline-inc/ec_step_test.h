#ifndef EC_STEP_TEST_H
#define EC_STEP_TEST_H

#include <stdbool.h>
#include <stdint.h>

#define EC_STEP_MIN_HZ UINT32_C(10)
#define EC_STEP_MAX_HZ UINT32_C(10000)
#define EC_STEP_MAX_STEPS UINT32_C(1000000)

typedef enum {
    EC_AXIS_NONE = 0,
    EC_AXIS_X,
    EC_AXIS_Y,
    EC_AXIS_Z
} ec_axis_t;

typedef enum {
    EC_DIRECTION_0 = 0,
    EC_DIRECTION_1 = 1
} ec_direction_t;

typedef enum {
    EC_STEP_TEST_IDLE = 0,
    EC_STEP_TEST_SIGNAL_ONLY,
    EC_STEP_TEST_MOTION_ARMING,
    EC_STEP_TEST_MOTION_RUNNING,
    EC_STEP_TEST_MOTION_COUNTED,
    /* 2026-09-15 双轴：X/Y 同时计数的斜线/联动移动。追加在末尾，保持既有
     * 枚举值不变，避免动到已冻结的单轴行为。 */
    EC_STEP_TEST_MOTION_COUNTED_XY
} ec_step_test_mode_t;

typedef enum {
    EC_STEP_RESULT_NONE = 0,
    EC_STEP_RESULT_DONE,
    EC_STEP_RESULT_TIMEOUT,
    EC_STEP_RESULT_ABORTED
} ec_step_result_t;

void ec_step_test_init(void);
bool ec_step_test_start(ec_axis_t axis);
bool ec_motion_test_arm(uint16_t active_inputs);
bool ec_motion_test_start(ec_axis_t axis, ec_direction_t direction,
                          uint16_t active_inputs);
bool ec_motion_test_start_steps(ec_axis_t axis, ec_direction_t direction,
                                uint32_t steps, uint32_t frequency_hz,
                                uint16_t active_inputs);
/* Dual-axis counted move: X and Y start together and are counted down
 * independently. Either leg may be zero, but not both (an axis-aligned move
 * is valid). The timeout is derived from the slower (larger) axis. Consumes
 * the armed window exactly like ec_motion_test_start_steps(). */
bool ec_motion_test_start_steps_xy(ec_direction_t x_direction, uint32_t x_steps,
                                   ec_direction_t y_direction, uint32_t y_steps,
                                   uint32_t frequency_hz,
                                   uint16_t active_inputs);
uint32_t ec_motion_test_x_step_target(void);
uint32_t ec_motion_test_y_step_target(void);
uint32_t ec_motion_test_x_step_remaining(void);
uint32_t ec_motion_test_y_step_remaining(void);
void ec_motion_test_on_counted_done(void);
bool ec_motion_inhibit_from_raw(uint16_t raw_mask);
void ec_motion_test_on_aborted(void);
void ec_step_test_stop(void);
void ec_step_test_poll(uint32_t now_ms, uint16_t active_inputs);
ec_axis_t ec_step_test_active_axis(void);
ec_step_test_mode_t ec_step_test_mode(void);
bool ec_motion_test_is_armed(void);
uint32_t ec_motion_test_step_target(void);
uint32_t ec_motion_test_step_remaining(void);
ec_step_result_t ec_motion_test_step_result(void);

bool ec_step_port_start(ec_axis_t axis, uint32_t frequency_hz);
bool ec_step_port_start_counted(ec_axis_t axis, uint32_t frequency_hz,
                                uint32_t steps);
bool ec_step_port_set_direction(ec_axis_t axis, ec_direction_t direction);
bool ec_step_port_enable_axis(ec_axis_t axis);
/* Dual-axis port primitives (2026-09-15). enable_xy() enables both drivers;
 * start_counted_xy() arms both axes in one go, each with its own step count and
 * its own step frequency. counted_remaining() returns X+Y while an XY move is
 * active for diagnostics only; completion is reported through the explicit
 * completion latch below, because an abort/stop path also clears remaining. */
bool ec_step_port_enable_xy(void);
bool ec_step_port_start_counted_xy(uint32_t x_steps, uint32_t x_frequency_hz,
                                   uint32_t y_steps, uint32_t y_frequency_hz);
uint32_t ec_step_port_counted_remaining_for(ec_axis_t axis);
uint32_t ec_step_port_counted_target_for(ec_axis_t axis);
/* True once every axis of the active counted move has counted down to zero. */
bool ec_step_port_counted_all_done(void);
void ec_step_port_stop_all(void);
void ec_step_port_disable_all(void);
uint32_t ec_step_port_now_ms(void);
uint32_t ec_step_port_counted_remaining(void);
uint32_t ec_step_port_counted_target(void);

/* Completion/abort events are latched by the STM32 timer/safety paths.  A
 * remaining count of zero is not a completion signal: stop/abort paths also
 * clear that count.  The executor consumes each latch exactly once.  For a
 * single-axis completion, *completed_axis is X or Y; for a dual-axis
 * completion it is EC_AXIS_NONE. */
bool ec_step_port_take_counted_completion(ec_axis_t *completed_axis);
bool ec_step_port_take_counted_abort(void);

#endif
