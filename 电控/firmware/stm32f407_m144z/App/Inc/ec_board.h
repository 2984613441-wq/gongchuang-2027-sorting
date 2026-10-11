#ifndef EC_BOARD_H
#define EC_BOARD_H

#include "ec_inputs.h"
#include "ec_bus_servo.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

void ec_board_enter_safe_state(void);
void ec_board_poll_inputs(uint32_t now_ms);
/* 2026-09-18 新增：补光灯直控（LIGHT_EN = PC0）。
 * 极性：低 = 关 —— 与 main.c 初始化、ec_board_enter_safe_state 的写法一致，
 * 也与 docs/reports/2026-08-16-g1-pcb-code-handoff.md:43「低（关）」一致。
 * 接法：PC0 -> 栅极电阻 -> 逻辑电平 MOSFET(AO3400) -> 灯；
 *       灯由外部 5V 模块供电，该模块 GND 必须与逻辑 GND 共地。
 * 这是台架调试入口，不参与协议。 */
void ec_board_light_set(bool on);

/* 2026-09-18 L4 批准：自适应夹爪总线舵机（HX-06L）发送端口。
 * USART3_TX 已由 PD8 迁至 PB10（见 stm32f4xx_hal_msp.c）；
 * 舵机信号线物理上即接在 PB10，接线未改。位置/时间越界返回 false。 */
bool ec_grip_port_move(uint16_t position, uint16_t time_ms);
ec_input_snapshot_t ec_board_read_inputs(void);
void ec_board_uart_start_rx(void);
/* TX path used by ec_app_flush_tx(). */
void ec_board_uart_transmit(const uint8_t *data, size_t length);
/* Polled RX path used by ec_app_poll().
 * 2026-09-18 RX-DEAF-FIX: the UART interrupt (ec_board_uart_rx_callback) now
 * ONLY stages each byte in a ring buffer; every byte of protocol processing
 * runs in the main loop. Previously the ISR ran the whole pipeline including a
 * blocking response transmit, with HAL_UART_Receive_IT re-armed only as the
 * last statement - an overrun was guaranteed, and HAL's UART_EndRxTransfer()
 * then left the RXNE interrupt disabled forever (no HAL_UART_ErrorCallback was
 * defined), so the board went permanently deaf.
 * The host tests replace both functions with their own doubles. */
#define EC_BOARD_RX_CAPACITY 256U
bool ec_board_uart_rx_available(void);
uint8_t ec_board_uart_rx_read(void);

#endif
