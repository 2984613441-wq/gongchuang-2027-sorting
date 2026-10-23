#include "ec_step_test.h"

#include "ec_inputs.h"

#define EC_STEP_TEST_FREQUENCY_HZ UINT32_C(10)
#define EC_STEP_TEST_DURATION_MS  UINT32_C(5000)
#define EC_TRACK_TEST_FREQUENCY_HZ UINT32_C(100)
#define EC_MOTION_ARM_WINDOW_MS   UINT32_C(10000)
#define EC_MOTION_SETTLE_MS       UINT32_C(20)
#define EC_MOTION_DURATION_MS     UINT32_C(10000)
#define EC_MOTION_COUNTED_TIMEOUT_MARGIN_MS UINT32_C(1000)
/* 2026-09-15 用户裁决：X/Y 不装限位开关 → 遮罩收敛为仅 ESTOP。
 * 与 ec_axis_driver.c / ec_demo.c / ec_servo_test.c 的三处遮罩保持一致。 */
#define EC_MOTION_SAFETY_MASK  (EC_INPUT_ESTOP_FB)

/* active_axis/started_at_ms/counted_steps/mode/counted_result are shared between
 * the ISR (ec_motion_test_on_counted_done / stop_active_test) and the main-loop
 * poll: must be volatile. armed_at_ms/motion_armed/counted_timeout_ms are only
 * touched by the main loop, so they stay non-volatile. */
static volatile ec_axis_t active_axis;
static volatile uint32_t started_at_ms;
static uint32_t armed_at_ms;
static volatile uint32_t counted_steps;
static volatile uint32_t counted_x_steps;   /* COUNTED_XY: X leg target */
static volatile uint32_t counted_y_steps;   /* COUNTED_XY: Y leg target */
static volatile ec_step_test_mode_t mode;
static uint8_t motion_armed;
static volatile ec_step_result_t counted_result;
static uint32_t counted_timeout_ms;

static bool is_valid_axis(ec_axis_t axis)
{
    /* Z is a servo (not a stepper): only X/Y are stepper axes. */
    return (axis == EC_AXIS_X) || (axis == EC_AXIS_Y);
}

static bool has_motion_inhibit(uint16_t active_inputs)
{
    return (active_inputs & EC_MOTION_SAFETY_MASK) != 0U;
}

static void stop_active_test(void)
{
    ec_step_port_stop_all();
    ec_step_port_disable_all();
    active_axis = EC_AXIS_NONE;
    mode = EC_STEP_TEST_IDLE;
    started_at_ms = 0U;
    counted_steps = 0U;
    counted_x_steps = 0U;
    counted_y_steps = 0U;
}

void ec_step_test_init(void)
{
    active_axis = EC_AXIS_NONE;
    started_at_ms = 0U;
    counted_steps = 0U;
    counted_x_steps = 0U;
    counted_y_steps = 0U;
    armed_at_ms = 0U;
    mode = EC_STEP_TEST_IDLE;
    motion_armed = 0U;
    counted_result = EC_STEP_RESULT_NONE;
    counted_timeout_ms = 0U;
}

bool ec_step_test_start(ec_axis_t axis)
{
    if (!is_valid_axis(axis)) return false;

    ec_step_test_stop();
    ec_step_port_disable_all();
    if (!ec_step_port_start(axis, EC_STEP_TEST_FREQUENCY_HZ)) {
        return false;
    }

    active_axis = axis;
    started_at_ms = ec_step_port_now_ms();
    mode = EC_STEP_TEST_SIGNAL_ONLY;
    return true;
}

bool ec_motion_test_arm(uint16_t active_inputs)
{
    ec_step_test_stop();
    if (has_motion_inhibit(active_inputs)) return false;

    motion_armed = 1U;
    armed_at_ms = ec_step_port_now_ms();
    return true;
}

