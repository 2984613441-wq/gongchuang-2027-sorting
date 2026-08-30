#include "ec_app.h"
#include "ec_axis_driver.h"
#include "ec_inputs.h"
#include "ec_motion_plan.h"
#include "ec_protocol.h"
#include "test_support.h"

#include <stddef.h>

static unsigned safe_state_calls;
static unsigned input_poll_calls;
static unsigned uart_start_calls;
static unsigned uart_tx_calls;

/* --- board doubles --- */
void ec_board_enter_safe_state(void) { safe_state_calls++; }
void ec_board_poll_inputs(uint32_t now_ms) { (void)now_ms; input_poll_calls++; }
void ec_board_uart_start_rx(void) { uart_start_calls++; }
void ec_board_uart_transmit(const uint8_t *data, size_t length)
{
    (void)data;
    (void)length;
    uart_tx_calls++;
}

/* P0-FIX (ec_board.h): UART RX ring-buffer doubles. The tests feed frames
 * straight into ec_app_on_uart_rx_byte(), so the ring is always empty. */
bool ec_board_uart_rx_available(void) { return false; }
uint8_t ec_board_uart_rx_read(void) { return 0U; }

/* Active-input mask, shared with test_diag.c's ec_board_read_inputs double. */
extern uint16_t fake_active_inputs;

/* --- axis_driver doubles --- */
static ec_axis_state_t fake_axis_state;
static ec_axis_result_t fake_axis_result;

ec_axis_result_t ec_axis_driver_start_pick_place(const ec_axis_pick_place_t *p)
{
    (void)p;
    fake_axis_state = EC_AXIS_STATE_MOVING;
    fake_axis_result = EC_AXIS_RESULT_OK;
    return EC_AXIS_RESULT_OK;
}

ec_axis_result_t ec_axis_driver_poll(uint32_t now_ms, uint16_t active_inputs)
{
    (void)now_ms;
    (void)active_inputs;
    return fake_axis_result;
}

/* P0-FIX (ec_safety_adapter.c): SAFE_LOCK -> STOP_ALL calls
 * ec_axis_driver_stop(). Mirror the production driver's reset. */
void ec_axis_driver_stop(void)
{
    fake_axis_state = EC_AXIS_STATE_IDLE;
    fake_axis_result = EC_AXIS_RESULT_OK;
}

ec_axis_state_t ec_axis_driver_state(void) { return fake_axis_state; }
ec_axis_result_t ec_axis_driver_result(void) { return fake_axis_result; }

/* --- motion_plan double --- */
static int16_t fake_plan_x;
static int16_t fake_plan_y;
static unsigned fake_plan_calls;

bool ec_motion_plan_build(ec_axis_pick_place_t *out, int16_t x_mm10, int16_t y_mm10)
{
    (void)out;
    fake_plan_x = x_mm10;
    fake_plan_y = y_mm10;
    ++fake_plan_calls;
    return true;
}

/* Feed one well-formed ITEM_TASK frame byte-by-byte through the UART router. */
static void feed_item_task(void)
{
    ec_proto_item_task_t item;
    ec_proto_frame_t frame;
    uint8_t payload[EC_PROTO_ITEM_TASK_PAYLOAD_LEN];
    uint8_t buf[64];
    size_t len;
    size_t i;

    item.target_seq = 1U;
    item.class_id = 1U;
    item.image_id = 1U;
    item.x_mm10 = 100;
    item.y_mm10 = 100;
    item.grip_angle = EC_PROTO_ITEM_TASK_ANGLE_NONE;

    (void)ec_proto_encode_item_task(&item, payload, sizeof(payload));

    frame.version = EC_PROTO_VERSION;
    frame.sender = EC_DEVICE_PI;
    frame.receiver = EC_DEVICE_STM32;
    frame.task_id = 1U;   /* matches the first round_id */
    frame.frame_seq = 1U;
    frame.command = EC_CMD_ITEM_TASK;
    frame.payload = payload;
    frame.payload_len = EC_PROTO_ITEM_TASK_PAYLOAD_LEN;

    len = ec_proto_encode(&frame, buf, sizeof(buf));
    TEST_ASSERT(len != 0U);
    for (i = 0U; i < len; ++i) {
        ec_app_on_uart_rx_byte(buf[i]);
    }
}

/* P0-FIX boot chain (2026-08-28): POST / HOMING / BARRIER are no longer
 * auto-passed. The startup sequence (ec_startup_sequence.c) runs real checks,
 * and BARRIER has no feedback input mapped yet, so it can never verify on the
 * host -> WAIT_TASK is unreachable here (hardware-gated, see the note below).
 *
 * This test walks the REAL chain:
 *   START -> POWER_ON/POST (passes after 100 ms with all limits same-state)
 *   -> HOMING (passes after 500 ms debounce with X_HOME|Y_HOME active)
 *   -> PREPARE_BARRIER (blocks: no BARRIER_AVOIDANCE_VERIFIED event and no
 *      BARRIER_READY frame are emitted)
 *   -> barrier timeout (5 s) -> EMERGENCY_STOP -> FAULT_LOCK.
 *
 * NOTE: the old version of this test asserted the placeholder-immediate chain
 * "POST -> HOMING -> BARRIER straight to WAIT_TASK" and that ITEM_TASK then
 * started motion. That is exactly the behaviour the P0-FIX removed (any
 * ITEM_TASK could start motion without safety checks). The happy path
 * WAIT_TASK -> VALIDATE_TASK -> EXECUTING -> ... is covered at the gateway
 * layer in 电控/stm32_logic/tests/test_protocol_gateway.c; at the app layer it
 * needs a barrier-feedback input that is not mapped in the firmware yet. */
