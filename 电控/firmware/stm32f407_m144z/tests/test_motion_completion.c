/* Real board-port ISR, executor, planner, app and gateway; only HAL is fake.
 * The model delivers TIM update callbacks at ARR-derived intervals and polls
 * the app every 1 ms. It does not model lost IRQs, pin waveforms or rotor motion.
 * Each invocation is a fresh process; all production statics boot normally. */
#include "ec_app.h"
#include "ec_axis_driver.h"
#include "ec_board_stm32.h"
#include "ec_board.h"
#include "ec_diag.h"
#include "ec_motion_plan.h"
#include "ec_protocol.h"
#include "ec_step_profile.h"
#include "test_support.h"
#include <string.h>

GPIO_TypeDef host_gpio[7];
TIM_HandleTypeDef htim2 = {.Instance = 2, .Init = {19999U}};
TIM_HandleTypeDef htim3 = {.Instance = 3, .Init = {19999U}};
TIM_HandleTypeDef htim4 = {.Instance = 4}, htim8 = {.Instance = 8};
TIM_HandleTypeDef htim10 = {.Instance = 10}, htim11 = {.Instance = 11};
UART_HandleTypeDef huart2 = {2}, huart3 = {3};
static uint64_t time_us;
static uint32_t primask;
static unsigned commands[256], sequence[32], sequence_len;
static unsigned move_count, update_count;
static bool suppress_irq, steal_final_completion;
static uint64_t last_update_us;
static uint64_t motion_origin_us;
static uint32_t previous_clock;
static bool trace;
static int16_t scenario_pick_x_mm10 = 342;
static int16_t scenario_pick_y_mm10 = 173;
static int16_t scenario_place_x_mm10 = 50;
static int16_t scenario_place_y_mm10 = 50;
static uint8_t scenario_target_seq = 1U;
static bool production_input;

uint32_t HAL_GetTick(void) { return (uint32_t)(time_us / 1000U); }
uint32_t __get_PRIMASK(void) { return primask; }
void __disable_irq(void) { primask = 1U; }
void __enable_irq(void) { primask = 0U; }
GPIO_PinState HAL_GPIO_ReadPin(GPIO_TypeDef *p, uint16_t pin)
{ return (p->input & pin) ? GPIO_PIN_SET : GPIO_PIN_RESET; }
void HAL_GPIO_WritePin(GPIO_TypeDef *p, uint16_t pin, GPIO_PinState state)
{ if (state) p->output |= pin; else p->output &= (uint16_t)~pin; }
void HAL_GPIO_Init(GPIO_TypeDef *p, GPIO_InitTypeDef *config)
{ (void)p; (void)config; }
HAL_StatusTypeDef HAL_TIM_PWM_Start(TIM_HandleTypeDef *t, uint32_t channel)
{
    t->running |= 1U << channel;
    t->next_us = time_us + ((uint64_t)t->arr + 1U) * 10U;
    if ((t == &htim8) || (t == &htim4)) {
        ++move_count;
        if (trace) printf("MOVE index=%u axis=%c target=%lu initial_arr=%lu t=%lu ms\n",
            move_count, t == &htim8 ? 'X' : 'Y',
            (unsigned long)ec_step_port_counted_target(), (unsigned long)t->arr,
            (unsigned long)((time_us - motion_origin_us) / 1000U));
    }
    return HAL_OK;
}
HAL_StatusTypeDef HAL_TIM_PWM_Stop(TIM_HandleTypeDef *t, uint32_t channel)
{ t->running &= ~(1U << channel); return HAL_OK; }
HAL_StatusTypeDef HAL_UART_Receive_IT(UART_HandleTypeDef *u, uint8_t *data,
                                     uint16_t length)
{ (void)u; (void)data; (void)length; return HAL_OK; }
HAL_StatusTypeDef HAL_UART_Transmit(UART_HandleTypeDef *u, uint8_t *data,
                                   uint16_t length, uint32_t timeout)
{
    ec_proto_frame_t f;
    (void)timeout;
    if ((u == &huart2) && ec_proto_decode(data, length, &f)) {
        unsigned i;
        ++commands[f.command];
        TEST_ASSERT(sequence_len < sizeof(sequence) / sizeof(sequence[0]));
        sequence[sequence_len++] = f.command;
        printf("TX t=%lu cmd=%02X seq=%u bytes=", (unsigned long)HAL_GetTick(),
               f.command, f.frame_seq);
        for (i = 0; i < length; ++i) printf("%02X%s", data[i], i+1 == length ? "" : " ");
        putchar('\n');
    }
    return HAL_OK;
}

