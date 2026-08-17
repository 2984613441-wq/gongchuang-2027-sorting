#include "ec_board_stm32.h"

#include "ec_app.h"
#include "ec_board.h"
#include "ec_diag.h"
#include "ec_inputs.h"
#include "ec_safety_adapter.h"
#include "ec_step_test.h"

#include <stddef.h>
#include <string.h>

extern TIM_HandleTypeDef htim2;
extern TIM_HandleTypeDef htim3;
extern TIM_HandleTypeDef htim4;
extern TIM_HandleTypeDef htim8;
extern TIM_HandleTypeDef htim9;
extern TIM_HandleTypeDef htim10;
extern TIM_HandleTypeDef htim11;
extern UART_HandleTypeDef huart3;

static ec_input_filter_t input_filter;
static ec_input_snapshot_t input_snapshot;
static uint8_t input_filter_initialized;
static uint8_t uart_main_rx_byte;

static uint16_t read_raw_inputs(void)
{
    uint16_t raw = 0U;

#define EC_READ_HIGH(bit, name)                                               \
    do {                                                                      \
        if (HAL_GPIO_ReadPin(name##_GPIO_Port, name##_Pin) == GPIO_PIN_SET) { \
            raw |= (bit);                                                     \
        }                                                                     \
    } while (0)

    EC_READ_HIGH(EC_INPUT_X_HOME, X_HOME);
    EC_READ_HIGH(EC_INPUT_X_END, X_END);
    EC_READ_HIGH(EC_INPUT_Y_HOME, Y_HOME);
    EC_READ_HIGH(EC_INPUT_Y_END, Y_END);
    EC_READ_HIGH(EC_INPUT_Z_UP, Z_UP);
    EC_READ_HIGH(EC_INPUT_Z_DOWN, Z_DOWN);
    EC_READ_HIGH(EC_INPUT_ESTOP_FB, ESTOP_FB);
    EC_READ_HIGH(EC_INPUT_START, START_SIG);
    EC_READ_HIGH(EC_INPUT_MANUAL_RESET, MANUAL_RESET_SIG);

#undef EC_READ_HIGH
    return raw;
}

static TIM_HandleTypeDef *step_timer_for_axis(ec_axis_t axis)
{
    switch (axis) {
    case EC_AXIS_X: return &htim8;
    case EC_AXIS_Y: return &htim4;
    case EC_AXIS_Z: return &htim9;
    default: return NULL;
    }
}

void ec_board_enter_safe_state(void)
{
    ec_step_port_stop_all();

    (void)HAL_TIM_PWM_Stop(&htim3, TIM_CHANNEL_3);
    (void)HAL_TIM_PWM_Stop(&htim3, TIM_CHANNEL_4);
    (void)HAL_TIM_PWM_Stop(&htim10, TIM_CHANNEL_1);
    (void)HAL_TIM_PWM_Stop(&htim11, TIM_CHANNEL_1);
    (void)HAL_TIM_PWM_Stop(&htim2, TIM_CHANNEL_3);
    (void)HAL_TIM_PWM_Stop(&htim2, TIM_CHANNEL_4);

    ec_step_port_disable_all();
    HAL_GPIO_WritePin(LIGHT_EN_GPIO_Port, LIGHT_EN_Pin, GPIO_PIN_RESET);
}

void ec_board_poll_inputs(uint32_t now_ms)
{
    uint16_t raw = read_raw_inputs();
    if (input_filter_initialized == 0U) {
        ec_inputs_init(&input_filter, raw, now_ms);
        input_filter_initialized = 1U;
    } else {
        ec_inputs_update(&input_filter, raw, now_ms);
    }

    input_snapshot.raw_mask = raw;
    input_snapshot.stable_mask = ec_inputs_stable_mask(&input_filter);
    input_snapshot.active_mask = ec_inputs_active_mask(&input_filter);
}

ec_input_snapshot_t ec_board_read_inputs(void)
{
    return input_snapshot;
}

bool ec_step_port_start(ec_axis_t axis, uint32_t frequency_hz)
{
    TIM_HandleTypeDef *timer;

    if (frequency_hz != UINT32_C(10)) return false;
    timer = step_timer_for_axis(axis);
    if (timer == NULL) return false;

    __HAL_TIM_SET_COUNTER(timer, 0U);
    __HAL_TIM_SET_COMPARE(timer, TIM_CHANNEL_1,
                          (timer->Init.Period + 1U) / 2U);
    return HAL_TIM_PWM_Start(timer, TIM_CHANNEL_1) == HAL_OK;
}

bool ec_step_port_set_direction(ec_axis_t axis, ec_direction_t direction)
{
    GPIO_PinState state = (direction == EC_DIRECTION_1) ?
                          GPIO_PIN_SET : GPIO_PIN_RESET;

    switch (axis) {
    case EC_AXIS_X:
        HAL_GPIO_WritePin(DIR_X_GPIO_Port, DIR_X_Pin, state);
        return true;
    case EC_AXIS_Y:
        HAL_GPIO_WritePin(DIR_Y_GPIO_Port, DIR_Y_Pin, state);
        return true;
    case EC_AXIS_Z:
        HAL_GPIO_WritePin(DIR_Z_GPIO_Port, DIR_Z_Pin, state);
        return true;
    default:
        return false;
    }
}

bool ec_step_port_enable_axis(ec_axis_t axis)
{
    ec_step_port_disable_all();
    switch (axis) {
    case EC_AXIS_X:
        HAL_GPIO_WritePin(ENABLE_X_GPIO_Port, ENABLE_X_Pin, GPIO_PIN_RESET);
        return true;
    case EC_AXIS_Y:
        HAL_GPIO_WritePin(ENABLE_Y_GPIO_Port, ENABLE_Y_Pin, GPIO_PIN_RESET);
        return true;
    case EC_AXIS_Z:
        HAL_GPIO_WritePin(ENABLE_Z_GPIO_Port, ENABLE_Z_Pin, GPIO_PIN_RESET);
        return true;
    default:
        return false;
    }
}

void ec_step_port_stop_all(void)
{
    (void)HAL_TIM_PWM_Stop(&htim8, TIM_CHANNEL_1);
    (void)HAL_TIM_PWM_Stop(&htim4, TIM_CHANNEL_1);
    (void)HAL_TIM_PWM_Stop(&htim9, TIM_CHANNEL_1);
}

void ec_step_port_disable_all(void)
{
    HAL_GPIO_WritePin(ENABLE_X_GPIO_Port, ENABLE_X_Pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(ENABLE_Y_GPIO_Port, ENABLE_Y_Pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(ENABLE_Z_GPIO_Port, ENABLE_Z_Pin, GPIO_PIN_SET);
}

uint32_t ec_step_port_now_ms(void)
{
    return HAL_GetTick();
}

void ec_safety_port_stop_all(void)
{
    ec_step_port_stop_all();
}

void ec_safety_port_disable_drivers(void)
{
    ec_step_port_disable_all();
}

void ec_safety_port_inhibit_power(void)
{
    /* ESTOP_FB is feedback only; dangerous power is cut by external hardware. */
    ec_step_port_disable_all();
}

void ec_diag_port_write(const char *text)
{
    size_t length = strlen(text);
    if (length > UINT16_MAX) return;
    (void)HAL_UART_Transmit(&huart3, (uint8_t *)text, (uint16_t)length, 20U);
}

void ec_board_uart_start_rx(void)
{
    (void)HAL_UART_Receive_IT(&huart3, &uart_main_rx_byte, 1U);
}

void ec_board_uart_rx_callback(UART_HandleTypeDef *huart)
{
    if ((huart != NULL) && (huart->Instance == USART3)) {
        ec_app_on_uart_rx_byte(uart_main_rx_byte);
        (void)HAL_UART_Receive_IT(&huart3, &uart_main_rx_byte, 1U);
    }
}
