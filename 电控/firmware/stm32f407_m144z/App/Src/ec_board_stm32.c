#include "ec_board_stm32.h"

#include "ec_app.h"
#include "ec_barrier_test.h"
#include "ec_board.h"
#include "ec_diag.h"
#include "ec_group_test.h"
#include "ec_inputs.h"
#include "ec_safety_adapter.h"
#include "ec_servo_test.h"
#include "ec_step_test.h"

#include <stddef.h>
#include <string.h>

extern TIM_HandleTypeDef htim2;
extern TIM_HandleTypeDef htim3;
extern TIM_HandleTypeDef htim4;
extern TIM_HandleTypeDef htim8;
extern TIM_HandleTypeDef htim10;
extern TIM_HandleTypeDef htim11;
extern UART_HandleTypeDef huart3;

/* Step-timer counting clock = 100 kHz (HSI 16 MHz / (PSC+1=160), PSC=159).
 * Coupled to main.c SystemClock_Config + MX_TIMx_Init: if the system clock or
 * PSC changes, this value must be updated or the step frequency shifts. */
#define EC_STEP_TIMER_HZ UINT32_C(100000)

static ec_input_filter_t input_filter;
static ec_input_snapshot_t input_snapshot;
static uint8_t input_filter_initialized;
/* UART RX single-byte staging buffer. Written by HAL's UART_Receive_IT and
 * read back in ec_board_uart_rx_callback (via HAL_UART_RxCpltCallback), both
 * in the UART ISR context; the main loop never touches it. No ISR<->main-loop
 * race, so unlike counted_axis below it does not need volatile. */
static uint8_t uart_main_rx_byte;
/* Shared between the TIM update ISR (ec_step_port_on_timer_period /
 * ec_motion_test_on_counted_done) and the main-loop poll: must be volatile
 * so -O2/-O3 does not cache them in registers and freeze STEP_REMAIN / DONE. */
static volatile ec_axis_t counted_axis;
static volatile uint32_t counted_steps_remaining;
static volatile uint32_t counted_steps_total;
static volatile uint8_t counted_active;

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
    default: return NULL;
    }
}

static void stop_counted_timer(void)
{
    TIM_HandleTypeDef *timer;

    if (counted_active == 0U) return;
    timer = step_timer_for_axis(counted_axis);
    if (timer != NULL) {
        (void)HAL_TIM_PWM_Stop(timer, TIM_CHANNEL_1);
        __HAL_TIM_DISABLE_IT(timer, TIM_IT_CC1);
        __HAL_TIM_DISABLE_IT(timer, TIM_IT_UPDATE);
    }
    counted_active = 0U;
    counted_steps_remaining = 0U;
    counted_steps_total = 0U;
}

void ec_board_enter_safe_state(void)
{
    ec_step_port_stop_all();

    ec_barrier_port_stop();
    ec_servo_port_stop();
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
    uint32_t period;

    if ((frequency_hz != UINT32_C(10)) &&
        (frequency_hz != UINT32_C(100))) return false;
    timer = step_timer_for_axis(axis);
    if (timer == NULL) return false;

    /* TIM4/TIM8/TIM9 use a 100 kHz timer clock (PSC=159). */
    period = (EC_STEP_TIMER_HZ / frequency_hz) - 1U;
    __HAL_TIM_SET_AUTORELOAD(timer, period);
    __HAL_TIM_SET_COUNTER(timer, 0U);
    __HAL_TIM_SET_COMPARE(timer, TIM_CHANNEL_1, (period + 1U) / 2U);
    return HAL_TIM_PWM_Start(timer, TIM_CHANNEL_1) == HAL_OK;
}

bool ec_step_port_start_counted(ec_axis_t axis, uint32_t frequency_hz,
                                uint32_t steps)
{
    TIM_HandleTypeDef *timer;
    uint32_t period;

    /* Re-entry guard: refuse to arm a counted run while one is already
     * active, so a stray second start can't overwrite the shared
     * counted_axis/counted_steps_* state (P2-5). */
    if (counted_active != 0U) return false;
    if ((axis != EC_AXIS_X) && (axis != EC_AXIS_Y)) {
        return false;
    }
    if (steps == 0U) return false;
    if ((frequency_hz < EC_STEP_MIN_HZ) ||
        (frequency_hz > EC_STEP_MAX_HZ)) {
        return false;
    }
    timer = step_timer_for_axis(axis);
    if (timer == NULL) return false;

    period = (EC_STEP_TIMER_HZ / frequency_hz) - 1U;
    __HAL_TIM_SET_AUTORELOAD(timer, period);
    __HAL_TIM_SET_COUNTER(timer, 0U);
    __HAL_TIM_SET_COMPARE(timer, TIM_CHANNEL_1, (period + 1U) / 2U);
    __HAL_TIM_CLEAR_FLAG(timer, TIM_FLAG_UPDATE);

    counted_axis = axis;
    counted_steps_remaining = steps;
    counted_steps_total = steps;
    counted_active = 1U;

    if (HAL_TIM_PWM_Start(timer, TIM_CHANNEL_1) != HAL_OK) {
        counted_active = 0U;
        counted_steps_remaining = 0U;
        counted_steps_total = 0U;
        ec_step_port_stop_all();
        return false;
    }
    __HAL_TIM_ENABLE_IT(timer, TIM_IT_UPDATE);
    return true;
}