static void advance_to(uint64_t end_us, bool poll_app)
{
    while (time_us < end_us) {
        TIM_HandleTypeDef *timers[] = {&htim8, &htim4};
        TIM_HandleTypeDef *next = NULL;
        uint64_t when = ((time_us / 1000U) + 1U) * 1000U;
        unsigned i;
        if (when > end_us) when = end_us;
        for (i = 0; i < 2; ++i) {
            TIM_HandleTypeDef *t = timers[i];
            if (!suppress_irq && (t->running & 1U) &&
                (t->interrupts & TIM_IT_UPDATE) && (t->next_us <= when)) {
                next = t;
                when = t->next_us;
            }
        }
        time_us = when;
        if (next != NULL) {
            ec_axis_t consumed;
            ec_step_port_on_timer_period(next);
            ++update_count;
            last_update_us = time_us;
            /* Fault injection only: consume the final latch before the app.
             * This is NOT a claim that any production consumer does this. */
            if (steal_final_completion && move_count == 6U &&
                !(next->running & 1U)) {
                TEST_ASSERT(ec_step_port_take_counted_completion(&consumed));
                puts("INJECTED: final latch consumed by test before executor");
            }
            next->next_us = time_us + ((uint64_t)next->arr + 1U) * 10U;
        }
        if (poll_app && (HAL_GetTick() != previous_clock)) {
            previous_clock = HAL_GetTick();
            ec_app_poll(previous_clock);
        }
    }
}

static void feed_item(void)
{
    ec_proto_item_task_t item = {0};
    ec_proto_frame_t frame = {0};
    uint8_t payload[EC_PROTO_ITEM_TASK_PAYLOAD_LEN], bytes[64];
    size_t len, i;
    item.target_seq = scenario_target_seq;
    item.class_id = item.image_id = 1U;
    item.x_mm10 = scenario_place_x_mm10;
    item.y_mm10 = scenario_place_y_mm10;
    item.pick_x_mm10 = scenario_pick_x_mm10;
    item.pick_y_mm10 = scenario_pick_y_mm10;
    item.grip_angle = EC_PROTO_ITEM_TASK_ANGLE_NONE;
    TEST_ASSERT(ec_proto_encode_item_task(&item, payload, sizeof(payload)));
    frame.version = EC_PROTO_VERSION;
    frame.sender = EC_DEVICE_PI;
    frame.receiver = EC_DEVICE_STM32;
    frame.task_id = frame.frame_seq = 1U;
    frame.command = EC_CMD_ITEM_TASK;
    frame.payload = payload;
    frame.payload_len = sizeof(payload);
    len = ec_proto_encode(&frame, bytes, sizeof(bytes));
    TEST_ASSERT(len != 0U);
    for (i = 0; i < len; ++i) ec_app_on_uart_rx_byte(bytes[i]);
}

