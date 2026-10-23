#include "ec_board_stm32.h"

#include "ec_app.h"
#include "ec_barrier_test.h"
#include "ec_board.h"
#include "ec_diag.h"
#include "ec_group_test.h"
#include "ec_inputs.h"
#include "ec_light_ws2812.h"
#include "ec_safety_adapter.h"
#include "ec_servo_test.h"
#include "ec_step_test.h"
#include "ec_step_profile.h"

#include <stddef.h>
#include <string.h>

extern TIM_HandleTypeDef htim2;
extern TIM_HandleTypeDef htim3;
extern TIM_HandleTypeDef htim4;
extern TIM_HandleTypeDef htim8;
extern TIM_HandleTypeDef htim9;
extern TIM_HandleTypeDef htim10;
extern TIM_HandleTypeDef htim11;
extern UART_HandleTypeDef huart2;

/* Step-timer counting clock = 100 kHz (HSI 16 MHz / (PSC+1=160), PSC=159).
 * Coupled to main.c SystemClock_Config + MX_TIMx_Init: if the system clock or
 * PSC changes, this value must be updated or the step frequency shifts. */
#define EC_STEP_TIMER_HZ UINT32_C(100000)

/* 2026-10-23：巡航频率从硬编码改为运行时可设（T8 安全速度实测）。
 *
 * 原实现把 5000U 直接写在 start_axis_counted() 的 ec_step_profile_plan() 调用里，
 * 想试其它速度必须改代码重烧。现在改成这个变量，可用诊断命令 `SPEED <hz>` 改。
 *
 * ⚠️ 语义：这是【轨迹曲线的巡航上限】，不是最终速度。若运动步数不足以跑完
 *    加速段+减速段，曲线会走"三角形"把峰值降到更低 —— 见 ec_step_profile.c。
 * ⚠️ 真正的上限受电机/驱动能力限制，且**丢步无硬件可发现**（X/Y 无限位开关）。
 *    提档后必须用方框测试验证复位（/home/pi/square_clear.py）。
 */
static uint32_t step_cruise_hz = EC_STEP_CRUISE_HZ_DEFAULT;

static ec_input_filter_t input_filter;
static ec_input_snapshot_t input_snapshot;
static uint8_t input_filter_initialized;
/* UART RX single-byte staging buffer. Written by HAL's UART_Receive_IT and
 * read back in ec_board_uart_rx_callback (via HAL_UART_RxCpltCallback), in the
 * UART ISR context. */
static uint8_t uart_main_rx_byte;

/* 2026-09-18 RX-DEAF-FIX: ISR -> 主循环 的接收环形缓冲。
 * 原实现让 USART2 接收中断直接跑完整条协议链（帧解码 + 状态机 + 阻塞发送，
 * 最长 ~20ms），而 HAL_UART_Receive_IT 是那条链的最后一句才重新武装 RX。
 * 那几微秒到几十毫秒里 RXNE 中断是关的，下一个字节必然到达 -> ORE 溢出；
 * HAL 的 UART_EndRxTransfer() 随即把 RxState 置 READY、关掉 RXNE 中断，并调用
 * 本工程从未定义的弱回调 HAL_UART_ErrorCallback（空函数）-> 接收永久死亡。
 * 实测症状即：收到若干次 ITEM_TASK 后完全静默（连 1Hz STATUS 都没了）、
 * 全程看不到任何 ACK/NACK、按板载 RESET 键即恢复。
 * 现在 ISR 只做「存字节 + 立刻重新武装」，全部处理搬到主循环
 * （ec_app_poll() 的排空循环，本来就已经写好、只是被恒 false 架空了）。
 * 满时丢最旧字节：主循环每轮都排空，正常不会满；真落后时保留最新字节，
 * 网关会自己在下一次 0xA5 重新同步。 */
static volatile uint8_t uart_rx_buf[EC_BOARD_RX_CAPACITY];
static volatile uint16_t uart_rx_head;
static volatile uint16_t uart_rx_tail;
/* Shared between the TIM update ISR (ec_step_port_on_timer_period /
 * ec_motion_test_on_counted_done) and the main-loop poll: must be volatile
 * so -O2/-O3 does not cache them in registers and freeze STEP_REMAIN / DONE. */
static volatile ec_axis_t counted_axis;
static volatile uint32_t counted_steps_remaining;
static volatile uint32_t counted_steps_total;
static volatile uint8_t counted_active;
/* Dual-axis (XY) counted move: both axes run on their own timer at their own
 * step rate, so each needs its own countdown. Counted separately from the
 * single-axis state above so the existing single-axis path is untouched. */
static volatile uint8_t counted_xy_active;
static volatile uint32_t counted_x_remaining;
static volatile uint32_t counted_x_total;
static volatile uint32_t counted_y_remaining;
static volatile uint32_t counted_y_total;
/* A zero remaining count is ambiguous: the safety/stop paths also clear it.
 * These latches are written by the timer ISR and consumed once by the main
 * loop, so the executor can distinguish natural completion from an abort. */
static volatile uint8_t counted_completion_pending;
static volatile ec_axis_t counted_completed_axis;
static volatile uint8_t counted_abort_pending;
/* Trapezoidal velocity profile for the current counted move. Planned once at
 * start, then read-only in ISR; no race (ISR only reads step_index, which is
 * volatile above as counted_steps_total - counted_steps_remaining). */
static ec_step_profile_t step_profile;
static ec_step_profile_t step_profile_xy_x;
static ec_step_profile_t step_profile_xy_y;