bool ec_motion_test_start(ec_axis_t axis, ec_direction_t direction,
                          uint16_t active_inputs)
{
    uint32_t now_ms = ec_step_port_now_ms();

    if (!is_valid_axis(axis)) return false;
    if ((direction != EC_DIRECTION_0) && (direction != EC_DIRECTION_1)) {
        return false;
    }
    if ((motion_armed == 0U) ||
        ((uint32_t)(now_ms - armed_at_ms) > EC_MOTION_ARM_WINDOW_MS) ||
        has_motion_inhibit(active_inputs)) {
        motion_armed = 0U;
        return false;
    }

    motion_armed = 0U;
    counted_result = EC_STEP_RESULT_NONE;
    counted_timeout_ms = 0U;
    stop_active_test();
    if (!ec_step_port_set_direction(axis, direction) ||
        !ec_step_port_enable_axis(axis)) {
        stop_active_test();
        return false;
    }

    active_axis = axis;
    started_at_ms = now_ms;
    mode = EC_STEP_TEST_MOTION_ARMING;
    return true;
}

bool ec_motion_test_start_steps(ec_axis_t axis, ec_direction_t direction,
                                uint32_t steps, uint32_t frequency_hz,
                                uint16_t active_inputs)
{
    uint32_t now_ms = ec_step_port_now_ms();

    if (!is_valid_axis(axis)) return false;
    if ((direction != EC_DIRECTION_0) && (direction != EC_DIRECTION_1)) {
        return false;
    }
    if ((steps == 0U) || (steps > EC_STEP_MAX_STEPS)) return false;
    if ((frequency_hz < EC_STEP_MIN_HZ) ||
        (frequency_hz > EC_STEP_MAX_HZ)) {
        return false;
    }
    if ((motion_armed == 0U) ||
        ((uint32_t)(now_ms - armed_at_ms) > EC_MOTION_ARM_WINDOW_MS) ||
        has_motion_inhibit(active_inputs)) {
        motion_armed = 0U;
        return false;
    }

    motion_armed = 0U;
    counted_result = EC_STEP_RESULT_NONE;
    counted_timeout_ms = ((steps * UINT32_C(1000)) / frequency_hz) +
                         EC_MOTION_COUNTED_TIMEOUT_MARGIN_MS;
    stop_active_test();
    if (!ec_step_port_set_direction(axis, direction) ||
        !ec_step_port_enable_axis(axis) ||
        !ec_step_port_start_counted(axis, frequency_hz, steps)) {
        stop_active_test();
        return false;
    }

    active_axis = axis;
    started_at_ms = now_ms;
    counted_steps = steps;
    mode = EC_STEP_TEST_MOTION_COUNTED;
    return true;
}

/* ────────────────────────────────────────────────────────────────────────────
 * XY 双轴计步移动的内部共用实现（2026-10-22 提取）
 *
 * 与旧实现的唯一区别：**允许两轴使用不同频率**。
 *
 * 为什么需要不同频率：
 *   底层 ec_step_port_start_counted_xy() 本来就是"两轴同时启动、各自独立计数、
 *   各自独立频率"，并不做几何插补。要走出**直线**，只需让
 *       freq_x / freq_y == steps_x / steps_y
 *   两轴就同时到达 ⇒ 合成轨迹是直线（CNC 的常速合成法）。
 *   若两轴同频，短的那条腿先停，轨迹是"先斜后直"的折线。
 *
 * 超时按"较慢那条腿"算（t = steps/freq 取较大者）；同频时与旧实现结果完全一致。
 * ──────────────────────────────────────────────────────────────────────────── */
