#ifndef EC_BOARD_STM32_H
#define EC_BOARD_STM32_H

#include "main.h"

void ec_board_uart_rx_callback(UART_HandleTypeDef *huart);
/* Forwarded from HAL_UART_ErrorCallback (main.c). Re-arms RX after an
 * overrun/framing error; without it HAL leaves the RXNE interrupt disabled
 * and reception dies permanently (see ec_board_stm32.c). */
void ec_board_uart_error_callback(UART_HandleTypeDef *huart);
void ec_step_port_on_timer_period(TIM_HandleTypeDef *htim);

#endif