void ec_step_port_on_timer_period(TIM_HandleTypeDef *htim)
{
    TIM_HandleTypeDef *timer;

    if (counted_active == 0U) return;
    timer = step_timer_for_axis(counted_axis);
    if ((timer == NULL) || (htim == NULL) ||
        (htim->Instance != timer->Instance)) {
        return;
    }

    /* Fast-path safety inhibit (P2-3): read the raw limit/ESTOP GPIO pins
     * directly (no debounce) so a triggered limit/ESTOP halts within one
     * step tick instead of waiting for the main-loop poll (~50ms worst).
     * Same active-low polarity as ec_inputs_active_mask. */
    if (ec_motion_inhibit_from_raw(read_raw_inputs())) {
        stop_counted_timer();
        ec_step_port_disable_all();
        ec_motion_test_on_aborted();
        return;
    }

    if (counted_steps_remaining > 0U) {
        counted_steps_remaining--;
    }
    if (counted_steps_remaining == 0U) {
        /* Runs in the TIM update ISR. HAL_TIM_PWM_Stop inside
         * stop_counted_timer may return HAL_BUSY if the main loop holds the
         * lock, but the safety fallback is ec_step_port_disable_all (direct
         * GPIO write) right after, which does not depend on the HAL lock. */
        stop_counted_timer();
        ec_step_port_disable_all();
        ec_motion_test_on_counted_done();
    }
}

bool ec_servo_port_start(uint16_t pulse_us)
{
    if ((pulse_us == 0U) || (pulse_us > htim2.Init.Period)) return false;

    __HAL_TIM_SET_COUNTER(&htim2, 0U);
    __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_3, pulse_us);
    return HAL_TIM_PWM_Start(&htim2, TIM_CHANNEL_3) == HAL_OK;
}

static bool barrier_start_channel(TIM_HandleTypeDef *timer,
                                  uint32_t channel, uint16_t pulse_us)
{
    if ((pulse_us == 0U) || (pulse_us > htim3.Init.Period)) return false;

    __HAL_TIM_SET_COUNTER(timer, 0U);
    __HAL_TIM_SET_COMPARE(timer, channel, pulse_us);
    return HAL_TIM_PWM_Start(timer, channel) == HAL_OK;
}

bool ec_barrier_port_start_mask(uint8_t channel_mask, uint16_t pulse_us)
{
    bool ok = true;

    if ((channel_mask == 0U) || (pulse_us == 0U) ||
        (pulse_us > htim3.Init.Period)) {
        return false;
    }

    ec_barrier_port_stop();
    if (((channel_mask & UINT8_C(0x01)) != 0U) &&
        !barrier_start_channel(&htim3, TIM_CHANNEL_3, pulse_us)) {
        ok = false;
    }
    if (((channel_mask & UINT8_C(0x02)) != 0U) &&
        !barrier_start_channel(&htim3, TIM_CHANNEL_4, pulse_us)) {
        ok = false;
    }
    if (((channel_mask & UINT8_C(0x04)) != 0U) &&
        !barrier_start_channel(&htim10, TIM_CHANNEL_1, pulse_us)) {
        ok = false;
    }
    if (((channel_mask & UINT8_C(0x08)) != 0U) &&
        !barrier_start_channel(&htim11, TIM_CHANNEL_1, pulse_us)) {
        ok = false;
    }

    if (!ok) {
        ec_barrier_port_stop();
        return false;
    }
    return true;
}