static uint16_t read_raw_inputs(void)
{
    uint16_t raw = 0U;

#define EC_READ_HIGH(bit, name)                                               \
    do {                                                                      \
        if (HAL_GPIO_ReadPin(name##_GPIO_Port, name##_Pin) == GPIO_PIN_SET) { \
            raw |= (bit);                                                     \
        }                                                                     \
    } while (0)

    /* 2026-09-15 用户裁决：X/Y 不装限位开关，原点 = 上电位置（方案 A）。
     * 下面 6 个限位输入的采样保留（不删引脚宏，避免与 CubeMX 重新生成冲突），
     * 但已无任何代码检查它们 —— 四处安全遮罩已收敛为仅 EC_INPUT_ESTOP_FB。
     * 悬空引脚的电平不再影响任何判据。 */
    EC_READ_HIGH(EC_INPUT_X_HOME, X_HOME);
    EC_READ_HIGH(EC_INPUT_X_END, X_END);
    EC_READ_HIGH(EC_INPUT_Y_HOME, Y_HOME);
    EC_READ_HIGH(EC_INPUT_Y_END, Y_END);
    EC_READ_HIGH(EC_INPUT_Z_UP, Z_UP);
    EC_READ_HIGH(EC_INPUT_Z_DOWN, Z_DOWN);
    EC_READ_HIGH(EC_INPUT_ESTOP_FB, ESTOP_FB);
    EC_READ_HIGH(EC_INPUT_START, START_SIG);
    EC_READ_HIGH(EC_INPUT_MANUAL_RESET, MANUAL_RESET_SIG);

    /* 电源许可：尚未接 GPIO，用 POWER-PERMISSION-GPIO-SETUP.md 记载的临时方案
     * 强制"假定存在"。注意语义：raw 位 = 1 表示线为 HIGH = 有许可；
     * ec_inputs_active_mask() 会取反，因此必须把 raw 置 1 才不会被误判为失电。
     * 接线后改为：EC_READ_HIGH(EC_INPUT_POWER_PERMISSION, POWER_PERMISSION);
     * 并删除本行。 */
    raw |= EC_INPUT_POWER_PERMISSION;

#undef EC_READ_HIGH
    return raw;
}

static TIM_HandleTypeDef *step_timer_for_axis(ec_axis_t axis)
{
    switch (axis) {
    case EC_AXIS_X: return &htim8;
    case EC_AXIS_Y: return &htim4;
    default: return NULL;
    }
}

static void stop_one_step_timer(TIM_HandleTypeDef *timer)
{
    if (timer == NULL) return;
    (void)HAL_TIM_PWM_Stop(timer, TIM_CHANNEL_1);
    __HAL_TIM_DISABLE_IT(timer, TIM_IT_CC1);
    __HAL_TIM_DISABLE_IT(timer, TIM_IT_UPDATE);
}

static void stop_counted_timer(void)
{
    if (counted_active != 0U) {
        stop_one_step_timer(step_timer_for_axis(counted_axis));
        counted_active = 0U;
        counted_steps_remaining = 0U;
        counted_steps_total = 0U;
    }
    if (counted_xy_active != 0U) {
        stop_one_step_timer(step_timer_for_axis(EC_AXIS_X));
        stop_one_step_timer(step_timer_for_axis(EC_AXIS_Y));
        counted_xy_active = 0U;
        counted_x_remaining = 0U;
        counted_x_total = 0U;
        counted_y_remaining = 0U;
        counted_y_total = 0U;
    }
}

static void clear_counted_events(void)
{
    counted_completion_pending = 0U;
    counted_completed_axis = EC_AXIS_NONE;
    counted_abort_pending = 0U;
}

/* Program one step timer for a counted run of `steps`: plan the trapezoidal
 * velocity profile (fall back to a constant `frequency_hz` when the move is too
 * short to plan) and start PWM + the update interrupt. Returns NULL on any
 * failure, in which case nothing is left running for that axis. */
static TIM_HandleTypeDef *start_axis_counted(ec_axis_t axis, uint32_t steps,
                                             uint32_t frequency_hz,
                                             ec_step_profile_t *profile)
{
    TIM_HandleTypeDef *timer = step_timer_for_axis(axis);
    uint32_t period;

    if (timer == NULL) return NULL;

    period = 0U;
    /* 🔴 2026-09-19：巡航频率 2000 → 4000 → **5000 Hz**（方案乙连带，用户裁决）。
     *
     * 原因：方案乙把 HOME 从上电中心挪到负方向最里角（见 ec_motion_plan.h 的
     * EC_MOTION_HOME_X/Y_MM10 注释），程序路径由约 11500 步增加到约 38800 步
     * （落料点用近点 5.0,5.0 时）。各档时长（含 3 次舵机 settle 共 0.6s）：
     *   2000Hz → 约 21.7s   超窗口，必失败
     *   4000Hz → 约 14.7s   余量仅 0.35s，等于没有余量
     *   5000Hz → 约 12.6s   余量约 2.4s  ✅ 取此档
     * 必须压进 ec_app.c:553 的 15000ms 失活窗口 —— 该窗口**会被运动进展续命**
     * （EC_APP_PROGRESS_SOURCE_ENABLED=1，见 ec_app.h:25-26），且在轴 MOVING/GRIPPING
     * 时不判超时（2026-09-22 修复误判）。超时仍会触发 DEADLINE_EXPIRED → FAULT_LOCK，
     * 动作中途中止，主机侧表现就是"从不发 MOTION_DONE"。
     *
     * ⚠️ 仍不够的情形：若落料点改用对角最远点 (+90.0,+92.0)，路径约 59920 步，
     *    5000Hz 下仍要约 17.1s > 15s。届时必须走根治方案 ——
     *    启用进度源让窗口随运动进展重置（ec_app.c:579-583，现为 fail-closed，
     *    需 HIL-PROGRESS-001 先证明观测量），或改用更近的落点。
     *
     * ⚠️ 注意：真正生效的是**本行的 cruise 实参**，不是 EC_AXIS_MOVE_FREQUENCY_HZ
     *    —— 后者只在规划失败时兜底（见下面 period==0 分支）。改那个宏不会提速。
     *
     * ⚠️ 5000Hz（= 62.5mm/s）属提频，**存在丢步风险**。丢步无硬件可发现
     *    （X/Y 不装限位开关），表现为坐标基准永久失准。
     *    已验证方法：`python3 /home/pi/pi_square.py 50` —— 走 50mm 正方形，
     *    四条腿首尾相接，**不闭合即丢步**；再用尺复核四边是否各 50mm。
     *    4000Hz 已用此方法验证通过；改到 5000Hz 后**必须重做同一验证**。
     *    EC_STEP_MAX_HZ 为 10000（ec_step_test.h:8），5000 在合法域内。 */
    if (ec_step_profile_plan(profile, steps, 200U, step_cruise_hz, 200U,
                             10000U, 10000U)) {
        period = ec_step_profile_reload_at(profile, 0U, EC_STEP_TIMER_HZ);
    }
    if (period == 0U) {
        /* Fallback: constant frequency (very short moves / degenerate params).
         * 注意：只有曲线规划失败时才用到 frequency_hz。 */
        period = (EC_STEP_TIMER_HZ / frequency_hz) - 1U;
    }

    __HAL_TIM_SET_AUTORELOAD(timer, period);
    __HAL_TIM_SET_COUNTER(timer, 0U);
    __HAL_TIM_SET_COMPARE(timer, TIM_CHANNEL_1, (period + 1U) / 2U);
    __HAL_TIM_CLEAR_FLAG(timer, TIM_FLAG_UPDATE);

    if (HAL_TIM_PWM_Start(timer, TIM_CHANNEL_1) != HAL_OK) {
        return NULL;
    }
    __HAL_TIM_ENABLE_IT(timer, TIM_IT_UPDATE);
    return timer;
}

void ec_board_enter_safe_state(void)
{
    ec_step_port_stop_all();

    ec_barrier_port_stop();
    ec_servo_port_stop();
    (void)HAL_TIM_PWM_Stop(&htim2, TIM_CHANNEL_4);

    ec_step_port_disable_all();
    /* 2026-10-18：补光灯是 WS2812，单纯拉低引脚不会熄灭（灯珠内部已锁存），
     * 必须发送一帧全 0 的 GRB 数据。代价约 1.1ms（含前后复位低电平）。 */
    ec_ws2812_off();
}

/* 2026-09-18 新增：补光灯直控。低 = 关（与初始化及安全态一致）。
 * 加这个函数的原因：全工程此前只有两处写 LIGHT_EN，且都是 RESET，
 * 也就是说补光灯从来没有被打开过 —— 没有任何代码路径能点亮它。
 *
 * 🔴 2026-10-18 变更（用户确认）：实物补光灯是 **WS2812**（16 颗 × 0.3W，
 *   单总线 800kHz 协议）。单纯把 PC0 拉高**不会点亮**，必须按位发送 GRB 帧。
 *   ⇒ 改为调用 ec_light_ws2812 位模拟驱动；对外语义不变（true=亮 / false=灭）。 */
void ec_board_light_set(bool on)
{
    if (on) {
        ec_ws2812_white_on();
    } else {
        ec_ws2812_off();
    }
}

/* 2026-09-18 L4 批准：总线舵机（自适应夹爪）发送。
 * 走 USART3，波特率 115200（main.c 已配），TX 已迁至 PB10。
 * 只发不收 —— 半双工单总线，不回读时无需方向控制脚。
 * 10 字节 @115200 ≈ 0.9ms，20ms 超时足够。 */
extern UART_HandleTypeDef huart3;

/* 2026-09-18：PB10 复用功能运行时切换。
 * 夹爪舵机既可能是「总线舵机」（USART3_TX，AF7），也可能是普通
 * 「PWM 舵机」（TIM2_CH3，AF1）—— 两者都是三线，光看线区分不出来。
 * 两种驱动共用同一物理引脚，故做运行时切换，避免每试一种就重烧一次固件。
 * 切换前先停掉另一侧的输出，避免切换瞬间发出畸形波形。 */
static void grip_pin_select(uint8_t alternate)
{
    GPIO_InitTypeDef g = {0};

    if (alternate == GPIO_AF7_USART3) {
        (void)HAL_TIM_PWM_Stop(&htim2, TIM_CHANNEL_3);   /* 离开 PWM 模式 */
    }
    __HAL_RCC_GPIOB_CLK_ENABLE();
    g.Pin = GPIO_PIN_10;
    g.Mode = GPIO_MODE_AF_PP;
    g.Pull = GPIO_NOPULL;
    g.Speed = (alternate == GPIO_AF7_USART3) ? GPIO_SPEED_FREQ_VERY_HIGH
                                             : GPIO_SPEED_FREQ_LOW;
    g.Alternate = alternate;
    HAL_GPIO_Init(GPIOB, &g);
}

bool ec_grip_port_move(uint16_t position, uint16_t time_ms)
{
    uint8_t frame[EC_BUS_SERVO_MOVE_FRAME_LEN];
    size_t built;

    grip_pin_select(GPIO_AF7_USART3);      /* 本条命令走总线协议 */
    built = ec_bus_servo_build_move(frame, sizeof(frame),
                                    EC_BUS_SERVO_ID_DEFAULT,
                                    position, time_ms);
    if (built == 0U) {
        return false;
    }
    return HAL_UART_Transmit(&huart3, frame, (uint16_t)built, 20U) == HAL_OK;
}

void ec_board_poll_inputs(uint32_t now_ms)
{
    uint16_t raw = read_raw_inputs();
    if (input_filter_initialized == 0U) {
        ec_inputs_init(&input_filter, raw, now_ms);
        input_filter_initialized = 1U;
    } else {
        ec_inputs_update(&input_filter, raw, now_ms);
    }

    input_snapshot.raw_mask = raw;
    input_snapshot.stable_mask = ec_inputs_stable_mask(&input_filter);
    input_snapshot.active_mask = ec_inputs_active_mask(&input_filter);
}

ec_input_snapshot_t ec_board_read_inputs(void)
{
    return input_snapshot;
}

bool ec_step_port_start(ec_axis_t axis, uint32_t frequency_hz)
{
    TIM_HandleTypeDef *timer;
    uint32_t period;

    if ((frequency_hz != UINT32_C(10)) &&
        (frequency_hz != UINT32_C(100))) return false;
    timer = step_timer_for_axis(axis);
    if (timer == NULL) return false;

    /* TIM4/TIM8/TIM9 use a 100 kHz timer clock (PSC=159). */
    period = (EC_STEP_TIMER_HZ / frequency_hz) - 1U;
    __HAL_TIM_SET_AUTORELOAD(timer, period);
    __HAL_TIM_SET_COUNTER(timer, 0U);
    __HAL_TIM_SET_COMPARE(timer, TIM_CHANNEL_1, (period + 1U) / 2U);
    return HAL_TIM_PWM_Start(timer, TIM_CHANNEL_1) == HAL_OK;
}

bool ec_step_port_start_counted(ec_axis_t axis, uint32_t frequency_hz,
                                uint32_t steps)
{
    /* Re-entry guard: refuse to arm a counted run while one is already
     * active, so a stray second start can't overwrite the shared
     * counted_axis/counted_steps_* state (P2-5). */
    if ((counted_active != 0U) || (counted_xy_active != 0U)) return false;
    if ((axis != EC_AXIS_X) && (axis != EC_AXIS_Y)) {
        return false;
    }
    if (steps == 0U) return false;
    if ((frequency_hz < EC_STEP_MIN_HZ) ||
        (frequency_hz > EC_STEP_MAX_HZ)) {
        return false;
    }

    clear_counted_events();
    counted_axis = axis;
    counted_steps_remaining = steps;
    counted_steps_total = steps;
    counted_active = 1U;

    /* Plan trapezoidal velocity profile: start 200 Hz -> cruise 2000 Hz -> end
     * 200 Hz, accel/decel 5000 Hz/s. Conservative values; tune on-site for
     * faster throughput. Falls back to constant frequency_hz when planning
     * fails (moves too short for accel/decel). */
    if (start_axis_counted(axis, steps, frequency_hz, &step_profile) == NULL) {
        counted_active = 0U;
        counted_steps_remaining = 0U;
        counted_steps_total = 0U;
        ec_step_port_stop_all();
        return false;
    }
    return true;
}

bool ec_step_port_enable_xy(void)
{
    ec_step_port_disable_all();
    /* PD42S1 EN极性：高有效（2026-10-11手册确认） */
    HAL_GPIO_WritePin(ENABLE_X_GPIO_Port, ENABLE_X_Pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(ENABLE_Y_GPIO_Port, ENABLE_Y_Pin, GPIO_PIN_SET);
    return true;
}

bool ec_step_port_start_counted_xy(uint32_t x_steps, uint32_t x_frequency_hz,
                                   uint32_t y_steps, uint32_t y_frequency_hz)
{
    if ((counted_active != 0U) || (counted_xy_active != 0U)) return false;
    if ((x_steps > EC_STEP_MAX_STEPS) || (y_steps > EC_STEP_MAX_STEPS)) {
        return false;
    }
    /* Either leg may be zero (an axis-aligned MOVE_XY), but not both. The rate
     * of a zero-step leg is irrelevant, so it is not range-checked. */
    if ((x_steps == 0U) && (y_steps == 0U)) return false;
    if ((x_steps != 0U) &&
        ((x_frequency_hz < EC_STEP_MIN_HZ) ||
         (x_frequency_hz > EC_STEP_MAX_HZ))) {
        return false;
    }
    if ((y_steps != 0U) &&
        ((y_frequency_hz < EC_STEP_MIN_HZ) ||
         (y_frequency_hz > EC_STEP_MAX_HZ))) {
        return false;
    }

    clear_counted_events();
    counted_x_remaining = x_steps;
    counted_x_total = x_steps;
    counted_y_remaining = y_steps;
    counted_y_total = y_steps;
    counted_xy_active = 1U;

    if ((x_steps != 0U) &&
        (start_axis_counted(EC_AXIS_X, x_steps, x_frequency_hz,
                            &step_profile_xy_x) == NULL)) {
        stop_counted_timer();
        ec_step_port_disable_all();
        return false;
    }
    if ((y_steps != 0U) &&
        (start_axis_counted(EC_AXIS_Y, y_steps, y_frequency_hz,
                            &step_profile_xy_y) == NULL)) {
        stop_counted_timer();
        ec_step_port_disable_all();
        return false;
    }
    return true;
}

/* One update-tick of the dual-axis counted move, from whichever of the two step
 * timers fired. Each axis counts down independently and stops its own PWM when
 * its own count reaches zero, so a short leg never cuts the long one short. */
static void counted_xy_tick(TIM_HandleTypeDef *htim)
{
    volatile uint32_t *remaining;
    volatile uint32_t *total;
    ec_step_profile_t *profile;
    TIM_HandleTypeDef *timer;
    uint32_t step_index;
    uint32_t next_reload;

    if (htim->Instance == htim8.Instance) {
        timer = &htim8;
        remaining = &counted_x_remaining;
        total = &counted_x_total;
        profile = &step_profile_xy_x;
    } else if (htim->Instance == htim4.Instance) {
        timer = &htim4;
        remaining = &counted_y_remaining;
        total = &counted_y_total;
        profile = &step_profile_xy_y;
    } else {
        return;
    }

    /* Fast-path safety inhibit (P2-3), same as the single-axis path. */
    if (ec_motion_inhibit_from_raw(read_raw_inputs())) {
        stop_counted_timer();
        counted_completion_pending = 0U;
        counted_abort_pending = 1U;
        ec_step_port_disable_all();
        ec_motion_test_on_aborted();
        return;
    }

    if (*remaining > 0U) {
        (*remaining)--;
        step_index = *total - *remaining;
        next_reload = ec_step_profile_reload_at(profile, step_index,
                                                EC_STEP_TIMER_HZ);
        if (next_reload != 0U) {
            __HAL_TIM_SET_AUTORELOAD(timer, next_reload);
            __HAL_TIM_SET_COMPARE(timer, TIM_CHANNEL_1, (next_reload + 1U) / 2U);
        }
        if (*remaining == 0U) {
            stop_one_step_timer(timer);
        }
    }

    if (ec_step_port_counted_all_done()) {
        counted_completed_axis = EC_AXIS_NONE;
        counted_completion_pending = 1U;
        stop_counted_timer();
        ec_step_port_disable_all();
        ec_motion_test_on_counted_done();
    }
}

void ec_step_port_on_timer_period(TIM_HandleTypeDef *htim)
{
    TIM_HandleTypeDef *timer;
    /* 🔴 2026-09-18 已删除「TIM 中断内 NVIC_SystemReset」整块（原 :432-454）。
     * 删除理由（不是风格问题，是它本身是错的 + 危险）：
     *   · 逻辑错误：last_main_loop_tick 初值 0 且只在 ISR 内更新，所以
     *     `(now_tick - last_main_loop_tick) > 1000` 测的是【两次中断的间隔】，
     *     根本不是"主循环是否活着"。上电满 1 秒后第一个定时器中断进来，
     *     now_tick - 0 > 1000 即成立 → 上电约 1 秒就复位一次，
     *     复位后又从 0 开始 → 约 1Hz 的复位死循环。
     *   · 极度危险：在最高频、最高优先级的中断里复位整个 MCU，
     *     若在运动途中触发 → 带电掉料、机械撞击、坐标基准丢失。
     *   · 冗余：主循环每轮都有 HAL_IWDG_Refresh()，主循环真被饿死时
     *     看门狗本就负责复位。这里再叠一层是重复且有害的。
     * 若日后确需"主循环活性检测"，正确做法是主循环置标志、ISR 只读标志，
     * 且只停运动、不复位整个 MCU。 */

    if (counted_xy_active != 0U) {
        counted_xy_tick(htim);
        return;
    }
    if (counted_active == 0U) return;
    timer = step_timer_for_axis(counted_axis);
    if ((timer == NULL) || (htim->Instance != timer->Instance)) {
        return;
    }

    /* Fast-path safety inhibit (P2-3): read the raw limit/ESTOP GPIO pins
     * directly (no debounce) so a triggered limit/ESTOP halts within one
     * step tick instead of waiting for the main-loop poll (~50ms worst).
     * Same active-low polarity as ec_inputs_active_mask. */
    if (ec_motion_inhibit_from_raw(read_raw_inputs())) {
        stop_counted_timer();
        counted_completion_pending = 0U;
        counted_abort_pending = 1U;
        ec_step_port_disable_all();
        ec_motion_test_on_aborted();
        return;
    }

    if (counted_steps_remaining > 0U) {
        counted_steps_remaining--;
        /* Update ARR for the next step (step_index = total - remaining).
         * If profile returns 0 (out of range or invalid), keep current ARR. */
        uint32_t step_index = counted_steps_total - counted_steps_remaining;
        uint32_t next_reload = ec_step_profile_reload_at(&step_profile, step_index,
                                                          EC_STEP_TIMER_HZ);
        if (next_reload != 0U) {
            __HAL_TIM_SET_AUTORELOAD(timer, next_reload);
            /* Update compare to maintain 50% duty cycle (pulse width = period/2). */
            __HAL_TIM_SET_COMPARE(timer, TIM_CHANNEL_1, (next_reload + 1U) / 2U);
        }
    }
    if (counted_steps_remaining == 0U) {
        /* Runs in the TIM update ISR. HAL_TIM_PWM_Stop inside
         * stop_counted_timer may return HAL_BUSY if the main loop holds the
         * lock, but the safety fallback is ec_step_port_disable_all (direct
         * GPIO write) right after, which does not depend on the HAL lock. */
        counted_completed_axis = counted_axis;
        counted_completion_pending = 1U;
        stop_counted_timer();
        ec_step_port_disable_all();
        ec_motion_test_on_counted_done();
    }
}

/* PB10 = TIM2_CH3 舵机通道是否正在输出。只有 ec_servo_port_start() /
 * ec_servo_port_stop() / ec_servo_port_stop_z() 三个函数能改它。
 * 为什么不用 HAL 的 TIM_CHANNEL_STATE_GET 判断 —— 见
 * ec_servo_port_start() 下方 2026-09-19 那段加固说明。 */
static bool servo_ch3_started = false;
static bool drop_servo_started = false;

bool ec_servo_port_start(uint16_t pulse_us)
{
    if ((pulse_us == 0U) || (pulse_us > htim2.Init.Period)) return false;

    /* 2026-09-18：本条命令走 PWM，先把 PB10 切回 TIM2_CH3(AF1)。 */
    grip_pin_select(GPIO_AF1_TIM2);
    __HAL_TIM_SET_COUNTER(&htim2, 0U);
    __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_3, pulse_us);

    /* 🔴 2026-09-18 修复「Z 程序第二个舵机步必死 → PORT_FAIL → 从不发 MOTION_DONE」。
     * 机理三段都是既成事实，改前务必看完：
     *   1) HAL_TIM_PWM_Start 进门第一句就查通道状态
     *      （Drivers/.../stm32f4xx_hal_tim.c:1462）：不是 READY 直接 return HAL_ERROR；
     *   2) Z 轴程序里有【两个】舵机步 —— 取料点闭合 EC_AXIS_Z_DOWN_US、
     *      落料点张开 EC_AXIS_Z_UP_US（ec_motion_plan.c:154,162），中间只夹 XY 移动；
     *   3) ec_axis_driver.c:389-400 在 GRIPPING→下一步时【故意不释放】本通道：
     *      夹爪闭合后必须持续输出脉宽才能夹住物体，中途停脉宽会当场掉件。
     * 于是第二个舵机步必然撞上状态门 → fault(EC_AXIS_RESULT_PORT_FAIL)
     * → 板子进 FAULT_LOCK → 永远不发 MOTION_DONE；主机侧表现为
     * 「ITEM_TASK 已 ACK，但动作永远不完成，每 ~10.7s 重跑一次启动序列」。
     * 实机证据（AXIS 命令）：LAST_KIND=2(Z_SERVO) LAST_STEP=5 LAST_LEN=8
     * LAST_RESULT=6(PORT_FAIL)，与上面的步序逐项吻合（5 = 第二个舵机步）。
     * 修法：通道已在输出时【只更新 CCR】（上面那句已做），不再重启通道 ——
     * 既不丢保持力矩（没有停-启空档），也不产生 HAL_ERROR。
     *
     * 🔴 2026-09-19 加固（来源：Claude 对抗性审查 #1，DSH 回源码复核后落地）：
     * 上面那句「已在输出」原先是用 HAL 的通道状态字判断的：
     *     if (TIM_CHANNEL_STATE_GET(&htim2, TIM_CHANNEL_3) != READY) return true;
     * 这个判断【不可靠】，因为 HAL_TIM_PWM_Stop() 内部是
     *     __HAL_TIM_DISABLE(htim);                      // 关的是整个 TIM2 计数器
     *     TIM_CHANNEL_STATE_SET(htim, Channel, READY);  // 只恢复【传入的那一个】通道
     * （stm32f4xx_hal_tim.c:1523 与 :1526，两条都是 HAL 原文）。
     * 而 PB11 = TIM2_CH4 与 PB10 = TIM2_CH3 共用同一个计数器：ec_servo_port_stop_z()
     * 停 CH4 时会把 CH3 的输出一起掐断，却把 CH3 的状态字【留在 BUSY】。
     * 那种情况下旧判断会误以为「还在输出」而直接 return true →
     * 【一个脉冲都不发，且不报任何故障】→ 夹爪静默失能，表现像机械故障，极难查。
     * 现状之所以没炸，只靠 ec_axis_driver.c:139-140 那两行的先后顺序挡着
     * （先 ec_servo_port_stop() 把 CH3 置回 READY，再 ec_servo_port_stop_z() 关计数器），
     * 属于隐式依赖 —— 任何人重排这两行就会破。
     * 加固办法：不再问 HAL，改用本文件自持的标志位 servo_ch3_started 表达同一语义；
     * 并在 ec_servo_port_stop_z() 里把被它连带关掉的计数器救回来。 */
    if (!servo_ch3_started) {
        if (HAL_TIM_PWM_Start(&htim2, TIM_CHANNEL_3) != HAL_OK) {
            return false;
        }
        servo_ch3_started = true;
    }
    return true;
}

static bool barrier_start_channel(TIM_HandleTypeDef *timer,
                                  uint32_t channel, uint16_t pulse_us)
{
    if ((pulse_us == 0U) || (pulse_us > htim3.Init.Period)) return false;

    __HAL_TIM_SET_COUNTER(timer, 0U);
    __HAL_TIM_SET_COMPARE(timer, channel, pulse_us);
    return HAL_TIM_PWM_Start(timer, channel) == HAL_OK;
}

bool ec_barrier_port_start_mask(uint8_t channel_mask, uint16_t pulse_us)
{
    bool ok = true;

    if ((channel_mask == 0U) || (pulse_us == 0U) ||
        (pulse_us > htim3.Init.Period)) {
        return false;
    }

    ec_barrier_port_stop();
    if (((channel_mask & UINT8_C(0x01)) != 0U) &&
        !barrier_start_channel(&htim3, TIM_CHANNEL_3, pulse_us)) {
        ok = false;
    }
    if (((channel_mask & UINT8_C(0x02)) != 0U) &&
        !barrier_start_channel(&htim3, TIM_CHANNEL_4, pulse_us)) {
        ok = false;
    }
    if (((channel_mask & UINT8_C(0x04)) != 0U) &&
        !barrier_start_channel(&htim10, TIM_CHANNEL_1, pulse_us)) {
        ok = false;
    }
    if (((channel_mask & UINT8_C(0x08)) != 0U) &&
        !barrier_start_channel(&htim11, TIM_CHANNEL_1, pulse_us)) {
        ok = false;
    }

    if (!ok) {
        ec_barrier_port_stop();
        return false;
    }
    return true;
}

void ec_barrier_port_stop(void)
{
    (void)HAL_TIM_PWM_Stop(&htim3, TIM_CHANNEL_3);
    (void)HAL_TIM_PWM_Stop(&htim3, TIM_CHANNEL_4);
    (void)HAL_TIM_PWM_Stop(&htim10, TIM_CHANNEL_1);
    (void)HAL_TIM_PWM_Stop(&htim11, TIM_CHANNEL_1);
    __HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_3, 0U);
    __HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_4, 0U);
    __HAL_TIM_SET_COMPARE(&htim10, TIM_CHANNEL_1, 0U);
    __HAL_TIM_SET_COMPARE(&htim11, TIM_CHANNEL_1, 0U);
}

