#include "ec_diag.h"
#include "ec_step_test.h"
#include "test_support.h"
#include <string.h>
static char tx_log[2048]; static size_t tx_used;
void ec_diag_port_write(const char *text) { size_t length = strlen(text); TEST_ASSERT(tx_used + length < sizeof(tx_log)); memcpy(&tx_log[tx_used], text, length + 1U); tx_used += length; }
ec_input_snapshot_t ec_board_read_inputs(void) { ec_input_snapshot_t s = { EC_INPUT_ALL_MASK, EC_INPUT_ALL_MASK, 0U }; return s; }
void test_diag(void) {
  tx_log[0] = '\0'; tx_used = 0U; ec_step_test_init(); ec_diag_init();
  ec_diag_process_line("STEP X"); TEST_ASSERT(ec_step_test_active_axis() == EC_AXIS_X);
  ec_diag_process_line("STEP STOP"); TEST_ASSERT(ec_step_test_active_axis() == EC_AXIS_NONE);
  ec_diag_process_line("STEP X 999"); TEST_ASSERT(ec_step_test_active_axis() == EC_AXIS_NONE); TEST_ASSERT(strstr(tx_log, "ERR BAD_COMMAND") != NULL);
  ec_diag_process_line("INPUTS"); TEST_ASSERT(strstr(tx_log, "INPUTS RAW=01FF STABLE=01FF ACTIVE=0000") != NULL);
  ec_diag_process_line("STATUS"); TEST_ASSERT(strstr(tx_log, "SAFE_LOCK=1") != NULL);
  ec_diag_process_line("MOVE X DIR0"); TEST_ASSERT(strstr(tx_log, "ERR MOTION_NOT_ARMED_OR_INHIBITED") != NULL);
  ec_diag_process_line("MOTION ARM"); TEST_ASSERT(ec_motion_test_is_armed());
  ec_diag_process_line("MOVE X DIR0"); TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_MOTION_ARMING);
  ec_diag_process_line("STEP STOP"); TEST_ASSERT(ec_step_test_mode() == EC_STEP_TEST_IDLE);

  tx_log[0] = '\0'; tx_used = 0U;
  ec_diag_on_rx_byte('S'); ec_diag_on_rx_byte('T'); ec_diag_on_rx_byte('A');
  ec_diag_on_rx_byte('T'); ec_diag_on_rx_byte('U'); ec_diag_on_rx_byte('S');
  ec_diag_on_rx_byte('\r'); ec_diag_poll();
  TEST_ASSERT(strstr(tx_log, "SAFE_LOCK=1") != NULL);

  tx_log[0] = '\0'; tx_used = 0U;
  for (unsigned i = 0U; i < 80U; ++i) ec_diag_on_rx_byte('A');
  ec_diag_on_rx_byte('\n'); ec_diag_poll();
  TEST_ASSERT(strstr(tx_log, "ERR LINE_TOO_LONG") != NULL);

  tx_log[0] = '\0'; tx_used = 0U; ec_diag_init();
  ec_diag_on_rx_byte('S'); ec_diag_on_rx_byte('T'); ec_diag_on_rx_byte('E'); ec_diag_on_rx_byte('P'); ec_diag_on_rx_byte(' '); ec_diag_on_rx_byte('X'); ec_diag_on_rx_byte('\r');
  ec_diag_on_rx_byte('S'); ec_diag_on_rx_byte('T'); ec_diag_on_rx_byte('E'); ec_diag_on_rx_byte('P'); ec_diag_on_rx_byte(' '); ec_diag_on_rx_byte('S'); ec_diag_on_rx_byte('T'); ec_diag_on_rx_byte('O'); ec_diag_on_rx_byte('P'); ec_diag_on_rx_byte('\r');
  ec_diag_poll();
  TEST_ASSERT(strstr(tx_log, "OK STEP X") != NULL);
  TEST_ASSERT(strstr(tx_log, "OK STEP STOP") != NULL);
  TEST_ASSERT(ec_step_test_active_axis() == EC_AXIS_NONE);

  tx_log[0] = '\0'; tx_used = 0U; ec_diag_init();
  for (unsigned i = 0U; i < 128U; ++i) ec_diag_on_rx_byte('A');
  ec_diag_poll();
  TEST_ASSERT(strstr(tx_log, "ERR RX_OVERFLOW") != NULL);
  ec_diag_on_rx_byte('S'); ec_diag_on_rx_byte('T'); ec_diag_on_rx_byte('A');
  ec_diag_on_rx_byte('T'); ec_diag_on_rx_byte('U'); ec_diag_on_rx_byte('S');
  ec_diag_on_rx_byte('\r'); ec_diag_poll();
  TEST_ASSERT(strstr(tx_log, "SAFE_LOCK=1") != NULL);

  tx_log[0] = '\0'; tx_used = 0U; ec_diag_init();
  ec_diag_tick(999U); TEST_ASSERT(tx_used == 0U);
  ec_diag_tick(1000U); TEST_ASSERT(strstr(tx_log, "SAFE_LOCK=1") != NULL);
}
