#ifndef EC_APP_H
#define EC_APP_H

#include "ec_state_machine.h"

#include <stdint.h>

void ec_app_init(void);
void ec_app_poll(uint32_t now_ms);
void ec_app_on_uart_rx_byte(uint8_t byte);
ec_state_t ec_app_state(void);

#endif