void ec_barrier_port_stop(void)
{
    (void)HAL_TIM_PWM_Stop(&htim3, TIM_CHANNEL_3);
    (void)HAL_TIM_PWM_Stop(&htim3, TIM_CHANNEL_4);
    (void)HAL_TIM_PWM_Stop(&htim10, TIM_CHANNEL_1);
    (void)HAL_TIM_PWM_Stop(&htim11, TIM_CHANNEL_1);
    __HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_3, 0U);
    __HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_4, 0U);
    __HAL_TIM_SET_COMPARE(&htim10, TIM_CHANNEL_1, 0U);
    __HAL_TIM_SET_COMPARE(&htim11, TIM_CHANNEL_1, 0U);
}

uint32_t ec_barrier_port_now_ms(void)
{
    return HAL_GetTick();
}

void ec_servo_port_stop(void)
{
    (void)HAL_TIM_PWM_Stop(&htim2, TIM_CHANNEL_3);
    __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_3, 0U);
}

/* Z-axis lift servo: TIM2_CH4 = PB11, the former WRIST_PWM channel. Shares
 * TIM2's 50 Hz servo period with the gripper (TIM2_CH3). */
bool ec_servo_port_start_z(uint16_t pulse_us)
{
    if ((pulse_us == 0U) || (pulse_us > htim2.Init.Period)) return false;

    __HAL_TIM_SET_COUNTER(&htim2, 0U);
    __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_4, pulse_us);
    return HAL_TIM_PWM_Start(&htim2, TIM_CHANNEL_4) == HAL_OK;
}

void ec_servo_port_stop_z(void)
{
    (void)HAL_TIM_PWM_Stop(&htim2, TIM_CHANNEL_4);
    __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_4, 0U);
}

uint32_t ec_servo_port_now_ms(void)
{
    return HAL_GetTick();
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
    default:
        return false;
    }
}

void ec_step_port_stop_all(void)
{
    stop_counted_timer();
    (void)HAL_TIM_PWM_Stop(&htim8, TIM_CHANNEL_1);
    (void)HAL_TIM_PWM_Stop(&htim4, TIM_CHANNEL_1);
}

void ec_step_port_disable_all(void)
{
    HAL_GPIO_WritePin(ENABLE_X_GPIO_Port, ENABLE_X_Pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(ENABLE_Y_GPIO_Port, ENABLE_Y_Pin, GPIO_PIN_SET);
}

uint32_t ec_step_port_now_ms(void)
{
    return HAL_GetTick();
}

uint32_t ec_step_port_counted_remaining(void)
{
    return (counted_active != 0U) ? counted_steps_remaining : 0U;
}

uint32_t ec_step_port_counted_target(void)
{
    return (counted_active != 0U) ? counted_steps_total : 0U;
}

bool ec_group_port_set_direction(ec_axis_t axis, ec_direction_t direction)
{
    return ec_step_port_set_direction(axis, direction);
}

bool ec_group_port_enable_xy(void)
{
    ec_step_port_disable_all();
    HAL_GPIO_WritePin(ENABLE_X_GPIO_Port, ENABLE_X_Pin, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(ENABLE_Y_GPIO_Port, ENABLE_Y_Pin, GPIO_PIN_RESET);
    return true;
}

bool ec_group_port_start_step(ec_axis_t axis, uint32_t frequency_hz)
{
    return ec_step_port_start(axis, frequency_hz);
}

bool ec_group_port_start_servo(uint16_t pulse_us)
{
    return ec_servo_port_start(pulse_us);
}

void ec_group_port_stop_all(void)
{
    ec_step_port_stop_all();
    ec_servo_port_stop();
    ec_step_port_disable_all();
}

uint32_t ec_group_port_now_ms(void)
{
    return HAL_GetTick();
}

void ec_safety_port_stop_all(void)
{
    ec_step_port_stop_all();
    ec_servo_port_stop();
    ec_barrier_port_stop();
}

void ec_safety_port_disable_drivers(void)
{
    ec_step_port_disable_all();
}

void ec_safety_port_inhibit_power(void)
{
    /* ESTOP_FB is feedback only; dangerous power is cut by external hardware. */
    ec_servo_port_stop();
    ec_barrier_port_stop();
    ec_step_port_disable_all();
}

void ec_diag_port_write(const char *text)
{
    size_t length = strlen(text);
    uint32_t timeout_ms;

    if (length > UINT16_MAX) return;
    /* 115200 8N1 -> 11520 bytes/s. Allow 2x the send time + 10 ms floor so
     * STATUS/HELP (~350 B) are not truncated by a fixed 20 ms timeout. */
    timeout_ms = (uint32_t)((length * 2000UL) / 11520UL) + 10UL;
    (void)HAL_UART_Transmit(&huart3, (uint8_t *)text, (uint16_t)length,
                            timeout_ms);
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
