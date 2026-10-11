#include "ec_servo_test.h"

#include "ec_inputs.h"

#define EC_SERVO_ARM_WINDOW_MS UINT32_C(10000)
#define EC_SERVO_RUN_MS        UINT32_C(2000)
/* 2026-09-15 用户裁决：X/Y 不装限位开关 → 遮罩收敛为仅 ESTOP。
 * 与 ec_axis_driver.c / ec_demo.c / ec_step_test.c 的三处遮罩保持一致。 */
#define EC_SERVO_SAFETY_MASK  (EC_INPUT_ESTOP_FB)

static ec_servo_test_mode_t mode;
static uint32_t armed_at_ms;
static uint32_t started_at_ms;
static uint16_t active_pulse_us;

static bool has_safety_inhibit(uint16_t active_inputs)
{
    return (active_inputs & EC_SERVO_SAFETY_MASK) != 0U;
}

static bool is_allowed_pulse(uint16_t pulse_us)
{
    /* 🔴 2026-09-19 新增 900/950：用户实机观察 P1000 时夹爪"还可以再往上开一点点"，
     * 需要更低脉宽才能探到完全张开的端点。
     * ⚠️ 往下压脉宽 = 把舵机推向机械端点。越过机械限位会持续堵转、电流拉满、发热甚至
     *    烧毁舵机。故只用小步（950→900）试探，**听到持续嗡嗡声/异响立刻 SERVO STOP**，
     *    并把最终取值定在"刚好完全张开"之上，不要贴死机械端点。
     * ⚠️ 本表与 ec_diag.c 的 servo_pulse_from_command() 命令表必须同步增删，
     *    否则会出现"命令能解析但被这里拒掉"的不一致。 */
    /* 2026-09-21 三改：用户现场目视 P750 仍"不够开"，要求继续下探。
     * 一次开放 650/675/700/725 四档（25us 一步），避免为每一档重烧一次。
     * 🔴 越往下越贴机械端点：听到持续嗡嗡声/异响立刻 SERVO STOP，
     *    最终取值定在"刚好完全张开"之上，不要贴死端点。 */
    /* 2026-09-21 四改：用户继续要求更低（625）⇒ 再追加 550/575/600/625 四档。
     * 🔴 已连续下探 900→675 全程无堵转；再往下每一步都更贴机械端点，必须逐档听声。 */
    return (pulse_us == UINT16_C(550)) ||
           (pulse_us == UINT16_C(575)) ||
           (pulse_us == UINT16_C(600)) ||
           (pulse_us == UINT16_C(625)) ||
           (pulse_us == UINT16_C(650)) ||
           (pulse_us == UINT16_C(675)) ||
           (pulse_us == UINT16_C(700)) ||
           (pulse_us == UINT16_C(725)) ||
           (pulse_us == UINT16_C(750)) ||   /* 2026-09-21 新增：用户要求张开到 750 */
           (pulse_us == UINT16_C(800)) ||   /* 2026-09-21 新增：回退扫描档 */
           (pulse_us == UINT16_C(850)) ||   /* 2026-09-19 二改：900→850，更张开 */
           (pulse_us == UINT16_C(870)) ||   /* 2026-09-21 新增：回退扫描档 */
           (pulse_us == UINT16_C(900)) ||
           (pulse_us == UINT16_C(950)) ||
           (pulse_us == UINT16_C(1000)) ||
           (pulse_us == UINT16_C(1100)) ||
           (pulse_us == UINT16_C(1200)) ||
           (pulse_us == UINT16_C(1300)) ||
           (pulse_us == UINT16_C(1500)) ||
           (pulse_us == UINT16_C(1700)) ||
           (pulse_us == UINT16_C(1900));
}

static void clear_state(void)
{
    mode = EC_SERVO_TEST_IDLE;
    armed_at_ms = 0U;
    started_at_ms = 0U;
    active_pulse_us = 0U;
}

void ec_servo_test_init(void)
{
    clear_state();
}

bool ec_servo_test_arm(uint16_t active_inputs, bool step_test_busy)
{
    ec_servo_test_stop();
    if (step_test_busy || has_safety_inhibit(active_inputs)) return false;

    armed_at_ms = ec_servo_port_now_ms();
    mode = EC_SERVO_TEST_ARMED;
    return true;
}

bool ec_servo_test_start(uint16_t pulse_us, uint16_t active_inputs,
                         bool step_test_busy)
{
    uint32_t now_ms = ec_servo_port_now_ms();
    bool authorized = (mode == EC_SERVO_TEST_ARMED) &&
                      ((uint32_t)(now_ms - armed_at_ms) <=
                       EC_SERVO_ARM_WINDOW_MS);

    if (!authorized) {
        if (mode == EC_SERVO_TEST_RUNNING) return false;
        clear_state();
        return false;
    }

    /* An authorization is single-use, including rejected start attempts. */
    clear_state();
    if (!is_allowed_pulse(pulse_us) || step_test_busy ||
        has_safety_inhibit(active_inputs)) {
        return false;
    }
    if (!ec_servo_port_start(pulse_us)) {
        ec_servo_port_stop();
        return false;
    }

    mode = EC_SERVO_TEST_RUNNING;
    started_at_ms = now_ms;
    active_pulse_us = pulse_us;
    return true;
}

void ec_servo_test_stop(void)
{
    ec_servo_port_stop();
    clear_state();
}

void ec_servo_test_poll(uint32_t now_ms, uint16_t active_inputs)
{
    if (mode == EC_SERVO_TEST_ARMED) {
        if (has_safety_inhibit(active_inputs) ||
            ((uint32_t)(now_ms - armed_at_ms) > EC_SERVO_ARM_WINDOW_MS)) {
            clear_state();
        }
        return;
    }

    if (mode == EC_SERVO_TEST_RUNNING) {
        if (has_safety_inhibit(active_inputs) ||
            ((uint32_t)(now_ms - started_at_ms) >= EC_SERVO_RUN_MS)) {
            ec_servo_test_stop();
        }
    }
}

bool ec_servo_test_is_armed(void)
{
    return mode == EC_SERVO_TEST_ARMED;
}

bool ec_servo_test_is_running(void)
{
    return mode == EC_SERVO_TEST_RUNNING;
}

bool ec_servo_test_blocks_step(void)
{
    return mode != EC_SERVO_TEST_IDLE;
}

uint16_t ec_servo_test_active_pulse_us(void)
{
    return active_pulse_us;
}

ec_servo_test_mode_t ec_servo_test_mode(void)
{
    return mode;
}
