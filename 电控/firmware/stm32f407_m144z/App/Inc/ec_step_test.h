#ifndef EC_STEP_TEST_H
#define EC_STEP_TEST_H

#include <stdbool.h>
#include <stdint.h>

#define EC_STEP_MIN_HZ UINT32_C(10)
#define EC_STEP_MAX_HZ UINT32_C(10000)
/* 🔴 2026-09-20 收紧：1000000 → 16000（用户裁决"收紧到真实行程 + 一点余量"）。
 *
 * 原值 1000000 步 = 12.5 米（@80 步/mm），而 X/Y 机械行程只有 190mm 左右，
 * 且 **X/Y 不装限位开关**（2026-09-15 用户裁决）⇒ 一次手误的 MOVE 就能把轴顶死。
 * 历史：X+ 越程堵转已发生 3 次（`ec_motion_plan.h:145`）。
 *
 * 16000 步 = 200mm，依据：
 *   · 单腿最长 = 行程全程 —— X 185mm（−95.0 → +90.0）、Y 190mm（−97.5 → +92.5）
 *   · 200mm 留 10mm 余量，**覆盖所有合法运动**，台架小步增量工具照常可用
 *   · 只挡住"不可能合法"的超长命令
 *
 * ⚠️ 本常量虽在"台架测试"头文件里，**生产路径也在用**：
 *    `ec_axis_driver.c:90/97/98/116`、`ec_board_stm32.c:370`、`ec_diag.c:199`
 *    ⇒ 改这里等于同时收紧三条路径。（把常量挪进生产头文件才是正解，属重构，暂缓。）
 * ⚠️ 本改动需**重新编译并烧录**才生效。 */
#define EC_STEP_MAX_STEPS UINT32_C(16000)

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

/* 2026-10-22 新增：与上面同语义，但**两轴可用不同频率**。
 *
 * 用途 —— 走直线（而不是"先斜后直"的折线）：
 *   底层是"两轴同时启动、各自独立频率、各自计数到 0"，不做几何插补。
 *   只要让  x_frequency_hz / y_frequency_hz == x_steps / y_steps ，
 *   两轴就会同时到达，合成轨迹即直线（CNC 常速合成法）。
 *
 * 超时按"较慢那条腿"算：max(x_steps/x_freq, y_steps/y_freq) + margin。
 * 旧入口 ec_motion_test_start_steps_xy() 行为不变（两轴同频 = 本函数传同一值）。 */
bool ec_motion_test_start_steps_xy2(ec_direction_t x_direction, uint32_t x_steps,
                                    ec_direction_t y_direction, uint32_t y_steps,
                                    uint32_t x_frequency_hz,
                                    uint32_t y_frequency_hz,
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

/* ────────────────────────────────────────────────────────────────────────────
 * 巡航频率运行时可设（2026-10-23 新增，T8 安全速度实测用）
 *
 * 背景：巡航频率原本是 ec_board_stm32.c:start_axis_counted() 里的**硬编码
 *      5000U**。`MOVE ... HZ f` 的 f 与 EC_AXIS_MOVE_FREQUENCY_HZ 都只在
 *      ec_step_profile_plan() 失败时兜底 ⇒ 想试不同速度只能改代码重烧。
 *
 * 现在改为运行时可设：烧录一次后可用诊断命令 `SPEED <hz>` 任意扫档，
 * 每档跑一次方框测试（square_clear.py）看是否丢步，即可找出真实安全上限。
 *
 * 约束：
 *   · 取值域 [EC_STEP_MIN_HZ, EC_STEP_MAX_HZ] = [10, 10000]
 *   · 必须 > 曲线起止频率（默认 200Hz），否则 ec_step_profile_plan 会拒绝
 *   · 只在**下一条 MOVE 开始规划时**生效；正在进行的运动不受影响
 *   · 掉电恢复默认值 EC_STEP_CRUISE_HZ_DEFAULT
 * ──────────────────────────────────────────────────────────────────────────── */
/* 2026-10-23 实测结论：8000 Hz 不丢步，默认值由 5000 提到 8000。
 *
 * 方框复位测试证据（/home/pi/pi_square_fixed.py，4 腿首尾相接，不闭合即丢步）：
 *     4000Hz / 50mm  → 1.30s/腿  闭合 ✅
 *     5000Hz / 50mm  → 1.15s/腿  闭合 ✅
 *     6000Hz / 50mm  → 1.15s/腿  闭合 ✅
 *     7000Hz / 50mm  → 1.15s/腿  闭合 ✅（4000 步太短，峰值被封在 ~6328）
 *     8000Hz / 100mm → 1.75s/腿  闭合 ✅（8000 步足够，理论 1.76s 精确吻合）
 *
 * 收益：峰值 62.5mm/s → 100mm/s（+60%），直接缓解 15s 失活窗口压力。
 *
 * ⚠️ 注意：真正的峰值还受"行程是否够长"限制 —— 步数不足时曲线走三角形自动降峰。
 *    例如 4000 步在 8000Hz 设定下只能到约 6328Hz；要到 8000 需 ≥6396+步（约 80mm）。
 * ⚠️ 10000Hz 未测（需 125mm 行程，从常驻位置余量不足），擅自设 10000 无实测依据。
 */
#define EC_STEP_CRUISE_HZ_DEFAULT  UINT32_C(8000)
bool ec_step_port_set_cruise_hz(uint32_t cruise_hz);
uint32_t ec_step_port_get_cruise_hz(void);

/* Completion/abort events are latched by the STM32 timer/safety paths.  A
 * remaining count of zero is not a completion signal: stop/abort paths also
 * clear that count.  The executor consumes each latch exactly once.  For a
 * single-axis completion, *completed_axis is X or Y; for a dual-axis
 * completion it is EC_AXIS_NONE. */
bool ec_step_port_take_counted_completion(ec_axis_t *completed_axis);
bool ec_step_port_take_counted_abort(void);

#endif