uint32_t ec_barrier_port_now_ms(void)
{
    return HAL_GetTick();
}

void ec_servo_port_stop(void)
{
    (void)HAL_TIM_PWM_Stop(&htim2, TIM_CHANNEL_3);
    __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_3, 0U);
    /* 本函数把通道停掉了，标志位必须同步清掉，否则下次 start 会以为还在输出。 */
    servo_ch3_started = false;
}

/* Legacy channel: TIM2_CH4 = PB11 (old WRIST/"Z" naming -- that name is VOID).
 * It does NOT drive the Z axis. Z axis + gripper = ONE LDX-335MG digital servo
 * on PB10 = TIM2_CH3 (ec_servo_port_start); lift and jaw are linked, i.e. one
 * single degree of freedom. The old DS3120MG model and the old 1100/1900 us
 * pulse widths are VOID and must be re-measured
 * (docs/测量表-②Z轴行程-2026-09-17.md:19).
 *
 * ec_axis_driver.c stopped starting this channel on 2026-09-16 (only ec_demo.c
 * still calls ec_servo_port_start_z), but its stop_all() still calls
 * ec_servo_port_stop_z(); ec_safety_port_stop_all() does NOT stop this
 * channel. Shares TIM2's 50 Hz servo period with PB10. */
bool ec_servo_port_start_z(uint16_t pulse_us)
{
    if ((pulse_us == 0U) || (pulse_us > htim2.Init.Period)) return false;

    __HAL_TIM_SET_COUNTER(&htim2, 0U);
    __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_4, pulse_us);
    return HAL_TIM_PWM_Start(&htim2, TIM_CHANNEL_4) == HAL_OK;
}