static bool start_steps_xy_impl(ec_direction_t x_direction, uint32_t x_steps,
                                ec_direction_t y_direction, uint32_t y_steps,
                                uint32_t x_frequency_hz, uint32_t y_frequency_hz,
                                uint16_t active_inputs)
{
    uint32_t now_ms = ec_step_port_now_ms();
    uint32_t t_x_ms;
    uint32_t t_y_ms;

    if (((x_direction != EC_DIRECTION_0) && (x_direction != EC_DIRECTION_1)) ||
        ((y_direction != EC_DIRECTION_0) && (y_direction != EC_DIRECTION_1))) {
        return false;
    }
    /* Both legs must be non-zero: a single-axis move belongs to
     * ec_motion_test_start_steps(), and a zero/zero "move" is a no-op. */
    if ((x_steps == 0U) || (x_steps > EC_STEP_MAX_STEPS) ||
        (y_steps == 0U) || (y_steps > EC_STEP_MAX_STEPS)) {
        return false;
    }
    if ((x_frequency_hz < EC_STEP_MIN_HZ) ||
        (x_frequency_hz > EC_STEP_MAX_HZ) ||
        (y_frequency_hz < EC_STEP_MIN_HZ) ||
        (y_frequency_hz > EC_STEP_MAX_HZ)) {
        return false;
    }
    if ((motion_armed == 0U) ||
        ((uint32_t)(now_ms - armed_at_ms) > EC_MOTION_ARM_WINDOW_MS) ||
        has_motion_inhibit(active_inputs)) {
        motion_armed = 0U;
        return false;
    }

    motion_armed = 0U;
    counted_result = EC_STEP_RESULT_NONE;
    /* 较慢那条腿决定超时线。同频时等价于旧的 "major_steps/freq + margin"。 */
    t_x_ms = (x_steps * UINT32_C(1000)) / x_frequency_hz;
    t_y_ms = (y_steps * UINT32_C(1000)) / y_frequency_hz;
    counted_timeout_ms = ((t_x_ms > t_y_ms) ? t_x_ms : t_y_ms) +
                         EC_MOTION_COUNTED_TIMEOUT_MARGIN_MS;
    stop_active_test();
    if (!ec_step_port_set_direction(EC_AXIS_X, x_direction) ||
        !ec_step_port_set_direction(EC_AXIS_Y, y_direction) ||
        !ec_step_port_enable_xy() ||
        !ec_step_port_start_counted_xy(x_steps, x_frequency_hz, y_steps,
                                       y_frequency_hz)) {
        stop_active_test();
        return false;
    }

    active_axis = EC_AXIS_NONE;
    started_at_ms = now_ms;
    counted_steps = 0U;
    counted_x_steps = x_steps;
    counted_y_steps = y_steps;
    mode = EC_STEP_TEST_MOTION_COUNTED_XY;
    return true;
}

bool ec_motion_test_start_steps_xy(ec_direction_t x_direction, uint32_t x_steps,
                                   ec_direction_t y_direction, uint32_t y_steps,
                                   uint32_t frequency_hz,
                                   uint16_t active_inputs)
{
    /* 原行为保持不变：两轴同频。既有测试依赖这个入口，签名与语义都不动。 */
    return start_steps_xy_impl(x_direction, x_steps, y_direction, y_steps,
                               frequency_hz, frequency_hz, active_inputs);
}

bool ec_motion_test_start_steps_xy2(ec_direction_t x_direction, uint32_t x_steps,
                                    ec_direction_t y_direction, uint32_t y_steps,
                                    uint32_t x_frequency_hz,
                                    uint32_t y_frequency_hz,
                                    uint16_t active_inputs)
{
    /* 新增：两轴各自频率。用于"直线合成"（freq 比 = 步数比）。 */
    return start_steps_xy_impl(x_direction, x_steps, y_direction, y_steps,
                               x_frequency_hz, y_frequency_hz, active_inputs);
}

void ec_motion_test_on_counted_done(void)
{
    if ((mode == EC_STEP_TEST_MOTION_COUNTED) ||
        (mode == EC_STEP_TEST_MOTION_COUNTED_XY)) {
        counted_result = EC_STEP_RESULT_DONE;
        stop_active_test();
    }
}

bool ec_motion_inhibit_from_raw(uint16_t raw_mask)
{
    /* Inputs are active-low (see ec_inputs_active_mask): a safety pin reads
     * LOW when triggered. Raw GPIO reads HIGH=1, so inhibit = any safety pin
     * LOW = (~raw_mask) & EC_MOTION_SAFETY_MASK != 0. Polarity MUST be
     * verified against the physical wiring before relying on this for safety
     * (see the pre-power-on forced-actions checklist, item 1). */
    return ((uint16_t)(~raw_mask) & EC_MOTION_SAFETY_MASK) != 0U;
}

void ec_motion_test_on_aborted(void)
{
    if (mode == EC_STEP_TEST_MOTION_COUNTED) {
        counted_result = EC_STEP_RESULT_ABORTED;
        stop_active_test();
    }
}

