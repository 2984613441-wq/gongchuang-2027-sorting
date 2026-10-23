#include "ec_diag.h"
#include "ec_app.h"
#include "ec_barrier_test.h"
#include "ec_drop_servo.h"
#include "ec_group_test.h"
#include "ec_servo_test.h"
#include "ec_step_test.h"
#include "test_support.h"
#include <string.h>
static char tx_log[8192]; static size_t tx_used;
uint16_t fake_active_inputs;
void ec_diag_port_write(const char *text) { size_t length = strlen(text); TEST_ASSERT(tx_used + length < sizeof(tx_log)); memcpy(&tx_log[tx_used], text, length + 1U); tx_used += length; }
ec_input_snapshot_t ec_board_read_inputs(void) { ec_input_snapshot_t s = { EC_INPUT_ALL_MASK, EC_INPUT_ALL_MASK, fake_active_inputs }; return s; }
/* 2026-09-18：LIGHT ON|OFF 命令的桩。记录最后设定的状态，便于断言。 */
bool fake_light_state;
void ec_board_light_set(bool on) { fake_light_state = on; }
/* 2026-10-18：补光灯改为 WS2812 后，ec_diag.c 的 LIGHT LV / LIGHT RGB / LIGHT?
 * 与 ec_app.c 的初始化会调用下面这些函数。主机测试不编译 HAL 代码，
 * 故在此提供最小桩，只记录最后一次亮度，便于断言。 */
uint8_t fake_ws2812_level;
void ec_ws2812_init(void) { fake_ws2812_level = 0U; }
uint8_t ec_ws2812_white_level(void) { return fake_ws2812_level; }
bool ec_ws2812_set_white_level(uint8_t level) { fake_ws2812_level = level; return true; }
void ec_ws2812_fill(uint8_t r, uint8_t g, uint8_t b)
{
  (void)r;
  (void)g;
  (void)b;
}
/* 2026-10-18：TOF/TOFDBG/TOFSEND 命令的桩。主机测试不编译 ec_tof.c
 * （它依赖 UART4 HAL），只提供返回固定值的替身。 */
void ec_tof_init(void) { }
bool ec_tof_latest(uint16_t *dist_mm, uint8_t *conf, uint32_t *age_ms,
                   uint32_t now_ms)
{
  (void)now_ms;
  if (dist_mm != NULL) { *dist_mm = 0U; }
  if (conf != NULL) { *conf = 0U; }
  if (age_ms != NULL) { *age_ms = 0U; }
  return false;
}
bool ec_tof_have_frame(void) { return false; }
uint32_t ec_tof_frames(void) { return 0U; }
uint32_t ec_tof_errors(void) { return 0U; }
uint32_t ec_tof_raw_bytes(void) { return 0U; }
uint32_t ec_tof_uart_errors(void) { return 0U; }
void ec_tof_send_test(void) { }

/* 2026-10-18 新增：TOFRAW 命令的桩。主机测试不编译 ec_tof.c，
 * 故这里提供空实现（返回 0 字节 + 原因码 0）。 */
uint8_t ec_tof_raw_ring(uint8_t *out, uint8_t max)
{
  (void)out;
  (void)max;
  return 0U;
}
uint8_t ec_tof_last_reject(char *line, uint8_t max)
{
  if ((line != NULL) && (max > 0U)) {
    line[0] = '\0';
  }
  return 0U;
}
/* 2026-09-18：GRIP 命令的桩。记录最后一次下发的夹爪位置/时间，供断言使用。 */
uint16_t fake_grip_pos;
uint16_t fake_grip_time;
bool fake_grip_ok = true;
bool ec_grip_port_move(uint16_t position, uint16_t time_ms)
{
  fake_grip_pos = position;
  fake_grip_time = time_ms;
  return fake_grip_ok;
}
/* 2026-10-22：DROP 命令（落料舵机 PE5/TIM9_CH1）的板级桩。
 * ec_drop_servo.c 只依赖这两个板级函数，主机侧用假实现记录最后下发的脉宽。 */