static void test_startup_sequence(void)
{
    safe_state_calls = input_poll_calls = uart_start_calls = uart_tx_calls = 0U;
    fake_active_inputs = 0U;
    ec_app_init();
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);

    /* FAULT_LOCK + START -> POWER_ON (POST begins). */
    fake_active_inputs = EC_INPUT_START;
    ec_app_poll(1U);
    TEST_ASSERT(ec_app_state() == EC_STATE_POWER_ON);
    fake_active_inputs = 0U;

    /* POST: all limit switches read the same state -> passes after 100 ms. */
    ec_app_poll(100U);
    TEST_ASSERT(ec_app_state() == EC_STATE_HOMING);

    /* HOMING: both home switches must stay active for the 500 ms debounce. */
    fake_active_inputs = EC_INPUT_X_HOME | EC_INPUT_Y_HOME;
    ec_app_poll(499U);
    TEST_ASSERT(ec_app_state() == EC_STATE_HOMING);
    ec_app_poll(500U);
    TEST_ASSERT(ec_app_state() == EC_STATE_PREPARE_BARRIER);
    fake_active_inputs = 0U;

    /* BARRIER: no feedback input is mapped (see ec_startup_sequence.c) -> the
     * machine must stay in PREPARE_BARRIER and never emit BARRIER_READY. */
    ec_app_poll(1000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_PREPARE_BARRIER);
    TEST_ASSERT(uart_tx_calls == 0U);   /* no BARRIER_READY yet */

    /* Barrier timeout (5 s) -> EMERGENCY_STOP -> FAULT_LOCK. */
    ec_app_poll(5000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
    TEST_ASSERT(uart_tx_calls == 0U);   /* never verified ready */
}

/* P0-FIX property: an ITEM_TASK arriving before the machine is verified ready
 * (WAIT_TASK) must NOT start motion. Outside WAIT_TASK the gateway rejects it
 * with a NACK; in FAULT_LOCK the frame is dropped outright. */
static void test_item_task_rejected_before_ready(void)
{
    safe_state_calls = input_poll_calls = uart_start_calls = uart_tx_calls = 0U;
    fake_active_inputs = 0U;
    ec_app_init();

    /* In FAULT_LOCK the frame is dropped: no NACK, no motion, state unchanged. */
    feed_item_task();
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
    TEST_ASSERT(uart_tx_calls == 0U);
    TEST_ASSERT(fake_plan_calls == 0U);
    TEST_ASSERT(fake_axis_state != EC_AXIS_STATE_MOVING);

    /* In POWER_ON (POST running) the gateway rejects with a NACK: the app must
     * stay in POST and must not arm motion or reach the motion planner. */
    fake_active_inputs = EC_INPUT_START;
    ec_app_poll(1U);
    TEST_ASSERT(ec_app_state() == EC_STATE_POWER_ON);
    fake_active_inputs = 0U;

    feed_item_task();
    TEST_ASSERT(ec_app_state() == EC_STATE_POWER_ON);
    TEST_ASSERT(uart_tx_calls >= 1U);   /* NACK(REJECT_NEW_TASK) emitted */
    TEST_ASSERT(fake_plan_calls == 0U);
    TEST_ASSERT(fake_axis_state != EC_AXIS_STATE_MOVING);
}

void test_app(void)
{
    safe_state_calls = input_poll_calls = uart_start_calls = uart_tx_calls = 0U;
    fake_axis_state = EC_AXIS_STATE_IDLE;
    fake_axis_result = EC_AXIS_RESULT_OK;
    fake_plan_x = 0;
    fake_plan_y = 0;
    fake_plan_calls = 0U;
    fake_active_inputs = 0U;

    ec_app_init();
    TEST_ASSERT(safe_state_calls == 1U);
    TEST_ASSERT(uart_start_calls == 1U);
    TEST_ASSERT(input_poll_calls == 1U);
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);

    ec_app_poll(9U);
    TEST_ASSERT(input_poll_calls == 1U);
    ec_app_poll(10U);
    TEST_ASSERT(input_poll_calls == 2U);
    ec_app_poll(19U);
    TEST_ASSERT(input_poll_calls == 2U);
    ec_app_poll(20U);
    TEST_ASSERT(input_poll_calls == 3U);

    test_startup_sequence();
    test_item_task_rejected_before_ready();
}