void ec_servo_port_stop_z(void)
{
    (void)HAL_TIM_PWM_Stop(&htim2, TIM_CHANNEL_4);
    __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_4, 0U);
    /* 🔴 2026-09-19：HAL_TIM_PWM_Stop 内部 __HAL_TIM_DISABLE 关的是【整个 TIM2 计数器】
     * （stm32f4xx_hal_tim.c:1523），而 CH3(PB10 舵机) 与 CH4(PB11) 共用这一个计数器。
     * 也就是说：本函数会把正在输出的 PB10 舵机【一起掐断】。
     * 若此刻 CH3 本应在输出，必须把计数器救回来，否则夹爪静默失能 ——
     * 完整机理见 ec_servo_port_start() 里的 2026-09-19 加固说明。
     * CH3 的 CCx 使能位 HAL 没动过，所以只要计数器重新跑起来，脉宽就继续输出。 */
    if (servo_ch3_started) {
        __HAL_TIM_ENABLE(&htim2);
    }
}

bool ec_board_drop_servo_set_us(uint16_t pulse_us)
{
    if (pulse_us == 0U || pulse_us > htim9.Init.Period) return false;

    __HAL_TIM_SET_COUNTER(&htim9, 0U);
    __HAL_TIM_SET_COMPARE(&htim9, TIM_CHANNEL_1, pulse_us);
    if (drop_servo_started) return true;

    if (HAL_TIM_PWM_Start(&htim9, TIM_CHANNEL_1) != HAL_OK) return false;
    drop_servo_started = true;
    return true;
}

