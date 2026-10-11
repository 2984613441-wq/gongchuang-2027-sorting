#ifndef EC_BARRIER_TEST_H
#define EC_BARRIER_TEST_H

#include <stdbool.h>
#include <stdint.h>

#define EC_BARRIER_PULSE_MIN_US UINT16_C(500)
#define EC_BARRIER_PULSE_MAX_US UINT16_C(2500)

typedef enum {
    EC_BARRIER_TEST_IDLE = 0,
    EC_BARRIER_TEST_ARMED,
    EC_BARRIER_TEST_RUNNING
} ec_barrier_test_mode_t;

void ec_barrier_test_init(void);
bool ec_barrier_test_arm(uint16_t active_inputs, bool any_test_busy);
bool ec_barrier_test_start(uint8_t channel_mask, uint16_t pulse_us,
                           uint16_t active_inputs, bool any_test_busy);
void ec_barrier_test_stop(void);
void ec_barrier_test_poll(uint32_t now_ms, uint16_t active_inputs);
bool ec_barrier_test_is_armed(void);
bool ec_barrier_test_is_active(void);
bool ec_barrier_test_blocks_other(void);
ec_barrier_test_mode_t ec_barrier_test_mode(void);
uint8_t ec_barrier_test_active_mask(void);
uint16_t ec_barrier_test_pulse_us(void);

bool ec_barrier_port_start_mask(uint8_t channel_mask, uint16_t pulse_us);
void ec_barrier_port_stop(void);
uint32_t ec_barrier_port_now_ms(void);

#endif