static void print_budget(void)
{
    ec_axis_pick_place_t p;
    double profile = 0.0;
    unsigned i;
    TEST_ASSERT(ec_motion_plan_build(&p, scenario_pick_x_mm10,
        scenario_pick_y_mm10, scenario_place_x_mm10,
        scenario_place_y_mm10));
    if (production_input) {
        printf("INPUT home=(0,0) pick=(%d,%d) place=(%d,%d) mm10 target_seq=%u\n",
            scenario_pick_x_mm10, scenario_pick_y_mm10,
            scenario_place_x_mm10, scenario_place_y_mm10,
            scenario_target_seq);
    }
    for (i = 0; i < EC_AXIS_PICK_PLACE_STEP_COUNT; ++i) {
        if (p.step[i].kind == EC_AXIS_STEP_MOVE && p.step[i].steps) {
            ec_step_profile_t ramp;
            uint32_t j;
            uint64_t ticks = 0U;
            TEST_ASSERT(ec_step_profile_plan(&ramp, p.step[i].steps,
                200U, 2000U, 200U, 5000U, 5000U));
            for (j = 0; j < p.step[i].steps; ++j)
                ticks += ec_step_profile_reload_at(&ramp, j, 100000U) + 1U;
            profile += ticks / 100000.0;
            printf("PROGRAM step=%u kind=MOVE axis=%s direction=DIR%u steps=%lu servo_pulse_us=0\n",
                i, p.step[i].axis == EC_AXIS_X ? "X" : "Y",
                (unsigned)p.step[i].direction,
                (unsigned long)p.step[i].steps);
            printf("BUDGET step=%u profile_200_2000_200_hz=%.5f s peak_hz=%lu move_timeout_ms=%lu\n",
                i, ticks / 100000.0, (unsigned long)ramp.cruise_hz,
                (unsigned long)(p.step[i].steps * 2U + 1000U));
        } else if (p.step[i].servo_pulse_us) {
            profile += EC_AXIS_GRIPPER_SETTLE_MS / 1000.0;
            printf("PROGRAM step=%u kind=Z_SERVO axis=NONE direction=NA steps=0 servo_pulse_us=%u\n",
                i, (unsigned)p.step[i].servo_pulse_us);
            printf("BUDGET step=%u servo_settle=%.5f s move_timeout_ms=NA\n",
                i, EC_AXIS_GRIPPER_SETTLE_MS / 1000.0);
        }
    }
    printf("TOTAL source_profile_model=%.5f s\n", profile);

    if (production_input) {
        TEST_ASSERT(p.step[0].kind == EC_AXIS_STEP_MOVE &&
                    p.step[0].axis == EC_AXIS_X &&
                    p.step[0].direction == EC_DIRECTION_0 &&
                    p.step[0].steps == 1000U);
        TEST_ASSERT(p.step[1].kind == EC_AXIS_STEP_MOVE &&
                    p.step[1].axis == EC_AXIS_Y &&
                    p.step[1].direction == EC_DIRECTION_1 &&
                    p.step[1].steps == 432U);
        TEST_ASSERT(p.step[2].kind == EC_AXIS_STEP_Z_SERVO &&
                    p.step[2].servo_pulse_us == 1900U);
        TEST_ASSERT(p.step[3].kind == EC_AXIS_STEP_MOVE &&
                    p.step[3].axis == EC_AXIS_X &&
                    p.step[3].direction == EC_DIRECTION_1 &&
                    p.step[3].steps == 600U);
        TEST_ASSERT(p.step[4].kind == EC_AXIS_STEP_MOVE &&
                    p.step[4].axis == EC_AXIS_Y &&
                    p.step[4].direction == EC_DIRECTION_0 &&
                    p.step[4].steps == 32U);
        TEST_ASSERT(p.step[5].kind == EC_AXIS_STEP_Z_SERVO &&
                    p.step[5].servo_pulse_us == 1100U);
        TEST_ASSERT(p.step[6].kind == EC_AXIS_STEP_MOVE &&
                    p.step[6].axis == EC_AXIS_X &&
                    p.step[6].direction == EC_DIRECTION_1 &&
                    p.step[6].steps == 400U);
        TEST_ASSERT(p.step[7].kind == EC_AXIS_STEP_MOVE &&
                    p.step[7].axis == EC_AXIS_Y &&
                    p.step[7].direction == EC_DIRECTION_0 &&
                    p.step[7].steps == 400U);
        TEST_ASSERT(p.step[8].steps == 0U && p.step[8].servo_pulse_us == 0U);
    }
}

