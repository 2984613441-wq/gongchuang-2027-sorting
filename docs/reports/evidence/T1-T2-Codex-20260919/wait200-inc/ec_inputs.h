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
/* bit 9: 电源许可，**高电平有效**（HIGH = 有许可，LOW = 失电）。
 * 2026-09-15 修复：此前该宏未定义，导致 ec_startup_sequence.c / ec_app.c 编译失败
 * （台账 B-03），且 EC_INPUT_ALL_MASK=0x01FF 不含本位 → 采样会被裁掉 → active 位
 * 恒为 1，反而把"假定有许可"变成"必定失电"。
 * 当前尚未接 GPIO：ec_board_stm32.c 的 read_raw_inputs() 用文档记载的临时方案
 * 强制置位（假定许可存在）。接线步骤见 POWER-PERMISSION-GPIO-SETUP.md。 */
#define EC_INPUT_POWER_PERMISSION (UINT16_C(1) << 9U)
/* 已纳入滤波与掩码的输入位个数（必须与最高位+1 一致，避免再次硬编码 9U） */
#define EC_INPUT_COUNT        UINT32_C(10)
#define EC_INPUT_ALL_MASK     UINT16_C(0x03FF)

typedef struct {
    uint16_t raw_mask;
    uint16_t stable_mask;
    uint16_t active_mask;
} ec_input_snapshot_t;

typedef struct {
    uint16_t raw_mask;
    uint16_t candidate_mask;
    uint16_t stable_mask;
    uint32_t candidate_since_ms[EC_INPUT_COUNT];
} ec_input_filter_t;

void ec_inputs_init(ec_input_filter_t *filter, uint16_t raw_mask,
                    uint32_t now_ms);
void ec_inputs_update(ec_input_filter_t *filter, uint16_t raw_mask,
                      uint32_t now_ms);
uint16_t ec_inputs_stable_mask(const ec_input_filter_t *filter);
uint16_t ec_inputs_active_mask(const ec_input_filter_t *filter);

#endif