void ec_board_drop_servo_stop(void)
{
    if (drop_servo_started) {
        (void)HAL_TIM_PWM_Stop(&htim9, TIM_CHANNEL_1);
        drop_servo_started = false;
    }
    __HAL_TIM_SET_COMPARE(&htim9, TIM_CHANNEL_1, 0U);
}

uint32_t ec_servo_port_now_ms(void)
{
    return HAL_GetTick();
}

bool ec_step_port_set_direction(ec_axis_t axis, ec_direction_t direction)
{
    GPIO_PinState state = (direction == EC_DIRECTION_1) ?
                          GPIO_PIN_SET : GPIO_PIN_RESET;

    switch (axis) {
    case EC_AXIS_X:
        HAL_GPIO_WritePin(DIR_X_GPIO_Port, DIR_X_Pin, state);
        return true;
    case EC_AXIS_Y:
        HAL_GPIO_WritePin(DIR_Y_GPIO_Port, DIR_Y_Pin, state);
        return true;
    default:
        return false;
    }
}

bool ec_step_port_enable_axis(ec_axis_t axis)
{
    ec_step_port_disable_all();
    switch (axis) {
    case EC_AXIS_X:
        /* PD42S1 EN极性：高有效 */
        HAL_GPIO_WritePin(ENABLE_X_GPIO_Port, ENABLE_X_Pin, GPIO_PIN_SET);
        return true;
    case EC_AXIS_Y:
        HAL_GPIO_WritePin(ENABLE_Y_GPIO_Port, ENABLE_Y_Pin, GPIO_PIN_SET);
        return true;
    default:
        return false;
    }
}

