#include "ec_app.h"
#include "ec_axis_driver.h"
#include "ec_inputs.h"
#include "ec_motion_plan.h"
#include "ec_protocol.h"
#include "ec_protocol_gateway.h"
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

/* --- rolling no-motion watchdog tests (design 2026-08-30 §3.4) ---
 *
 * These drive the REAL app chain (START -> POST -> HOMING -> barrier seam ->
 * WAIT_TASK -> ITEM_TASK -> EXECUTING) and control time through the
 * injectable HAL tick (test_set_tick) plus the now_ms passed to ec_app_poll.
 * The motion-start base is HAL_GetTick() read at START_MOTION, so every
 * watchdog test sets the tick before feed_item_task() and passes matching
 * now_ms values to the polls.
 */

/* Feed one DISPLAY_ACK frame (EC_CMD_DISPLAY_ACK, from PI) with the given
 * render result and display-content CRC. The frame-level CRC is always valid;
 * a caller who wants an invalid ACK corrupts render_result or display_crc32. */
static void feed_display_ack(uint32_t display_crc32, uint8_t render_result)
{
    ec_proto_display_ack_t ack;
    ec_proto_frame_t frame;
    uint8_t payload[EC_DISPLAY_ACK_PAYLOAD_LEN];
    uint8_t buf[64];
    size_t len;
    size_t i;

    ack.target_seq = 1U;               /* the item accepted in feed_item_task */
    ack.render_result = render_result;
    ack.display_crc32 = display_crc32;

    (void)ec_proto_encode_display_ack(&ack, payload, sizeof(payload));

    frame.version = EC_PROTO_VERSION;
    frame.sender = EC_DEVICE_PI;
    frame.receiver = EC_DEVICE_STM32;
    frame.task_id = 1U;                /* matches the current round */
    frame.frame_seq = 2U;
    frame.command = EC_CMD_DISPLAY_ACK;
    frame.payload = payload;
    frame.payload_len = EC_DISPLAY_ACK_PAYLOAD_LEN;

    len = ec_proto_encode(&frame, buf, sizeof(buf));
    TEST_ASSERT(len != 0U);
    for (i = 0U; i < len; ++i) {
        ec_app_on_uart_rx_byte(buf[i]);
    }
}

/* Valid display-content CRC for the item latched by feed_item_task after a
 * SUCCESS result was recorded (target_seq=1, class_id=1, image_id=1,
 * success_count=1, result=SUCCESS). */
static uint32_t valid_display_ack_crc(void)
{
    return ec_proto_display_content_crc32(1U, 1U, 1U, 1U, EC_RESULT_SUCCESS);
}

/* Boot the real chain to WAIT_TASK (barrier feedback is unmapped on the host,
 * so the EC_APP_TEST_HOOKS seam stands in for BARRIER_AVOIDANCE_VERIFIED),
 * then deliver the first ITEM_TASK. Returns with the machine in EXECUTING and
 * the rolling watchdog armed at motion_start_tick (HAL_GetTick read at
 * START_MOTION). */
static void start_motion_at(uint32_t motion_start_tick)
{
    fake_active_inputs = 0U;
    ec_app_init();
    /* The boot chain's POST/HOMING/BARRIER timers are measured from the tick
     * read at each begin_* (0 = boot-time default), so a previous test's tick
     * must not leak in. The motion-start base is set separately below. */
    test_set_tick(0U);

    /* FAULT_LOCK + START -> POWER_ON (POST begins). */
    fake_active_inputs = EC_INPUT_START;
    ec_app_poll(1U);
    TEST_ASSERT(ec_app_state() == EC_STATE_POWER_ON);
    fake_active_inputs = 0U;

    /* POST passes after 100 ms (all limits same state). */
    ec_app_poll(100U);
    TEST_ASSERT(ec_app_state() == EC_STATE_HOMING);

    /* HOMING passes after 500 ms debounce with both home switches active. */
    fake_active_inputs = EC_INPUT_X_HOME | EC_INPUT_Y_HOME;
    ec_app_poll(499U);
    TEST_ASSERT(ec_app_state() == EC_STATE_HOMING);
    ec_app_poll(500U);
    TEST_ASSERT(ec_app_state() == EC_STATE_PREPARE_BARRIER);
    fake_active_inputs = 0U;

    /* Barrier: no feedback input mapped on the host -> test seam. */
    ec_app_test_force_barrier_verified();
    TEST_ASSERT(ec_app_state() == EC_STATE_WAIT_TASK);

    /* ITEM_TASK -> VALIDATE_TASK -> (workspace ok) -> EXECUTING; the
     * watchdog opens with HAL_GetTick() = motion_start_tick. */
    test_set_tick(motion_start_tick);
    feed_item_task();
    TEST_ASSERT(ec_app_state() == EC_STATE_EXECUTING);
    TEST_ASSERT(ec_app_test_watchdog_active());
    TEST_ASSERT(ec_app_test_last_observable_ms() == motion_start_tick);
}