void ec_step_test_stop(void)
{
    stop_active_test();
    motion_armed = 0U;
    armed_at_ms = 0U;
    counted_result = EC_STEP_RESULT_NONE;
    counted_timeout_ms = 0U;
}

void ec_step_test_poll(uint32_t now_ms, uint16_t active_inputs)
{
    if ((motion_armed != 0U) &&
        ((uint32_t)(now_ms - armed_at_ms) > EC_MOTION_ARM_WINDOW_MS)) {
        motion_armed = 0U;
    }

    if ((mode == EC_STEP_TEST_MOTION_ARMING) ||
        (mode == EC_STEP_TEST_MOTION_RUNNING) ||
        (mode == EC_STEP_TEST_MOTION_COUNTED) ||
        (mode == EC_STEP_TEST_MOTION_COUNTED_XY)) {
        if (has_motion_inhibit(active_inputs)) {
            if ((mode == EC_STEP_TEST_MOTION_COUNTED) ||
                (mode == EC_STEP_TEST_MOTION_COUNTED_XY)) {
                counted_result = EC_STEP_RESULT_ABORTED;
            }
            stop_active_test();
            return;
        }
    }

    if ((mode == EC_STEP_TEST_MOTION_ARMING) &&
        ((uint32_t)(now_ms - started_at_ms) >= EC_MOTION_SETTLE_MS)) {
        if (!ec_step_port_start(active_axis, EC_TRACK_TEST_FREQUENCY_HZ)) {
            stop_active_test();
            return;
        }
        mode = EC_STEP_TEST_MOTION_RUNNING;
        started_at_ms = now_ms;
    } else if ((mode == EC_STEP_TEST_MOTION_RUNNING) &&
               ((uint32_t)(now_ms - started_at_ms) >=
                EC_MOTION_DURATION_MS)) {
        stop_active_test();
    } else if (((mode == EC_STEP_TEST_MOTION_COUNTED) ||
                (mode == EC_STEP_TEST_MOTION_COUNTED_XY)) &&
               ((uint32_t)(now_ms - started_at_ms) >=
                counted_timeout_ms)) {
        /* The ISR may complete the final tick and write DONE just before
         * this timeout check: DONE wins, so do not overwrite it. */
        if (counted_result == EC_STEP_RESULT_NONE) {
            counted_result = EC_STEP_RESULT_TIMEOUT;
        }
        stop_active_test();
    } else if ((mode == EC_STEP_TEST_SIGNAL_ONLY) &&
               ((uint32_t)(now_ms - started_at_ms) >=
                EC_STEP_TEST_DURATION_MS)) {
        stop_active_test();
    }
}

ec_axis_t ec_step_test_active_axis(void)
{
    return active_axis;
}

ec_step_test_mode_t ec_step_test_mode(void)
{
    return mode;
}

bool ec_motion_test_is_armed(void)
{
    return motion_armed != 0U;
}

uint32_t ec_motion_test_step_target(void)
{
    return (mode == EC_STEP_TEST_MOTION_COUNTED) ? counted_steps : 0U;
}

uint32_t ec_motion_test_step_remaining(void)
{
    return (mode == EC_STEP_TEST_MOTION_COUNTED) ?
           ec_step_port_counted_remaining() : 0U;
}

uint32_t ec_motion_test_x_step_target(void)
{
    return (mode == EC_STEP_TEST_MOTION_COUNTED_XY) ? counted_x_steps : 0U;
}

uint32_t ec_motion_test_y_step_target(void)
{
    return (mode == EC_STEP_TEST_MOTION_COUNTED_XY) ? counted_y_steps : 0U;
}

uint32_t ec_motion_test_x_step_remaining(void)
{
    return (mode == EC_STEP_TEST_MOTION_COUNTED_XY) ?
           ec_step_port_counted_remaining_for(EC_AXIS_X) : 0U;
}

uint32_t ec_motion_test_y_step_remaining(void)
{
    return (mode == EC_STEP_TEST_MOTION_COUNTED_XY) ?
           ec_step_port_counted_remaining_for(EC_AXIS_Y) : 0U;
}

ec_step_result_t ec_motion_test_step_result(void)
{
    return counted_result;
}
