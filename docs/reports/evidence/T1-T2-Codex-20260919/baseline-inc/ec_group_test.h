#ifndef EC_GROUP_TEST_H
#define EC_GROUP_TEST_H

#include "ec_step_test.h"

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    EC_GROUP_TEST_IDLE = 0,
    EC_GROUP_TEST_ARMED,
    EC_GROUP_TEST_SETTLING,
    EC_GROUP_TEST_RUNNING
} ec_group_test_mode_t;

void ec_group_test_init(void);
bool ec_group_test_arm(uint16_t active_inputs, bool step_busy,
                       bool servo_busy);
bool ec_group_test_start(ec_direction_t x_direction,
                         ec_direction_t y_direction, uint16_t servo_pulse_us,
                         uint16_t active_inputs, bool step_busy,
                         bool servo_busy);
void ec_group_test_stop(void);
void ec_group_test_poll(uint32_t now_ms, uint16_t active_inputs);
bool ec_group_test_is_armed(void);
bool ec_group_test_is_active(void);
bool ec_group_test_blocks_single(void);
ec_group_test_mode_t ec_group_test_mode(void);
ec_direction_t ec_group_test_x_direction(void);
ec_direction_t ec_group_test_y_direction(void);
uint16_t ec_group_test_servo_pulse_us(void);

bool ec_group_port_set_direction(ec_axis_t axis, ec_direction_t direction);
bool ec_group_port_enable_xy(void);
bool ec_group_port_start_step(ec_axis_t axis, uint32_t frequency_hz);
bool ec_group_port_start_servo(uint16_t pulse_us);
void ec_group_port_stop_all(void);
uint32_t ec_group_port_now_ms(void);

#endif
