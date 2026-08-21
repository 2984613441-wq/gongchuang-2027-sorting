#ifndef EC_SERVO_TEST_H
#define EC_SERVO_TEST_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    EC_SERVO_TEST_IDLE = 0,
    EC_SERVO_TEST_ARMED,
    EC_SERVO_TEST_RUNNING
} ec_servo_test_mode_t;

void ec_servo_test_init(void);
bool ec_servo_test_arm(uint16_t active_inputs, bool step_test_busy);
bool ec_servo_test_start(uint16_t pulse_us, uint16_t active_inputs,
                         bool step_test_busy);
void ec_servo_test_stop(void);
void ec_servo_test_poll(uint32_t now_ms, uint16_t active_inputs);
bool ec_servo_test_is_armed(void);
bool ec_servo_test_is_running(void);
bool ec_servo_test_blocks_step(void);
uint16_t ec_servo_test_active_pulse_us(void);
ec_servo_test_mode_t ec_servo_test_mode(void);

bool ec_servo_port_start(uint16_t pulse_us);
void ec_servo_port_stop(void);
uint32_t ec_servo_port_now_ms(void);

#endif
