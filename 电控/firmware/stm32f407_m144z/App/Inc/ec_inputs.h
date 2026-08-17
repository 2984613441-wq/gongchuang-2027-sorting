#ifndef EC_INPUTS_H
#define EC_INPUTS_H

#include <stdint.h>

#define EC_INPUT_X_HOME       (UINT16_C(1) << 0U)
#define EC_INPUT_X_END        (UINT16_C(1) << 1U)
#define EC_INPUT_Y_HOME       (UINT16_C(1) << 2U)
#define EC_INPUT_Y_END        (UINT16_C(1) << 3U)
#define EC_INPUT_Z_UP         (UINT16_C(1) << 4U)
#define EC_INPUT_Z_DOWN       (UINT16_C(1) << 5U)
#define EC_INPUT_ESTOP_FB     (UINT16_C(1) << 6U)
#define EC_INPUT_START        (UINT16_C(1) << 7U)
#define EC_INPUT_MANUAL_RESET (UINT16_C(1) << 8U)
#define EC_INPUT_ALL_MASK     UINT16_C(0x01FF)

typedef struct {
    uint16_t raw_mask;
    uint16_t stable_mask;
    uint16_t active_mask;
} ec_input_snapshot_t;

typedef struct {
    uint16_t raw_mask;
    uint16_t candidate_mask;
    uint16_t stable_mask;
    uint32_t candidate_since_ms[9];
} ec_input_filter_t;

void ec_inputs_init(ec_input_filter_t *filter, uint16_t raw_mask,
                    uint32_t now_ms);
void ec_inputs_update(ec_input_filter_t *filter, uint16_t raw_mask,
                      uint32_t now_ms);
uint16_t ec_inputs_stable_mask(const ec_input_filter_t *filter);
uint16_t ec_inputs_active_mask(const ec_input_filter_t *filter);

#endif
