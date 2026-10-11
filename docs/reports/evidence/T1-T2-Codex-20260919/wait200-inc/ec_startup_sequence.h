#ifndef EC_STARTUP_SEQUENCE_H
#define EC_STARTUP_SEQUENCE_H

#include <stdint.h>

typedef enum {
    EC_STARTUP_IDLE = 0,
    EC_STARTUP_RUNNING,
    EC_STARTUP_PASSED,
    EC_STARTUP_FAILED,
} ec_startup_result_t;

void ec_startup_sequence_init(void);
void ec_startup_sequence_begin_post(uint32_t now_ms);
void ec_startup_sequence_begin_homing(uint32_t now_ms);
void ec_startup_sequence_begin_barrier(uint32_t now_ms);

ec_startup_result_t ec_startup_sequence_poll_post(uint32_t now_ms,
                                                   uint16_t active_inputs);
ec_startup_result_t ec_startup_sequence_poll_homing(uint32_t now_ms,
                                                     uint16_t active_inputs);
ec_startup_result_t ec_startup_sequence_poll_barrier(uint32_t now_ms,
                                                      uint16_t active_inputs);

void ec_startup_sequence_reset(void);

#endif