/* Test 1: a new valid observable-progress token re-bases the window.
 * Motion starts at t=0 (base 1000); a token at t=10 s moves the base to
 * 11000; t=24.9 s is still inside (10+15 > 24.9); t=25 s locks (15 s since
 * the last progress). */
static void test_deadline_token_extends(void)
{
    start_motion_at(1000U);
    ec_app_progress_source_set_enabled(true); /* bench-validated source on */

    test_set_tick(11000U);
    ec_app_note_observable_progress(1U);
    TEST_ASSERT(ec_app_test_last_observable_ms() == 11000U);

    ec_app_poll(25900U); /* t = 24.9 s after motion start */
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);
    ec_app_poll(26000U); /* t = 25.0 s after motion start */
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
}

/* Test 2: the same token delivered twice never re-extends. The second
 * delivery at t=20 s must be dropped (dedup), so the base stays at 11000 and
 * the window locks at t=25 s (not t=35 s). */
static void test_deadline_duplicate_token(void)
{
    start_motion_at(1000U);
    ec_app_progress_source_set_enabled(true);

    test_set_tick(11000U);
    ec_app_note_observable_progress(7U);
    TEST_ASSERT(ec_app_test_last_observable_ms() == 11000U);

    /* Same token re-delivered at t=20 s: must NOT refresh the base. */
    test_set_tick(21000U);
    ec_app_note_observable_progress(7U);
    TEST_ASSERT(ec_app_test_last_observable_ms() == 11000U);

    ec_app_poll(25900U); /* t = 24.9 s after motion start */
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);
    ec_app_poll(26000U); /* t = 25.0 s after motion start */
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
}

/* Test 3: exactly 15000 ms since the last observable progress locks. */
static void test_deadline_exact_15s(void)
{
    start_motion_at(1000U);

    ec_app_poll(15999U);
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);
    ec_app_poll(16000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
}

/* Test 4: a valid token at 14.9 s restarts the full 15 s countdown. */
static void test_deadline_149s_token(void)
{
    start_motion_at(1000U);
    ec_app_progress_source_set_enabled(true);

    test_set_tick(15900U);
    ec_app_note_observable_progress(2U);
    TEST_ASSERT(ec_app_test_last_observable_ms() == 15900U);

    ec_app_poll(30899U);
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);
    ec_app_poll(30900U);
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
}

/* Test 5: MOTION_DONE neither clears nor restarts the window - the display
 * phase keeps the remaining budget of the same rolling window (base 1000),
 * so it locks at t=16 s, not 16+15 s. */
static void test_deadline_motion_done_no_restart(void)
{
    start_motion_at(1000U);

    /* Motion completes at t=6 s: MOTION_DONE -> WAIT_ITEM_RESULT -> (item
     * result recorded) -> WAIT_DISPLAY_ACK. */
    fake_axis_state = EC_AXIS_STATE_DONE;
    fake_axis_result = EC_AXIS_RESULT_OK;
    ec_app_poll(6000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_WAIT_DISPLAY_ACK);
    TEST_ASSERT(ec_app_test_watchdog_active());
    TEST_ASSERT(ec_app_test_last_observable_ms() == 1000U);

    ec_app_poll(15999U);
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);
    ec_app_poll(16000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
}

