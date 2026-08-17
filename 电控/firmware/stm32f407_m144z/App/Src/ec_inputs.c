#include "ec_inputs.h"

#define EC_INPUT_DEBOUNCE_MS UINT32_C(20)

void ec_inputs_init(ec_input_filter_t *filter, uint16_t raw_mask,
                    uint32_t now_ms)
{
    uint16_t masked = raw_mask & EC_INPUT_ALL_MASK;
    uint32_t input_index;
    filter->raw_mask = masked;
    filter->candidate_mask = masked;
    filter->stable_mask = masked;
    for (input_index = 0U; input_index < 9U; ++input_index) {
        filter->candidate_since_ms[input_index] = now_ms;
    }
}

void ec_inputs_update(ec_input_filter_t *filter, uint16_t raw_mask,
                      uint32_t now_ms)
{
    uint16_t masked = raw_mask & EC_INPUT_ALL_MASK;
    uint32_t input_index;
    filter->raw_mask = masked;

    for (input_index = 0U; input_index < 9U; ++input_index) {
        uint16_t bit = (uint16_t)(UINT16_C(1) << input_index);
        uint16_t raw_bit = masked & bit;
        uint16_t candidate_bit = filter->candidate_mask & bit;

        if (raw_bit != candidate_bit) {
            filter->candidate_mask ^= bit;
            filter->candidate_since_ms[input_index] = now_ms;
        } else if (((filter->stable_mask & bit) != candidate_bit) &&
                   ((uint32_t)(now_ms -
                               filter->candidate_since_ms[input_index]) >=
                    EC_INPUT_DEBOUNCE_MS)) {
            if (candidate_bit != 0U) {
                filter->stable_mask |= bit;
            } else {
                filter->stable_mask &= (uint16_t)~bit;
            }
        }
    }
}

uint16_t ec_inputs_stable_mask(const ec_input_filter_t *filter)
{
    return filter->stable_mask;
}

uint16_t ec_inputs_active_mask(const ec_input_filter_t *filter)
{
    return (uint16_t)((~filter->stable_mask) & EC_INPUT_ALL_MASK);
}
