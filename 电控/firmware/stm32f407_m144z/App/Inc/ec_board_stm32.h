#ifndef EC_BOARD_STM32_H
#define EC_BOARD_STM32_H

#include "main.h"

void ec_board_uart_rx_callback(UART_HandleTypeDef *huart);
void ec_step_port_on_timer_period(TIM_HandleTypeDef *htim);

#endif
