#ifndef EC_STEP_TEST_H
#define EC_STEP_TEST_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    EC_AXIS_NONE = 0,
    EC_AXIS_X,
    EC_AXIS_Y,
    EC_AXIS_Z
} ec_axis_t;

void ec_step_test_init(void);
bool ec_step_test_start(ec_axis_t axis);
void ec_step_test_stop(void);
void ec_step_test_poll(uint32_t now_ms);
ec_axis_t ec_step_test_active_axis(void);

bool ec_step_port_start(ec_axis_t axis, uint32_t frequency_hz);
void ec_step_port_stop_all(void);
void ec_step_port_disable_all(void);
uint32_t ec_step_port_now_ms(void);

#endif
