#ifndef EC_DIAG_H
#define EC_DIAG_H

#include "ec_inputs.h"

#include <stdint.h>

void ec_diag_init(void);
void ec_diag_process_line(const char *line);
void ec_diag_on_rx_byte(uint8_t byte);
void ec_diag_poll(void);
void ec_diag_tick(uint32_t now_ms);

void ec_diag_port_write(const char *text);
ec_input_snapshot_t ec_board_read_inputs(void);

#endif
