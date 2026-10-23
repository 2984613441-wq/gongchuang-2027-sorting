/* Real board/group/step/profile code; HAL is a model, never drives hardware. */
#include "ec_board_stm32.h"
#include "ec_group_test.h"
#include "ec_step_test.h"
#include "test_support.h"
#include "ec_light_ws2812.h"
#include <string.h>

GPIO_TypeDef host_gpio[7];
TIM_HandleTypeDef htim2 = {.Instance = 2, .Init = {19999U}};
TIM_HandleTypeDef htim3 = {.Instance = 3, .Init = {19999U}};
TIM_HandleTypeDef htim4 = {.Instance = 4}, htim8 = {.Instance = 8};
TIM_HandleTypeDef htim9 = {.Instance = 9, .Init = {19999U}};
TIM_HandleTypeDef htim10 = {.Instance = 10}, htim11 = {.Instance = 11};
UART_HandleTypeDef huart2 = {2}, huart3 = {3};
static uint32_t now_ms, primask;
static unsigned starts, stops, fail_instance;
static bool x_running_when_y_started;

uint32_t HAL_GetTick(void) { return now_ms; }
uint32_t __get_PRIMASK(void) { return primask; }
void __disable_irq(void) { primask = 1U; }
void __enable_irq(void) { primask = 0U; }
GPIO_PinState HAL_GPIO_ReadPin(GPIO_TypeDef *p, uint16_t pin)
{ return (p->input & pin) ? GPIO_PIN_SET : GPIO_PIN_RESET; }
void HAL_GPIO_WritePin(GPIO_TypeDef *p, uint16_t pin, GPIO_PinState state)
{ if (state) p->output |= pin; else p->output &= (uint16_t)~pin; }
HAL_StatusTypeDef HAL_TIM_PWM_Start(TIM_HandleTypeDef *t, uint32_t channel)
{
    ++starts;
    if (t->Instance == fail_instance) return HAL_ERROR;
    if (t == &htim4) x_running_when_y_started = (htim8.running != 0U);
    t->running |= 1U << channel;
    return HAL_OK;
}
HAL_StatusTypeDef HAL_TIM_PWM_Stop(TIM_HandleTypeDef *t, uint32_t channel)
{ ++stops; t->running &= ~(1U << channel); return HAL_OK; }

/* GPIO alternate-function setup is modeled; unrelated services must not run. */
void HAL_GPIO_Init(GPIO_TypeDef *p, GPIO_InitTypeDef *config)
{ (void)p; (void)config; }
HAL_StatusTypeDef HAL_UART_Transmit(UART_HandleTypeDef *u, uint8_t *data,
                                   uint16_t length, uint32_t timeout)
{ (void)u; (void)data; (void)length; (void)timeout; TEST_ASSERT(false); return HAL_ERROR; }
HAL_StatusTypeDef HAL_UART_Receive_IT(UART_HandleTypeDef *u, uint8_t *data,
                                     uint16_t length)
{ (void)u; (void)data; (void)length; TEST_ASSERT(false); return HAL_ERROR; }
void ec_ws2812_off(void) { TEST_ASSERT(false); }
void ec_ws2812_white_on(void) { TEST_ASSERT(false); }

static void reset_fixture(void)
{
    unsigned i;
    ec_group_test_stop();
    ec_step_test_stop();
    ec_step_test_init();
    ec_group_test_init();
    for (i = 0; i < 7U; ++i) host_gpio[i].input = UINT16_MAX;
    now_ms = 100U;
    starts = stops = fail_instance = 0U;
    x_running_when_y_started = false;
}

