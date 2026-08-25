#include "ec_diag.h"
#include "ec_barrier_test.h"
#include "ec_group_test.h"
#include "ec_servo_test.h"
#include "ec_step_test.h"
#include "test_support.h"
#include <string.h>
static char tx_log[8192]; static size_t tx_used;
static uint16_t fake_active_inputs;
void ec_diag_port_write(const char *text) { size_t length = strlen(text); TEST_ASSERT(tx_used + length < sizeof(tx_log)); memcpy(&tx_log[tx_used], text, length + 1U); tx_used += length; }
ec_input_snapshot_t ec_board_read_inputs(void) { ec_input_snapshot_t s = { EC_INPUT_ALL_MASK, EC_INPUT_ALL_MASK, fake_active_inputs }; return s; }
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
  ec_diag_process_line("INPUTS"); TEST_ASSERT(strstr(tx_log, "INPUTS RAW=01FF STABLE=01FF ACTIVE=0000") != NULL);
  ec_diag_process_line("STATUS"); TEST_ASSERT(strstr(tx_log, "SAFE_LOCK=1") != NULL);
  TEST_ASSERT(strstr(tx_log, "GROUP_TEST=1 GROUP_ARMED=0 GROUP_ACTIVE=0") != NULL);
  TEST_ASSERT(strstr(tx_log, "STEP_RESULT=0") != NULL);
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
  TEST_ASSERT(ec_group_test_servo_pulse_us() == 1000U);
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

  assert_group_command("GROUP START XDIR0 YDIR0 OPEN", EC_DIRECTION_0, EC_DIRECTION_0, 1000U);
  assert_group_command("GROUP START XDIR0 YDIR0 CLOSE", EC_DIRECTION_0, EC_DIRECTION_0, 1900U);
  assert_group_command("GROUP START XDIR0 YDIR1 OPEN", EC_DIRECTION_0, EC_DIRECTION_1, 1000U);
  assert_group_command("GROUP START XDIR0 YDIR1 CLOSE", EC_DIRECTION_0, EC_DIRECTION_1, 1900U);
  assert_group_command("GROUP START XDIR1 YDIR0 OPEN", EC_DIRECTION_1, EC_DIRECTION_0, 1000U);
  assert_group_command("GROUP START XDIR1 YDIR0 CLOSE", EC_DIRECTION_1, EC_DIRECTION_0, 1900U);
  assert_group_command("GROUP START XDIR1 YDIR1 OPEN", EC_DIRECTION_1, EC_DIRECTION_1, 1000U);
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