uint16_t fake_drop_us;
bool fake_drop_ok = true;
bool ec_board_drop_servo_set_us(uint16_t pulse_us)
{
  if (!fake_drop_ok) {
    return false;
  }
  fake_drop_us = pulse_us;
  return true;
}
void ec_board_drop_servo_stop(void)
{
  fake_drop_us = 0U;
}
static void assert_servo_command(const char *command, uint16_t pulse_us) {
  ec_diag_process_line("SERVO ARM");
  ec_diag_process_line(command);
  TEST_ASSERT(ec_servo_test_active_pulse_us() == pulse_us);
  ec_diag_process_line("SERVO STOP");
}
static void assert_group_command(const char *command,
                                 ec_direction_t x_direction,
                                 ec_direction_t y_direction,
                                 uint16_t pulse_us) {
  ec_diag_process_line("GROUP ARM");
  ec_diag_process_line(command);
  TEST_ASSERT(ec_group_test_mode() == EC_GROUP_TEST_SETTLING);
  TEST_ASSERT(ec_group_test_x_direction() == x_direction);
  TEST_ASSERT(ec_group_test_y_direction() == y_direction);
  TEST_ASSERT(ec_group_test_servo_pulse_us() == pulse_us);
  ec_diag_process_line("GROUP STOP");
}
void test_diag(void) {
  tx_log[0] = '\0'; tx_used = 0U; fake_active_inputs = 0U; ec_step_test_init(); ec_servo_test_init(); ec_group_test_init(); ec_diag_init();
  ec_diag_process_line("HELP");
  TEST_ASSERT(strstr(tx_log, "P1000|P1100|P1200|P1300|P1500|P1700|P1900") != NULL);
  TEST_ASSERT(strstr(tx_log, "GROUP START XDIR0|XDIR1 YDIR0|YDIR1 OPEN|CLOSE") != NULL);
  ec_diag_process_line("MOTION ARM"); ec_diag_process_line("STEP X"); TEST_ASSERT(ec_step_test_active_axis() == EC_AXIS_X);
  ec_diag_process_line("STEP STOP"); TEST_ASSERT(ec_step_test_active_axis() == EC_AXIS_NONE);
  ec_diag_process_line("STEP X 999"); TEST_ASSERT(ec_step_test_active_axis() == EC_AXIS_NONE); TEST_ASSERT(strstr(tx_log, "ERR BAD_COMMAND") != NULL);
  ec_diag_process_line("INPUTS"); TEST_ASSERT(strstr(tx_log, "INPUTS RAW=03FF STABLE=03FF ACTIVE=0000") != NULL);
  ec_diag_process_line("STATUS"); TEST_ASSERT(strstr(tx_log, "SAFE_LOCK=1") != NULL);
  TEST_ASSERT(strstr(tx_log, "GROUP_TEST=1 GROUP_ARMED=0 GROUP_ACTIVE=0") != NULL);
  TEST_ASSERT(strstr(tx_log, "STEP_RESULT=0") != NULL);

  /* ===== 2026-10-22 新增：DROP 落料舵机（PE5/TIM9_CH1）命令 =====
   * ec_drop_servo 必须 init 过后才接受动作（未 init 时 set_us 拒绝，fail-closed）。
   * host 侧 ec_board_drop_servo_set_us 由本文件顶部假实现记录到 fake_drop_us。 */
  ec_diag_process_line("DROP OPEN");
  TEST_ASSERT(strstr(tx_log, "ERR DROP_NOT_READY") != NULL);   /* 未 init 必须拒绝 */

  TEST_ASSERT(ec_drop_servo_init());                            /* 桩恒成功 */
  tx_log[0] = '\0'; tx_used = 0U;

  /* 查询：未 init 后已 init，current 应为 MID(1500) */
  ec_diag_process_line("DROP?");
  TEST_ASSERT(strstr(tx_log, "OK DROP ready=1 current_us=1500") != NULL);

  /* ----- POS 合法范围 [MIN_US, MAX_US] -----
   * 2026-10-22：范围由 [500,2500] 收紧为 [700,2300]（MG996R 270° 量程，
   *   1500±655=±90°；700/2300 在端点外侧再留余量，防发到机械端点堵转烧舵机）。
   * 断言同时用常量与字面值，防日后改常量时测试悄悄跟着变。 */
  TEST_ASSERT(EC_DROP_SERVO_MIN_US == 700U);
  TEST_ASSERT(EC_DROP_SERVO_MAX_US == 2300U);

  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("DROP POS 1000");
  TEST_ASSERT(strstr(tx_log, "OK DROP POS 1000") != NULL);
  TEST_ASSERT(fake_drop_us == 1000U);

  /* 越界：下界外侧 699 / 上界外侧 2301 都必须被拒且【不改输出】 */
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("DROP POS 699");
  TEST_ASSERT(strstr(tx_log, "ERR DROP_RANGE") != NULL);
  TEST_ASSERT(fake_drop_us == 1000U);                           /* 未变 */

  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("DROP POS 2301");
  TEST_ASSERT(strstr(tx_log, "ERR DROP_RANGE") != NULL);
  TEST_ASSERT(fake_drop_us == 1000U);                           /* 未变 */

  /* 边界值 700 / 2300 必须通过 */
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("DROP POS 700");
  TEST_ASSERT(fake_drop_us == 700U);
  ec_diag_process_line("DROP POS 2300");
  TEST_ASSERT(fake_drop_us == 2300U);

  /* MG996R 的两个实测工作点（±90°）必须能下发 */
  ec_diag_process_line("DROP POS 845");
  TEST_ASSERT(fake_drop_us == 845U);
  ec_diag_process_line("DROP POS 2155");
  TEST_ASSERT(fake_drop_us == 2155U);

  /* MID / OPEN / CLOSE 三个动作别名 —— 2026-10-22 起是真实 MG996R 值：
   *   MID=1500（中位）、OPEN=845（−90°）、CLOSE=2155（+90°）
   * ⚠️ OPEN/CLOSE 的物理方向待接线后实测；若安装反向，交换头文件两行即可，
   *    本断言用的是宏而非字面值，交换后不需要改测试。 */
  ec_diag_process_line("DROP MID");
  TEST_ASSERT(fake_drop_us == 1500U);
  ec_diag_process_line("DROP OPEN");
  TEST_ASSERT(fake_drop_us == EC_DROP_SERVO_OPEN_US);
  ec_diag_process_line("DROP CLOSE");
  TEST_ASSERT(fake_drop_us == EC_DROP_SERVO_CLOSE_US);

  /* 三个动作脉宽必须互不相同（防止又被填成同一个占位值）*/
  TEST_ASSERT(EC_DROP_SERVO_OPEN_US != EC_DROP_SERVO_CLOSE_US);
  TEST_ASSERT(EC_DROP_SERVO_MID_US != EC_DROP_SERVO_OPEN_US);

  /* 未知子命令必须报用法，不能静默通过 */
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("DROP BOGUS");
  TEST_ASSERT(strstr(tx_log, "ERR DROP_USAGE") != NULL);

  /* 板级失败时状态不得更新（fail-closed） */
  fake_drop_ok = false;
  TEST_ASSERT(!ec_drop_servo_set_us(700U));
  fake_drop_ok = true;
  TEST_ASSERT(ec_drop_servo_current_us() != 700U);
  ec_diag_process_line("MOVE X DIR0"); TEST_ASSERT(strstr(tx_log, "ERR MOTION_NOT_ARMED_OR_INHIBITED") != NULL);
  ec_diag_process_line("MOTION ARM"); TEST_ASSERT(ec_motion_test_is_armed());
  ec_diag_process_line("MOVE X DIR0"); TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_MOTION_ARMING);
  ec_diag_process_line("STEP STOP"); TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_IDLE);

  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("MOTION ARM");
  ec_diag_process_line("MOVE X DIR0 STEPS 2000 HZ 500");
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_MOTION_COUNTED);
  TEST_ASSERT(ec_motion_test_step_target() == 2000U);
  TEST_ASSERT(ec_motion_test_step_remaining() == 2000U);
  ec_motion_test_on_counted_done();
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("STATUS");
  TEST_ASSERT(strstr(tx_log, "STEP_RESULT=1") != NULL);
  ec_diag_process_line("STEP STOP");
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_IDLE);
  TEST_ASSERT(ec_motion_test_step_result() == EC_STEP_RESULT_NONE);

  /* ===== 2026-10-22 新增：MOVE XY 双轴联动（直线合成）命令 =====
   * 关键不变量：fx/fy 必须等于 nx/ny，两轴才会同时到达 ⇒ 直线。
   * 下面用 4000:2000 = 2:1 的步数比，要求 fx:fy 也是 2:1。 */

  /* (1) 未 ARM 必须拒绝（与单轴 MOVE 同规矩，fail-closed） */
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("MOVE XY XDIR0 STEPS 4000 YDIR0 STEPS 2000 HZ 500");
  TEST_ASSERT(strstr(tx_log, "ERR MOTION_NOT_ARMED_OR_INHIBITED") != NULL);

  /* (2) ARM 后受理，且频率按步数比合成：较长腿=500Hz，较短腿=250Hz */
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("MOTION ARM");
  ec_diag_process_line("MOVE XY XDIR0 STEPS 4000 YDIR0 STEPS 2000 HZ 500");
  TEST_ASSERT(strstr(tx_log, "OK MOTION XY STARTING") != NULL);
  TEST_ASSERT(strstr(tx_log, "fx=500") != NULL);
  TEST_ASSERT(strstr(tx_log, "fy=250") != NULL);
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_MOTION_COUNTED_XY);
  TEST_ASSERT(ec_motion_test_x_step_target() == 4000U);
  TEST_ASSERT(ec_motion_test_y_step_target() == 2000U);
  ec_diag_process_line("STEP STOP");
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_IDLE);

  /* (3) 反向比例：Y 比 X 长 ⇒ fx 应降、fy 保持 */
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("MOTION ARM");
  ec_diag_process_line("MOVE XY XDIR0 STEPS 1000 YDIR0 STEPS 4000 HZ 800");
  TEST_ASSERT(strstr(tx_log, "OK MOTION XY STARTING") != NULL);
  TEST_ASSERT(strstr(tx_log, "fx=200") != NULL);   /* 800*1000/4000 */
  TEST_ASSERT(strstr(tx_log, "fy=800") != NULL);
  ec_diag_process_line("STEP STOP");

  /* (4) 等步数 ⇒ 两轴同频 */
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("MOTION ARM");
  ec_diag_process_line("MOVE XY XDIR1 STEPS 2000 YDIR1 STEPS 2000 HZ 500");
  TEST_ASSERT(strstr(tx_log, "fx=500") != NULL);
  TEST_ASSERT(strstr(tx_log, "fy=500") != NULL);
  ec_diag_process_line("STEP STOP");

  /* (5) 格式错误必须报用法（不许静默失败） */
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("MOVE XY XDIR0 STEPS 4000 HZ 500");
  TEST_ASSERT(strstr(tx_log, "ERR MOVE_XY_USAGE") != NULL);

  /* (6) 越界必须拒绝：方向非 0/1、步数 0 / 超上限、频率越界 */
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("MOVE XY XDIR2 STEPS 100 YDIR0 STEPS 100 HZ 500");
  TEST_ASSERT(strstr(tx_log, "ERR MOVE_XY_RANGE") != NULL);
  ec_diag_process_line("MOVE XY XDIR0 STEPS 0 YDIR0 STEPS 100 HZ 500");
  TEST_ASSERT(strstr(tx_log, "ERR MOVE_XY_RANGE") != NULL);
  ec_diag_process_line("MOVE XY XDIR0 STEPS 16001 YDIR0 STEPS 100 HZ 500");
  TEST_ASSERT(strstr(tx_log, "ERR MOVE_XY_RANGE") != NULL);
  ec_diag_process_line("MOVE XY XDIR0 STEPS 100 YDIR0 STEPS 100 HZ 5");
  TEST_ASSERT(strstr(tx_log, "ERR MOVE_XY_RANGE") != NULL);

  /* (7) MOVE XY 不得被单轴解析器误吞（旧行为回归防线） */
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("MOTION ARM");
  ec_diag_process_line("MOVE X DIR0 STEPS 100 HZ 500");
  TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_MOTION_COUNTED);
  TEST_ASSERT(ec_motion_test_step_target() == 100U);
  ec_diag_process_line("STEP STOP");

  /* ===== 2026-10-23 新增：SPEED 运行时调速（T8 安全速度实测）=====
   * 目的：烧录一次后可任意扫档，不用每试一个速度就改代码重烧。
   * 合法域：201..10000（必须高于轨迹曲线起止频率 200Hz）。 */

  /* (1) 默认值应为编译期默认 EC_STEP_CRUISE_HZ_DEFAULT
   * 2026-10-23：默认值由 5000 提到 8000（方框复位测试实测 8000Hz 不丢步）。
   * 这里同时断言宏的字面值，防止有人改了宏而测试悄悄跟着变。 */
  TEST_ASSERT(EC_STEP_CRUISE_HZ_DEFAULT == 8000U);
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("SPEED?");
  TEST_ASSERT(strstr(tx_log, "OK SPEED cruise_hz=8000") != NULL);
  TEST_ASSERT(ec_step_port_get_cruise_hz() == EC_STEP_CRUISE_HZ_DEFAULT);

  /* (2) 设 6000 生效（与默认值 8000 不同，才能证明命令真的改了值），并能读回 */
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("SPEED 6000");
  TEST_ASSERT(strstr(tx_log, "OK SPEED cruise_hz=6000") != NULL);
  TEST_ASSERT(ec_step_port_get_cruise_hz() == 6000U);
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("SPEED?");
  TEST_ASSERT(strstr(tx_log, "cruise_hz=6000") != NULL);

  /* (3) 上界 10000 合法 */
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("SPEED 10000");
  TEST_ASSERT(strstr(tx_log, "OK SPEED cruise_hz=10000") != NULL);

  /* (4) 越界必须拒绝且【不改原值】：10001 / 200 / 0 / 10 */
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("SPEED 10001");
  TEST_ASSERT(strstr(tx_log, "ERR SPEED_RANGE") != NULL);
  TEST_ASSERT(ec_step_port_get_cruise_hz() == 10000U);      /* 未变 */

  ec_diag_process_line("SPEED 200");                        /* 必须 >200 */
  TEST_ASSERT(strstr(tx_log, "ERR SPEED_RANGE") != NULL);
  TEST_ASSERT(ec_step_port_get_cruise_hz() == 10000U);      /* 未变 */

  ec_diag_process_line("SPEED 0");                          /* < EC_STEP_MIN_HZ */
  TEST_ASSERT(strstr(tx_log, "ERR SPEED_RANGE") != NULL);
  TEST_ASSERT(ec_step_port_get_cruise_hz() == 10000U);      /* 未变 */

  ec_diag_process_line("SPEED 10");                         /* 等于 MIN_HZ 但仍 <=200 */
  TEST_ASSERT(strstr(tx_log, "ERR SPEED_RANGE") != NULL);
  TEST_ASSERT(ec_step_port_get_cruise_hz() == 10000U);      /* 未变 */

  /* (5) 非数字必须报用法，不能静默 */
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("SPEED abc");
  TEST_ASSERT(strstr(tx_log, "ERR SPEED_USAGE") != NULL);

  /* (6) 恢复到默认值（8000），避免影响后续用例 */
  ec_diag_process_line("SPEED 8000");
  TEST_ASSERT(ec_step_port_get_cruise_hz() == EC_STEP_CRUISE_HZ_DEFAULT);

  /* ===== 2026-10-23 新增：INTERP 生产路径开关（R3 接入）=====
   * 默认必须是 off —— 保证"上电即与接入前逐字节相同"，不需要先做任何事。
   * 若默认 on，任何人烧了这版就直接换了运动计划，而插补版还没经实机验证。 */
  TEST_ASSERT(!ec_app_xy_interp_enabled());       /* 默认关 */

  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("INTERP?");
  TEST_ASSERT(strstr(tx_log, "OK INTERP off") != NULL);

  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("INTERP ON");
  TEST_ASSERT(strstr(tx_log, "OK INTERP on") != NULL);
  TEST_ASSERT(ec_app_xy_interp_enabled());

  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("INTERP?");
  TEST_ASSERT(strstr(tx_log, "OK INTERP on") != NULL);

  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("INTERP OFF");
  TEST_ASSERT(strstr(tx_log, "OK INTERP off") != NULL);
  TEST_ASSERT(!ec_app_xy_interp_enabled());

  /* 拼写错误不得被当成有效开关 */
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("INTERP ONX");
  TEST_ASSERT(strstr(tx_log, "OK INTERP on") == NULL);

  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("MOTION ARM");
  ec_diag_process_line("MOVE X DIR0 STEPS 0 HZ 500");
  TEST_ASSERT(strstr(tx_log, "ERR BAD_COMMAND") != NULL);
  ec_diag_process_line("MOVE X DIR0 STEPS 2000 HZ 5");
  TEST_ASSERT(strstr(tx_log, "ERR BAD_COMMAND") != NULL);
  ec_diag_process_line("MOVE X DIR0 STEPS 2000");
  TEST_ASSERT(strstr(tx_log, "ERR BAD_COMMAND") != NULL);
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("MOVE X DIR0 STEPS 1000001 HZ 100");
  TEST_ASSERT(strstr(tx_log, "ERR BAD_COMMAND") != NULL);
  ec_step_test_stop();
  TEST_ASSERT(!ec_motion_test_is_armed());

  ec_diag_process_line("SERVO PB10 P1500");
  TEST_ASSERT(strstr(tx_log, "ERR SERVO_NOT_ARMED") != NULL);
  ec_diag_process_line("SERVO ARM"); TEST_ASSERT(ec_servo_test_is_armed());
  ec_diag_process_line("SERVO PB10 P1500"); TEST_ASSERT(ec_servo_test_is_running());
  TEST_ASSERT(ec_servo_test_active_pulse_us() == 1500U);
  ec_diag_process_line("STEP X"); TEST_ASSERT(strstr(tx_log, "ERR TEST_BUSY") != NULL);
  ec_diag_process_line("STOP ALL"); TEST_ASSERT(!ec_servo_test_is_running());

  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("GROUP START XDIR0 YDIR0 OPEN");
  TEST_ASSERT(strstr(tx_log, "ERR GROUP_NOT_ARMED") != NULL);
  ec_diag_process_line("GROUP ARM");
  TEST_ASSERT(ec_group_test_is_armed());
  TEST_ASSERT(strstr(tx_log, "OK GROUP ARMED 10S") != NULL);
  ec_diag_process_line("STEP X");
  ec_diag_process_line("MOTION ARM");
  ec_diag_process_line("SERVO ARM");
  TEST_ASSERT(strstr(tx_log, "ERR TEST_BUSY") != NULL);
  TEST_ASSERT(strstr(tx_log, "ERR SERVO_INHIBITED_OR_BUSY") != NULL);
  ec_diag_process_line("GROUP START XDIR1 YDIR0 OPEN");
  TEST_ASSERT(ec_group_test_mode() == EC_GROUP_TEST_SETTLING);
  TEST_ASSERT(!ec_group_test_is_armed());
  TEST_ASSERT(ec_group_test_x_direction() == EC_DIRECTION_1);
  TEST_ASSERT(ec_group_test_y_direction() == EC_DIRECTION_0);
  TEST_ASSERT(ec_group_test_servo_pulse_us() == 1100U);
  ec_diag_process_line("STEP X");
  ec_diag_process_line("MOTION ARM");
  ec_diag_process_line("SERVO ARM");
  ec_diag_process_line("SERVO STOP");
  TEST_ASSERT(ec_group_test_mode() == EC_GROUP_TEST_SETTLING);
  ec_diag_process_line("GROUP STOP");
  TEST_ASSERT(ec_group_test_mode() == EC_GROUP_TEST_IDLE);
  TEST_ASSERT(strstr(tx_log, "OK GROUP STOP") != NULL);

  ec_diag_process_line("MOTION ARM");
  ec_diag_process_line("STEP X");
  ec_diag_process_line("GROUP ARM");
  TEST_ASSERT(strstr(tx_log, "ERR GROUP_INHIBITED_OR_BUSY") != NULL);
  ec_diag_process_line("STEP STOP");
  ec_diag_process_line("SERVO ARM");
  ec_diag_process_line("GROUP ARM");
  TEST_ASSERT(!ec_group_test_is_armed());
  ec_diag_process_line("STOP ALL");

  fake_active_inputs = EC_INPUT_START;
  ec_diag_process_line("GROUP ARM");
  TEST_ASSERT(!ec_group_test_is_armed());
  fake_active_inputs = 0U;

  ec_diag_process_line("GROUP START XDIR0 YDIR0 MID");
  TEST_ASSERT(strstr(tx_log, "ERR BAD_COMMAND") != NULL);

  assert_group_command("GROUP START XDIR0 YDIR0 OPEN", EC_DIRECTION_0, EC_DIRECTION_0, 1100U);
  assert_group_command("GROUP START XDIR0 YDIR0 CLOSE", EC_DIRECTION_0, EC_DIRECTION_0, 1900U);
  assert_group_command("GROUP START XDIR0 YDIR1 OPEN", EC_DIRECTION_0, EC_DIRECTION_1, 1100U);
  assert_group_command("GROUP START XDIR0 YDIR1 CLOSE", EC_DIRECTION_0, EC_DIRECTION_1, 1900U);
  assert_group_command("GROUP START XDIR1 YDIR0 OPEN", EC_DIRECTION_1, EC_DIRECTION_0, 1100U);
  assert_group_command("GROUP START XDIR1 YDIR0 CLOSE", EC_DIRECTION_1, EC_DIRECTION_0, 1900U);
  assert_group_command("GROUP START XDIR1 YDIR1 OPEN", EC_DIRECTION_1, EC_DIRECTION_1, 1100U);
  assert_group_command("GROUP START XDIR1 YDIR1 CLOSE", EC_DIRECTION_1, EC_DIRECTION_1, 1900U);

  assert_servo_command("SERVO PB10 P1000", 1000U);
  assert_servo_command("SERVO PB10 P1100", 1100U);
  assert_servo_command("SERVO PB10 P1200", 1200U);
  assert_servo_command("SERVO PB10 P1300", 1300U);
  assert_servo_command("SERVO PB10 P1500", 1500U);
  assert_servo_command("SERVO PB10 P1700", 1700U);
  assert_servo_command("SERVO PB10 P1900", 1900U);
  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("SERVO PB10 P1400");
  TEST_ASSERT(strstr(tx_log, "ERR BAD_COMMAND") != NULL);

  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_on_rx_byte('S'); ec_diag_on_rx_byte('T'); ec_diag_on_rx_byte('A');
  ec_diag_on_rx_byte('T'); ec_diag_on_rx_byte('U'); ec_diag_on_rx_byte('S');
  ec_diag_on_rx_byte('\r'); ec_diag_poll();
  TEST_ASSERT(strstr(tx_log, "SAFE_LOCK=1") != NULL);

  ec_diag_process_line("SERVO ARM");
  ec_diag_process_line("SERVO PB10 P1500");
  TEST_ASSERT(ec_servo_test_is_running());
  tx_log[0] = '\0'; tx_used = 0U;
  for (unsigned i = 0U; i < 80U; ++i) ec_diag_on_rx_byte('A');
  ec_diag_on_rx_byte('\n'); ec_diag_poll();
  TEST_ASSERT(strstr(tx_log, "ERR LINE_TOO_LONG") != NULL);
  TEST_ASSERT(!ec_servo_test_is_running());

  ec_diag_process_line("GROUP ARM");
  ec_diag_process_line("GROUP START XDIR0 YDIR1 CLOSE");
  TEST_ASSERT(ec_group_test_is_active());
  tx_log[0] = '\0'; tx_used = 0U;
  for (unsigned i = 0U; i < 80U; ++i) ec_diag_on_rx_byte('B');
  ec_diag_on_rx_byte('\n'); ec_diag_poll();
  TEST_ASSERT(strstr(tx_log, "ERR LINE_TOO_LONG") != NULL);
  TEST_ASSERT(!ec_group_test_is_active());

  tx_log[0] = '\0'; tx_used = 0U; ec_diag_init();
  ec_diag_process_line("MOTION ARM");
  ec_diag_on_rx_byte('S'); ec_diag_on_rx_byte('T'); ec_diag_on_rx_byte('E'); ec_diag_on_rx_byte('P'); ec_diag_on_rx_byte(' '); ec_diag_on_rx_byte('X'); ec_diag_on_rx_byte('\r');
  ec_diag_on_rx_byte('S'); ec_diag_on_rx_byte('T'); ec_diag_on_rx_byte('E'); ec_diag_on_rx_byte('P'); ec_diag_on_rx_byte(' '); ec_diag_on_rx_byte('S'); ec_diag_on_rx_byte('T'); ec_diag_on_rx_byte('O'); ec_diag_on_rx_byte('P'); ec_diag_on_rx_byte('\r');
  ec_diag_poll();
  TEST_ASSERT(strstr(tx_log, "OK STEP X") != NULL);
  TEST_ASSERT(strstr(tx_log, "OK STEP STOP") != NULL);
  TEST_ASSERT(ec_step_test_active_axis() == EC_AXIS_NONE);

  tx_log[0] = '\0'; tx_used = 0U; ec_diag_init();
  ec_diag_process_line("SERVO ARM");
  ec_diag_process_line("SERVO PB10 P1500");
  TEST_ASSERT(ec_servo_test_is_running());
  tx_log[0] = '\0'; tx_used = 0U;
  for (unsigned i = 0U; i < 128U; ++i) ec_diag_on_rx_byte('A');
  ec_diag_poll();
  TEST_ASSERT(strstr(tx_log, "ERR RX_OVERFLOW") != NULL);
  TEST_ASSERT(!ec_servo_test_is_running());
  ec_diag_on_rx_byte('S'); ec_diag_on_rx_byte('T'); ec_diag_on_rx_byte('A');
  ec_diag_on_rx_byte('T'); ec_diag_on_rx_byte('U'); ec_diag_on_rx_byte('S');
  ec_diag_on_rx_byte('\r'); ec_diag_poll();
  TEST_ASSERT(strstr(tx_log, "SAFE_LOCK=1") != NULL);

  ec_diag_process_line("GROUP ARM");
  ec_diag_process_line("GROUP START XDIR1 YDIR1 OPEN");
  TEST_ASSERT(ec_group_test_is_active());
  tx_log[0] = '\0'; tx_used = 0U; ec_diag_init();
  for (unsigned i = 0U; i < 128U; ++i) ec_diag_on_rx_byte('C');
  ec_diag_poll();
  TEST_ASSERT(strstr(tx_log, "ERR RX_OVERFLOW") != NULL);
  TEST_ASSERT(!ec_group_test_is_active());

  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("PING");
  TEST_ASSERT(strstr(tx_log, "OK PONG") != NULL);

  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("BARRIER P1500");
  TEST_ASSERT(strstr(tx_log, "ERR BARRIER_NOT_ARMED") != NULL);
  ec_diag_process_line("BARRIER ARM");
  TEST_ASSERT(ec_barrier_test_is_armed());
  TEST_ASSERT(strstr(tx_log, "OK BARRIER ARMED 10S") != NULL);
  ec_diag_process_line("STEP X");
  TEST_ASSERT(strstr(tx_log, "ERR TEST_BUSY") != NULL);
  ec_diag_process_line("BARRIER P1500");
  TEST_ASSERT(ec_barrier_test_is_active());
  TEST_ASSERT(ec_barrier_test_active_mask() == UINT8_C(0x0F));
  TEST_ASSERT(ec_barrier_test_pulse_us() == 1500U);
  ec_diag_process_line("BARRIER STOP");
  TEST_ASSERT(!ec_barrier_test_is_active());
  TEST_ASSERT(strstr(tx_log, "OK BARRIER STOP") != NULL);

  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("BARRIER ARM");
  ec_diag_process_line("BARRIER 3 P1300");
  TEST_ASSERT(ec_barrier_test_is_active());
  TEST_ASSERT(ec_barrier_test_active_mask() == UINT8_C(0x04));
  TEST_ASSERT(ec_barrier_test_pulse_us() == 1300U);
  ec_diag_process_line("BARRIER STOP");

  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("BARRIER ARM");
  ec_diag_process_line("BARRIER COLLECT P1000");
  TEST_ASSERT(ec_barrier_test_is_active());
  TEST_ASSERT(ec_barrier_test_pulse_us() == 1000U);
  ec_diag_process_line("STOP ALL");
  TEST_ASSERT(!ec_barrier_test_is_active());

  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("BARRIER ARM");
  ec_diag_process_line("BARRIER AVOID P1900");
  TEST_ASSERT(ec_barrier_test_is_active());
  ec_diag_process_line("BARRIER STOP");

  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_process_line("BARRIER P400");
  TEST_ASSERT(strstr(tx_log, "ERR BAD_COMMAND") != NULL);
  ec_diag_process_line("STATUS");
  TEST_ASSERT(strstr(tx_log, "BARRIER_TEST=1") != NULL);

  tx_log[0] = '\0'; tx_used = 0U; ec_diag_init();
  ec_diag_tick(999U); TEST_ASSERT(tx_used == 0U);
  ec_diag_tick(1000U); TEST_ASSERT(strstr(tx_log, "SAFE_LOCK=1") != NULL);
}