static void test_group_overlap(void)
{
    unsigned starts_before;
    reset_fixture();
    TEST_ASSERT(ec_group_test_arm(0U, false, false));
    TEST_ASSERT(ec_group_test_start(EC_DIRECTION_0, EC_DIRECTION_0,
                                    1100U, 0U, false, false));
    TEST_ASSERT(starts == 0U);
    ec_group_test_poll(119U, 0U);
    TEST_ASSERT(starts == 0U);
    now_ms = 120U;
    ec_group_test_poll(now_ms, 0U);
    TEST_ASSERT(ec_group_test_mode() == EC_GROUP_TEST_RUNNING);
    TEST_ASSERT(starts == 3U && stops == 0U);
    TEST_ASSERT(x_running_when_y_started);
    TEST_ASSERT(htim8.running && htim4.running);
    TEST_ASSERT(htim8.arr == 999U && htim4.arr == 999U);
    TEST_ASSERT(htim2.compare[TIM_CHANNEL_3] == 1100U);
    TEST_ASSERT(ec_step_port_counted_remaining() == 0U);
    TEST_ASSERT(!ec_group_test_arm(0U, false, false));
    starts_before = starts;
    ec_group_test_poll(10119U, 0U);
    TEST_ASSERT(ec_group_test_is_active());
    ec_group_test_poll(10120U, 0U);
    TEST_ASSERT(!ec_group_test_is_active());
    TEST_ASSERT(!htim8.running && !htim4.running);
    TEST_ASSERT(starts == starts_before);
    puts("GROUP: overlapping X/Y PWM in one poll; 100Hz; servo=1100us; stop=10000ms; counted_remaining=0 while active (MODEL ONLY)");
}

static void test_group_failure(void)
{
    reset_fixture();
    fail_instance = 4U;
    TEST_ASSERT(ec_group_test_arm(0U, false, false));
    TEST_ASSERT(ec_group_test_start(EC_DIRECTION_0, EC_DIRECTION_0,
                                    1100U, 0U, false, false));
    now_ms = 120U;
    ec_group_test_poll(now_ms, 0U);
    TEST_ASSERT(!ec_group_test_is_active());
    TEST_ASSERT(!htim8.running && !htim4.running && !htim2.running);
    puts("GROUP: Y-start failure stops X/Y/servo (MODEL ONLY)");
}

static void test_requested_rates(bool expect_requested_rate)
{
    const uint32_t rates[] = {500U, 800U, 1000U, 1500U, 2000U};
    unsigned i;
    for (i = 0U; i < sizeof(rates) / sizeof(rates[0]); ++i) {
        uint32_t min_arr, ticks = 0U;
        uint64_t duration_us = 0U;
        reset_fixture();
        TEST_ASSERT(ec_motion_test_arm(0U));
        TEST_ASSERT(ec_motion_test_start_steps(EC_AXIS_X, EC_DIRECTION_0,
                                                3600U, rates[i], 0U));
        min_arr = htim8.arr;
        while (htim8.running != 0U) {
            duration_us += ((uint64_t)htim8.arr + 1U) * 10U;
            if (htim8.arr < min_arr) min_arr = htim8.arr;
            ec_step_port_on_timer_period(&htim8);
            TEST_ASSERT(++ticks <= 3600U);
        }
        TEST_ASSERT(ticks == 3600U);
        TEST_ASSERT(ec_motion_test_step_result() == EC_STEP_RESULT_DONE);
        printf("COUNTED: requested=%luHz peak=%luHz steps=%lu modeled_duration_us=%llu\n",
               (unsigned long)rates[i], (unsigned long)(100000U / (min_arr + 1U)),
               (unsigned long)ticks, (unsigned long long)duration_us);
        if (expect_requested_rate) {
            TEST_ASSERT(100000U / (min_arr + 1U) <= rates[i]);
        } else {
            TEST_ASSERT(min_arr == 19U); /* Current fixed 5000Hz profile. */
        }
    }
}

static void test_arm_aborts_motion(void)
{
    reset_fixture();
    TEST_ASSERT(ec_motion_test_arm(0U));
    TEST_ASSERT(ec_motion_test_start_steps(EC_AXIS_X, EC_DIRECTION_0,
                                            3600U, 500U, 0U));
    TEST_ASSERT(htim8.running != 0U);
    TEST_ASSERT(ec_motion_test_arm(0U));
    TEST_ASSERT(htim8.running == 0U);
    puts("MOTION ARM: re-arm aborts an active counted run (MODEL ONLY)");
}

int main(int argc, char **argv)
{
    bool red = argc == 2 && strcmp(argv[1], "--expect-requested-rate") == 0;
    test_group_overlap();
    test_group_failure();
    test_arm_aborts_motion();
    test_requested_rates(red);
    puts("ALL T7/T8 HOST PROBES PASSED (NOT HARDWARE VALIDATION)");
    return 0;
}



