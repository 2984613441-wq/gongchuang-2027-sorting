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
    EC_STEP_TEST_MOTION_COUNTED
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
void ec_step_port_stop_all(void);
void ec_step_port_disable_all(void);
uint32_t ec_step_port_now_ms(void);
uint32_t ec_step_port_counted_remaining(void);
uint32_t ec_step_port_counted_target(void);

#endif