int main(int argc, char **argv)
{
    const char *scenario = argc > 1 ? argv[1] : "normal";
    unsigned i;
    if (strcmp(scenario, "production_input") == 0) {
        scenario_pick_x_mm10 = 125;
        scenario_pick_y_mm10 = 54;
        scenario_place_x_mm10 = 50;
        scenario_place_y_mm10 = 50;
        scenario_target_seq = 4U;
        production_input = true;
    }
    for (i = 0; i < 7; ++i) host_gpio[i].input = UINT16_MAX;
    ec_app_init();
    printf("HOST ONLY scenario=%s progress_macro=%u\n", scenario,
           (unsigned)EC_APP_PROGRESS_SOURCE_ENABLED);
    if (strcmp(scenario, "diag") == 0) {
        ec_axis_t axis = EC_AXIS_NONE;
        ec_diag_process_line("MOTION ARM");
        ec_diag_process_line("MOVE X DIR0 STEPS 400 HZ 500");
        TEST_ASSERT(ec_step_port_counted_target() == 400U);
        advance_to(1000000U, true);
        TEST_ASSERT(ec_motion_test_step_result() == EC_STEP_RESULT_DONE);
        TEST_ASSERT(update_count == 400U);
        TEST_ASSERT(ec_step_port_take_counted_completion(&axis));
        TEST_ASSERT(axis == EC_AXIS_X);
        TEST_ASSERT(!ec_step_port_take_counted_completion(&axis));
        printf("DIAG updates=%u last_update=%.5f s result=DONE latch=once axis=X\n",
               update_count, last_update_us / 1000000.0);
        return 0;
    }
    print_budget();
    advance_to(1000U, true); /* Publish actual safety inputs to the gateway. */
    feed_item(); /* Establish round, then let real POST/homing/barrier finish. */
    advance_to(700000U, true);
    TEST_ASSERT(ec_app_state() == EC_STATE_WAIT_TASK);
    trace = true;
    motion_origin_us = time_us;
    feed_item();
    TEST_ASSERT(ec_app_state() == EC_STATE_EXECUTING);
    TEST_ASSERT(commands[EC_CMD_ACK] == 1U);
    if (strcmp(scenario, "missing_irq") == 0) suppress_irq = true;
    if (strcmp(scenario, "missing_final_latch") == 0) steal_final_completion = true;
    while (time_us - motion_origin_us < 16000000U &&
           ec_app_state() != EC_STATE_FAULT_LOCK &&
           ec_app_state() != EC_STATE_WAIT_DISPLAY_ACK)
        advance_to(time_us + 1000U, true);
    printf("END elapsed=%lu ms state=%u axis_state=%u axis_result=%u progress=%lu updates=%u motion_done=%u item_result=%u\n",
        (unsigned long)((time_us - motion_origin_us) / 1000U), ec_app_state(),
        ec_axis_driver_state(), ec_axis_driver_result(),
        (unsigned long)ec_axis_driver_progress(), update_count,
        commands[EC_CMD_MOTION_DONE], commands[EC_CMD_ITEM_RESULT]);
    if (production_input) {
        TEST_ASSERT(ec_app_state() == EC_STATE_WAIT_DISPLAY_ACK);
        TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_DONE);
        TEST_ASSERT(ec_axis_driver_result() == EC_AXIS_RESULT_OK);
        TEST_ASSERT(ec_axis_driver_progress() == 8U);
        TEST_ASSERT(commands[EC_CMD_MOTION_DONE] == 1U);
        printf("PRODUCTION_INPUT_RESULT completed_steps=8 fault_step=NONE axis_result=EC_AXIS_RESULT_OK motion_done=1\n");
    }
    if (suppress_irq || steal_final_completion) {
        TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
        TEST_ASSERT(ec_axis_driver_result() == EC_AXIS_RESULT_TIMEOUT);
        TEST_ASSERT(commands[EC_CMD_MOTION_DONE] == 0U);
        TEST_ASSERT(commands[EC_CMD_ITEM_RESULT] == 0U);
    } else {
        TEST_ASSERT(ec_app_state() == EC_STATE_WAIT_DISPLAY_ACK);
        TEST_ASSERT(commands[EC_CMD_MOTION_DONE] == 1U);
        TEST_ASSERT(commands[EC_CMD_ITEM_RESULT] == 1U);
        TEST_ASSERT(sequence_len == 4U);
        TEST_ASSERT(sequence[2] == EC_CMD_MOTION_DONE && sequence[3] == EC_CMD_ITEM_RESULT);
        advance_to(motion_origin_us + 14999000U, true);
        TEST_ASSERT(ec_app_state() == EC_STATE_WAIT_DISPLAY_ACK);
        advance_to(motion_origin_us + 15000000U, true);
        TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
        puts("WATCHDOG no DISPLAY_ACK: WAIT_DISPLAY_ACK at 14999 ms, FAULT_LOCK at 15000 ms");
    }
    puts("PASS (host HAL model; no hardware claim)");
    return 0;
}