void ec_step_port_stop_all(void)
{
    stop_counted_timer();
    (void)HAL_TIM_PWM_Stop(&htim8, TIM_CHANNEL_1);
    (void)HAL_TIM_PWM_Stop(&htim4, TIM_CHANNEL_1);
}

void ec_step_port_disable_all(void)
{
    /* PD42S1 EN极性：高有效，失能时输出低电平 */
    HAL_GPIO_WritePin(ENABLE_X_GPIO_Port, ENABLE_X_Pin, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(ENABLE_Y_GPIO_Port, ENABLE_Y_Pin, GPIO_PIN_RESET);
}

uint32_t ec_step_port_now_ms(void)
{
    return HAL_GetTick();
}

/* 2026-10-23：巡航频率运行时可设（T8 安全速度实测）。
 *
 * 校验：
 *   1) [EC_STEP_MIN_HZ, EC_STEP_MAX_HZ]     —— 与 MOVE 的 HZ 同域
 *   2) > 曲线起止频率 200Hz                 —— 否则 ec_step_profile_plan 直接拒绝
 *      （它要求 cruise_hz >= start_hz 且 cruise_hz >= end_hz）
 *   3) 采样周期必须 >= 2（AUTORELOAD = 100000/hz - 1，若 hz > 50000 会算出 1 或 0，
 *      虽然被 EC_STEP_MAX_HZ=10000 挡住，这里再显式挡一次防以后放宽上限）
 *
 * 只在【下一条运动开始规划时】生效；正在进行的运动不受影响。
 * 失败时不改动原值（fail-closed）。
 */
bool ec_step_port_set_cruise_hz(uint32_t cruise_hz)
{
    uint32_t reload;

    if ((cruise_hz < EC_STEP_MIN_HZ) || (cruise_hz > EC_STEP_MAX_HZ)) {
        return false;
    }
    /* 曲线起止频率固定 200Hz（见 start_axis_counted 的 plan 调用）*/
    if (cruise_hz <= 200U) {
        return false;
    }
    reload = (EC_STEP_TIMER_HZ / cruise_hz);
    if (reload < 2U) {
        return false;
    }

    step_cruise_hz = cruise_hz;
    return true;
}

uint32_t ec_step_port_get_cruise_hz(void)
{
    return step_cruise_hz;
}

uint32_t ec_step_port_counted_remaining(void)
{
    if (counted_xy_active != 0U) {
        return counted_x_remaining + counted_y_remaining;
    }
    return (counted_active != 0U) ? counted_steps_remaining : 0U;
}

uint32_t ec_step_port_counted_target(void)
{
    if (counted_xy_active != 0U) {
        return counted_x_total + counted_y_total;
    }
    return (counted_active != 0U) ? counted_steps_total : 0U;
}

uint32_t ec_step_port_counted_remaining_for(ec_axis_t axis)
{
    if (counted_xy_active != 0U) {
        if (axis == EC_AXIS_X) return counted_x_remaining;
        if (axis == EC_AXIS_Y) return counted_y_remaining;
        return 0U;
    }
    return ((counted_active != 0U) && (axis == counted_axis)) ?
           counted_steps_remaining : 0U;
}

uint32_t ec_step_port_counted_target_for(ec_axis_t axis)
{
    if (counted_xy_active != 0U) {
        if (axis == EC_AXIS_X) return counted_x_total;
        if (axis == EC_AXIS_Y) return counted_y_total;
        return 0U;
    }
    return ((counted_active != 0U) && (axis == counted_axis)) ?
           counted_steps_total : 0U;
}

bool ec_step_port_counted_all_done(void)
{
    if (counted_xy_active != 0U) {
        return (counted_x_remaining == 0U) && (counted_y_remaining == 0U);
    }
    return (counted_active != 0U) && (counted_steps_remaining == 0U);
}

bool ec_step_port_take_counted_completion(ec_axis_t *completed_axis)
{
    uint8_t pending;

    if (completed_axis == NULL) return false;

    /* The ISR may publish a completion between the load and clear. Keep the
     * hand-off atomic so a real completion is never lost at the poll boundary. */
    {
        uint32_t primask = __get_PRIMASK();
        __disable_irq();
        pending = counted_completion_pending;
        if (pending != 0U) {
            *completed_axis = counted_completed_axis;
            counted_completion_pending = 0U;
            counted_completed_axis = EC_AXIS_NONE;
        }
        if (primask == 0U) __enable_irq();
    }
    return pending != 0U;
}

bool ec_step_port_take_counted_abort(void)
{
    uint8_t pending;

    {
        uint32_t primask = __get_PRIMASK();
        __disable_irq();
        pending = counted_abort_pending;
        counted_abort_pending = 0U;
        if (primask == 0U) __enable_irq();
    }
    return pending != 0U;
}

bool ec_group_port_set_direction(ec_axis_t axis, ec_direction_t direction)
{
    return ec_step_port_set_direction(axis, direction);
}

bool ec_group_port_enable_xy(void)
{
    ec_step_port_disable_all();
    /* PD42S1 EN极性：高有效 */
    HAL_GPIO_WritePin(ENABLE_X_GPIO_Port, ENABLE_X_Pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(ENABLE_Y_GPIO_Port, ENABLE_Y_Pin, GPIO_PIN_SET);
    return true;
}

bool ec_group_port_start_step(ec_axis_t axis, uint32_t frequency_hz)
{
    return ec_step_port_start(axis, frequency_hz);
}

bool ec_group_port_start_servo(uint16_t pulse_us)
{
    return ec_servo_port_start(pulse_us);
}

void ec_group_port_stop_all(void)
{
    ec_step_port_stop_all();
    ec_servo_port_stop();
    ec_step_port_disable_all();
}

uint32_t ec_group_port_now_ms(void)
{
    return HAL_GetTick();
}

void ec_safety_port_stop_all(void)
{
    ec_step_port_stop_all();
    ec_servo_port_stop();
    ec_barrier_port_stop();
}

void ec_safety_port_disable_drivers(void)
{
    ec_step_port_disable_all();
}

void ec_safety_port_inhibit_power(void)
{
    /* ESTOP_FB is feedback only; dangerous power is cut by external hardware. */
    ec_servo_port_stop();
    ec_barrier_port_stop();
    ec_step_port_disable_all();
}

void ec_diag_port_write(const char *text)
{
    size_t length = strlen(text);
    uint32_t timeout_ms;

    if (length > UINT16_MAX) return;
    /* 115200 8N1 -> 11520 bytes/s. Allow 2x the send time + 10 ms floor so
     * STATUS/HELP (~350 B) are not truncated by a fixed 20 ms timeout. */
    timeout_ms = (uint32_t)((length * 2000UL) / 11520UL) + 10UL;
    (void)HAL_UART_Transmit(&huart2, (uint8_t *)text, (uint16_t)length,
                            timeout_ms);
}

void ec_board_uart_start_rx(void)
{
    uart_rx_head = 0U;
    uart_rx_tail = 0U;
    (void)HAL_UART_Receive_IT(&huart2, &uart_main_rx_byte, 1U);
}

void ec_board_uart_rx_callback(UART_HandleTypeDef *huart)
{
    uint16_t next;

    if ((huart == NULL) || (huart->Instance != USART2)) return;

    next = (uint16_t)(uart_rx_head + 1U);
    if (next >= EC_BOARD_RX_CAPACITY) next = 0U;

    if (next == uart_rx_tail) {
        /* Full: drop the OLDEST byte so the newest - where the parser is -
         * stays contiguous. The gateway resyncs on the next 0xA5. */
        uint16_t tail = (uint16_t)(uart_rx_tail + 1U);

        if (tail >= EC_BOARD_RX_CAPACITY) tail = 0U;
        uart_rx_tail = tail;
    }

    uart_rx_buf[uart_rx_head] = uart_main_rx_byte;
    uart_rx_head = next;

    /* Re-arming is now the ONLY other thing this ISR does, so the window with
     * RXNE disabled is microseconds instead of the milliseconds a blocking
     * response transmit costs. That window is what caused the guaranteed ORE. */
    (void)HAL_UART_Receive_IT(&huart2, &uart_main_rx_byte, 1U);
}

void ec_board_uart_transmit(const uint8_t *data, size_t length)
{
    uint32_t timeout_ms;

    if (data == NULL || length == 0U || length > UINT16_MAX) return;

    /* 115200 8N1 -> 11520 bytes/s. Allow 2x the send time + 10 ms floor.
     * Use shorter timeout than HAL_MAX_DELAY to avoid blocking ISR too long. */
    timeout_ms = (uint32_t)((length * 2000UL) / 11520UL) + 10UL;
    (void)HAL_UART_Transmit(&huart2, (uint8_t *)data, (uint16_t)length, timeout_ms);
}

/* 2026-09-18 RX-DEAF-FIX: the ISR now only stages bytes; all protocol
 * processing runs in ec_app_poll()'s drain loop, in main-loop context, so a
 * blocking response transmit can no longer overlap a byte arrival while RX is
 * disarmed. This is the "deferred parsing" the old ponytail note anticipated. */
bool ec_board_uart_rx_available(void)
{
    return uart_rx_head != uart_rx_tail;
}

uint8_t ec_board_uart_rx_read(void)
{
    uint8_t byte;
    uint16_t next;

    if (uart_rx_head == uart_rx_tail) return 0U;

    byte = uart_rx_buf[uart_rx_tail];
    next = (uint16_t)(uart_rx_tail + 1U);
    if (next >= EC_BOARD_RX_CAPACITY) next = 0U;
    uart_rx_tail = next;
    return byte;
}

/* 2026-09-18 RX-DEAF-FIX: HAL calls this (via main.c's HAL_UART_ErrorCallback)
 * after UART_EndRxTransfer() has already set RxState READY and disabled the
 * RXNE interrupt on any ORE/FE/NE/PE. Without re-arming here, ONE overrun kills
 * USART2 reception for the rest of the power cycle. The overrun flag is cleared
 * first: re-arming while ORE is still latched re-enters the error path. */
void ec_board_uart_error_callback(UART_HandleTypeDef *huart)
{
    if ((huart == NULL) || (huart->Instance != USART2)) return;

    __HAL_UART_CLEAR_OREFLAG(huart);
    (void)HAL_UART_Receive_IT(&huart2, &uart_main_rx_byte, 1U);
}
