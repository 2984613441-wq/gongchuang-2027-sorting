#ifndef EC_BOARD_H
#define EC_BOARD_H

#include "ec_inputs.h"

#include <stdint.h>

void ec_board_enter_safe_state(void);
void ec_board_poll_inputs(uint32_t now_ms);
ec_input_snapshot_t ec_board_read_inputs(void);
void ec_board_uart_start_rx(void);

#endif