/* Test 6a: an invalid DISPLAY_ACK (render_result != RENDERED) emits a NACK
 * and never refreshes the base: the window still locks at t=16 s. */
static void test_deadline_invalid_ack_no_extend(void)
{
    unsigned tx_before;

    start_motion_at(1000U);

    fake_axis_state = EC_AXIS_STATE_DONE;
    fake_axis_result = EC_AXIS_RESULT_OK;
    ec_app_poll(6000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_WAIT_DISPLAY_ACK);

    tx_before = uart_tx_calls;
    feed_display_ack(0U, 0x01U); /* not RENDERED -> validation fails */
    TEST_ASSERT(uart_tx_calls > tx_before);   /* NACK emitted */
    TEST_ASSERT(ec_app_state() == EC_STATE_WAIT_DISPLAY_ACK);
    TEST_ASSERT(ec_app_test_watchdog_active());
    TEST_ASSERT(ec_app_test_last_observable_ms() == 1000U);

    ec_app_poll(15999U);
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);
    ec_app_poll(16000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
}

/* Test 6b: the first valid DISPLAY_ACK closes the case (watchdog off); the
 * same ACK re-delivered only RESENDs - it never re-arms or re-extends. */
static void test_deadline_duplicate_ack_no_reatm(void)
{
    uint32_t valid_crc;

    start_motion_at(1000U);

    fake_axis_state = EC_AXIS_STATE_DONE;
    fake_axis_result = EC_AXIS_RESULT_OK;
    ec_app_poll(6000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_WAIT_DISPLAY_ACK);

    valid_crc = valid_display_ack_crc();
    feed_display_ack(valid_crc, EC_DISPLAY_ACK_RENDERED);
    TEST_ASSERT(ec_app_state() == EC_STATE_PREPARE_BARRIER);
    TEST_ASSERT(!ec_app_test_watchdog_active());

    /* Same ACK again: cached resend only, no re-arm, no re-entry. */
    feed_display_ack(valid_crc, EC_DISPLAY_ACK_RENDERED);
    TEST_ASSERT(ec_app_state() == EC_STATE_PREPARE_BARRIER);
    TEST_ASSERT(!ec_app_test_watchdog_active());
    TEST_ASSERT(ec_app_test_last_observable_ms() == 1000U);
}

/* Test 7: uint32 tick wraparound. Base near UINT32_MAX (0xFFFFFF00); after
 * the tick wraps, (now - base) must still be computed wrap-safe:
 * 0x00000010 - 0xFFFFFF00 = 0x110 = 272 ms (< 15000, no lock);
 * 0x00003997 -> 14999 ms (no lock); 0x00003998 -> 15000 ms (lock). */
static void test_deadline_tick_wraparound(void)
{
    start_motion_at(0xFFFFFF00U);
    TEST_ASSERT(ec_app_test_last_observable_ms() == 0xFFFFFF00U);

    ec_app_poll(0x00000010U);
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);

    ec_app_poll(0x00003997U);
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);

    ec_app_poll(0x00003998U);
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
}

/* Test 8: fail-closed - with the progress-source switch OFF (the boot
 * default; production compiles with EC_APP_PROGRESS_SOURCE_ENABLED=0 so the
 * switch is locked off entirely), a token is a no-op and motion outrunning
 * the 15 s window locks. */
static void test_deadline_fail_closed(void)
{
    start_motion_at(1000U); /* ec_app_init() boots the switch OFF */

    test_set_tick(11000U);
    ec_app_note_observable_progress(1U);
    TEST_ASSERT(ec_app_test_last_observable_ms() == 1000U); /* no-op */

    ec_app_poll(15999U);
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);
    ec_app_poll(16000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
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

    /* Rolling no-motion watchdog (design §3.4, 8 cases). */
    test_deadline_token_extends();
    test_deadline_duplicate_token();
    test_deadline_exact_15s();
    test_deadline_149s_token();
    test_deadline_motion_done_no_restart();
    test_deadline_invalid_ack_no_extend();
    test_deadline_duplicate_ack_no_reatm();
    test_deadline_tick_wraparound();
    test_deadline_fail_closed();
}
