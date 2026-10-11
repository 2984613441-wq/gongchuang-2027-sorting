#include "ec_diag.h"
#include "ec_app.h"
#include "ec_axis_driver.h"
#include "ec_demo.h"
#include "ec_servo_test.h"
#include "ec_step_test.h"

#include <stdbool.h>
#include <string.h>

static char output[512];

/* This isolated diagnostic target does not link the production App. */
ec_state_t ec_app_state(void) { return EC_STATE_FAULT_LOCK; }

void ec_diag_port_write(const char *text)
{
    size_t used = strlen(output);
    size_t length = strlen(text);
    if ((used + length) < sizeof(output)) {
        memcpy(&output[used], text, length + 1U);
    }
}

ec_input_snapshot_t ec_board_read_inputs(void)
{
    ec_input_snapshot_t inputs = {
        EC_INPUT_ALL_MASK, EC_INPUT_ALL_MASK, 0U
    };
    return inputs;
}

/* 2026-09-18：LIGHT ON|OFF 命令的桩（该命令不受 test-build 开关影响）。 */
void ec_board_light_set(bool on) { (void)on; }
/* 2026-09-18：GRIP 命令的桩（该命令不受 test-build 开关影响）。 */
bool ec_grip_port_move(uint16_t position, uint16_t time_ms)
{
    (void)position; (void)time_ms; return true;
}

ec_step_test_mode_t ec_step_test_mode(void) { return EC_STEP_TEST_IDLE; }
bool ec_motion_test_is_armed(void) { return false; }
ec_axis_t ec_step_test_active_axis(void) { return EC_AXIS_NONE; }
void ec_step_test_stop(void) { }
bool ec_step_test_start(ec_axis_t axis) { (void)axis; return false; }
bool ec_motion_test_arm(uint16_t active_inputs)
{ (void)active_inputs; return false; }
bool ec_motion_test_start(ec_axis_t axis, ec_direction_t direction,
                          uint16_t active_inputs)
{ (void)axis; (void)direction; (void)active_inputs; return false; }
bool ec_motion_test_start_steps(ec_axis_t axis, ec_direction_t direction,
                                uint32_t steps, uint32_t frequency_hz,
                                uint16_t active_inputs)
{ (void)axis; (void)direction; (void)steps; (void)frequency_hz;
  (void)active_inputs; return false; }
bool ec_motion_test_start_steps_xy(ec_direction_t x_direction, uint32_t x_steps,
                                   ec_direction_t y_direction, uint32_t y_steps,
                                   uint32_t frequency_hz, uint16_t active_inputs)
{ (void)x_direction; (void)x_steps; (void)y_direction; (void)y_steps;
  (void)frequency_hz; (void)active_inputs; return false; }
uint32_t ec_motion_test_step_target(void) { return 0U; }
uint32_t ec_motion_test_step_remaining(void) { return 0U; }
ec_step_result_t ec_motion_test_step_result(void)
{ return EC_STEP_RESULT_NONE; }

bool ec_servo_test_is_armed(void) { return false; }
bool ec_servo_test_is_running(void) { return false; }
bool ec_servo_test_blocks_step(void) { return false; }
uint16_t ec_servo_test_active_pulse_us(void) { return 0U; }
ec_servo_test_mode_t ec_servo_test_mode(void) { return EC_SERVO_TEST_IDLE; }
void ec_servo_test_stop(void) { }
bool ec_servo_test_arm(uint16_t active_inputs, bool step_test_busy)
{ (void)active_inputs; (void)step_test_busy; return false; }
bool ec_servo_test_start(uint16_t pulse_us, uint16_t active_inputs,
                         bool step_test_busy)
{ (void)pulse_us; (void)active_inputs; (void)step_test_busy; return false; }

bool ec_demo_start(uint16_t active_inputs)
{ (void)active_inputs; return false; }
void ec_demo_stop(void) { }
bool ec_demo_is_active(void) { return false; }

/* ── 2026-09-22：AXIS 命令的实现链补桩（A2 遗留）─────────────────────────
 * 为什么需要：ec_diag.c 的 AXIS 分支（:457-482）会调下面这些**生产侧**函数，
 * 而本目标只编 test_diag_disabled.c + ec_diag.c（tests/CMakeLists.txt:61-62），
 * 不链接 App 的其它 .c ⇒ 此前该目标**链接失败**（缺这 8 个符号），
 * 在 ctest 里一直显示 Not Run，等于这门测试从未跑过。
 * ⚠️ A2 上一轮把 3 个桩加进了 tests/test_app.c —— 但**本目标不编 test_app.c**
 *    ⇒ 补在那儿对这里没有任何帮助（这正是漏掉的那一半）。
 * 桩一律给"无故障 / 中性"值：AXIS 那几行只是回显，不得改变下面 GROUP_TEST=0
 * 那三条断言的语义（STATUS 与 AXIS 是分开两次 ec_diag_port_write，互不干扰）。 */
ec_axis_state_t ec_axis_driver_state(void) { return EC_AXIS_STATE_IDLE; }
ec_axis_result_t ec_axis_driver_result(void) { return EC_AXIS_RESULT_OK; }
uint32_t ec_axis_driver_progress(void) { return 0U; }
uint32_t ec_axis_driver_completed_move_count(void) { return 0U; }
uint32_t ec_step_port_now_ms(void) { return 0U; }
const ec_axis_driver_diag_t *ec_axis_driver_diag(void)
{
    /* 真实实现只在 fault() 时填；这里给全零 = "没有锁存任何故障现场"。 */
    static const ec_axis_driver_diag_t none = {0};
    return &none;
}
/* 没有发生过"轴被孤立"停轴 ⇒ 返回 false，AXIS 不会多打 STOPCAUSE/WINDOW 行。 */
bool ec_app_last_stop_snapshot(ec_app_stop_snapshot_t *out)
{
    if (out != NULL) {
        (void)memset(out, 0, sizeof(*out));
    }
    return false;
}
bool ec_app_stop_snapshot_at(uint8_t which, ec_app_stop_snapshot_t *out)
{
    (void)which;
    return ec_app_last_stop_snapshot(out);
}

int main(void)
{
    output[0] = '\0';
    ec_diag_init();
    ec_diag_process_line("GROUP ARM");
    if (strstr(output, "ERR GROUP_TEST_DISABLED") == NULL) return 1;
    ec_diag_process_line("GROUP START XDIR0 YDIR0 OPEN");
    if (strstr(output, "ERR GROUP_TEST_DISABLED") == NULL) return 2;
    ec_diag_process_line("STATUS");
    if (strstr(output, "GROUP_TEST=0 GROUP_ARMED=0 GROUP_ACTIVE=0") == NULL) {
        return 3;
    }
    return 0;
}
