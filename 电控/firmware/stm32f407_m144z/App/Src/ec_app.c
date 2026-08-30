#include "ec_app.h"

#include "ec_axis_driver.h"
#include "ec_barrier_test.h"
#include "ec_board.h"
#include "ec_demo.h"
#include "ec_diag.h"
#include "ec_group_test.h"
#include "ec_inputs.h"
#include "ec_motion_plan.h"
#include "ec_protocol_gateway.h"
#include "ec_safety_adapter.h"
#include "ec_servo_test.h"
#include "ec_startup_sequence.h"
#include "ec_step_test.h"

#include "stm32f4xx_hal.h"

#ifndef EC_DIAGNOSTIC_BUILD
#define EC_DIAGNOSTIC_BUILD 0
#endif

#define EC_INPUT_SAMPLE_PERIOD_MS UINT32_C(10)

/* Production protocol gateway: owns the state machine + dedup + frame
 * assembly, replacing the diagnostic build's bare ec_state_machine_t. The
 * ASCII diagnostic command set (ec_diag) coexists on the same UART, routed by
 * the binary frame header 0xA5 (see ec_app_on_uart_rx_byte). */
static ec_gateway_t gateway;

/* Round counter for MANUAL_NEW_ROUND_CONFIRMED. PLACEHOLDER: the round-id
 * convention must be agreed with the Pi/vision side (the ITEM_TASK frame's
 * task_id must equal this). Local increment for now. */
static uint32_t local_round_id;

static uint32_t last_input_sample_ms;

/* Rolling no-motion watchdog (docs/design/2026-08-30-motion-time-budget.md
 * §3.3): last_observable_ms is a monotonically-rolling base that moves only
 * on (a) motion start and (b) bench-validated observable progress tokens
 * (when the progress source is enabled - production default OFF). Heartbeat,
 * retransmits, ACK/NACK, repeated DISPLAY_ACK and MOTION_DONE never touch it.
 * watchdog_active is true while a window is open. All comparisons use uint32
 * wrap-safe subtraction. */
static uint32_t last_observable_ms;
static bool watchdog_active;

#if EC_APP_PROGRESS_SOURCE_ENABLED
/* Progress-source adapter switch (see ec_app.h). Boots OFF (fail-closed):
 * ec_app_init() resets it, and no production caller feeds tokens yet. */
static bool progress_source_enabled;
/* Per-window token dedup: only a token strictly newer than the last consumed
 * one may re-base the window. Same token re-delivered, or an older token, is
 * dropped (design §3.3.2: 同一令牌去重). */
static uint32_t last_progress_token;
static bool last_progress_token_valid;
#endif

/* Power permission monitoring: last known state */
static bool power_permission_lost;

static void ec_app_handle_transition(const ec_transition_t *t);

static void ec_app_flush_tx(void)
{
    if (ec_gateway_tx_len(&gateway) != 0U) {
        ec_board_uart_transmit(ec_gateway_tx_data(&gateway),
                               ec_gateway_tx_len(&gateway));
    }
}

/* Inject a hardware/manual event that carries no extra payload. Recurses
 * through the placeholder-immediate boot sequence (POST -> HOMING -> BARRIER)
 * and item validation; depth is bounded (<= 5). */
static void ec_app_inject_simple(ec_event_type_t type)
{
    ec_gateway_event_t event;
    ec_transition_t t;

    event.type = type;
    event.round_id = 0U;
    event.round_closed = false;
    event.danger_area_clear = false;
    event.estop_released = false;
    event.content_validated = true;
    event.result_code = EC_RESULT_SUCCESS;

    t = ec_gateway_inject(&gateway, &event);
    ec_app_handle_transition(&t);
}

static void ec_app_inject_item_result(uint8_t result_code)
{
    ec_gateway_event_t event;
    ec_transition_t t;

    event.type = EC_EVENT_ITEM_RESULT_RECORDED;
    event.round_id = 0U;
    event.round_closed = false;
    event.danger_area_clear = false;
    event.estop_released = false;
    event.content_validated = false;
    event.result_code = result_code;

    t = ec_gateway_inject(&gateway, &event);
    ec_app_handle_transition(&t);
}

/* Rolling no-motion watchdog - observable progress token entry (design §3.3).
 *
 * Only bench-validated observable progress may re-base the 15 s window. A
 * program-step completion count is NOT such progress (a stalled axis still
 * advances its pulse counter), which is why no production source feeds this
 * yet: with EC_APP_PROGRESS_SOURCE_ENABLED 0 (production default) this is a
 * hard no-op, fail-closed. When compiled in, the runtime adapter switch still
 * boots OFF; a bench-validated source enables it explicitly. Same-token
 * re-delivery (and any older token) never re-extends. */
void ec_app_note_observable_progress(uint32_t token)
{
#if EC_APP_PROGRESS_SOURCE_ENABLED
    if (!progress_source_enabled) {
        return; /* adapter switch off: tokens must not move the base */
    }
    if (!watchdog_active) {
        return; /* no open window: a late token must not arm anything */
    }
    if (last_progress_token_valid && (token <= last_progress_token)) {
        return; /* duplicate or stale token: no re-extend */
    }
    last_progress_token = token;
    last_progress_token_valid = true;
    last_observable_ms = HAL_GetTick();
#else
    (void)token; /* progress source not compiled in: fail-closed no-op */
#endif
}

/* Runtime progress-source adapter switch. At EC_APP_PROGRESS_SOURCE_ENABLED 0
 * (production default) this is locked closed: nothing can enable the token
 * path in a build that was compiled fail-closed. */
void ec_app_progress_source_set_enabled(bool enabled)
{
#if EC_APP_PROGRESS_SOURCE_ENABLED
    progress_source_enabled = enabled;
#else
    (void)enabled; /* compile-time OFF: locked closed (fail-closed) */
#endif
}

/* Build the pick-place program from the current item's drop coordinate (latched
 * by the gateway from ITEM_TASK) and arm the axis driver. The mm->steps /
 * direction mapping and the mechanical waypoints live in ec_motion_plan; the
 * parameters there are still placeholders pending the real mechanical layout. */
static void ec_app_start_motion(void)
{
    ec_axis_pick_place_t program;
    ec_axis_result_t result;
    int16_t x_mm10;
    int16_t y_mm10;

    if (!ec_gateway_item_target(&gateway, &x_mm10, &y_mm10) ||
        !ec_motion_plan_build(&program, x_mm10, y_mm10)) {
        /* No latched coordinate or out-of-workspace target -> unreachable. */
        ec_app_inject_item_result(EC_RESULT_POSITION_UNREACHABLE);
        return;
    }

    result = ec_axis_driver_start_pick_place(&program);
    if (result != EC_AXIS_RESULT_OK) {
        /* Motion failed to arm -> a failed item result. Real failure
         * classification waits on the result sensors (default off). */
        ec_app_inject_item_result(EC_RESULT_POSITION_UNREACHABLE);
        return;
    }

    /* Open the rolling no-motion watchdog window from motion start
     * (design §3.3). The base only moves again on bench-validated progress
     * tokens (progress source enabled) or the first valid DISPLAY_ACK. */
    last_observable_ms = HAL_GetTick();
    watchdog_active = true;
#if EC_APP_PROGRESS_SOURCE_ENABLED
    last_progress_token_valid = false; /* fresh window: fresh token dedup */
#endif
}

static void ec_app_handle_transition(const ec_transition_t *t)
{
    if ((t->actions & EC_ACTION_SAFE_LOCK) != 0U) {
        ec_safety_apply(t->actions);
    }
    /* P0-FIX: Removed automatic injection of POST_PASSED, HOMING_PASSED,
     * BARRIER_AVOIDANCE_VERIFIED, and TASK_SAFETY_VALIDATED. These MUST be
     * triggered by real sensor checks, timeout expiry, or manual override.
     * Without this fix, any ITEM_TASK could start motion without safety checks. */

    /* First valid DISPLAY_ACK closes the rolling no-motion window (结案,
     * design §3.3). The ACK_DISPLAY_CONSUMED action fires only on the first
     * valid consumption; repeat ACKs only RESEND and never re-arm or extend.
     * P0-FIX (kept): also clear when a transition reaches READY state, so a
     * future state machine reaching READY still closes the window. */
    if ((t->actions & EC_ACTION_ACK_DISPLAY_CONSUMED) != 0U) {
        watchdog_active = false;
    }
    if (t->state == EC_STATE_READY) {
        watchdog_active = false;
    }

    /* Startup sequence integration: trigger real checks instead of auto-pass */
    if ((t->actions & EC_ACTION_BEGIN_POST) != 0U) {
        ec_startup_sequence_begin_post(HAL_GetTick());
    }
    if ((t->actions & EC_ACTION_BEGIN_HOMING) != 0U) {
        ec_startup_sequence_begin_homing(HAL_GetTick());
    }
    if ((t->actions & EC_ACTION_PREPARE_BARRIER) != 0U) {
        /* P0-FIX: Reset startup sequence before each item to prevent second-item
         * deadlock. Barrier state must be cleared so begin_barrier() restarts. */
        ec_startup_sequence_reset();
        ec_startup_sequence_begin_barrier(HAL_GetTick());
    }

    if ((t->actions & EC_ACTION_START_MOTION) != 0U) {
        ec_app_start_motion();
    }

    /* Task safety validation: Check target coordinate and safety gates.
     * Coordinate must be within frozen workspace (+/-145mm per interface-contract).
     * Other gates (barrier position, danger area) require real sensor integration. */
    if (t->state == EC_STATE_VALIDATE_TASK) {
        ec_axis_pick_place_t program;
        int16_t x_mm10, y_mm10;
        bool workspace_ok = false;

        /* Check if target coordinate can be reached (workspace boundary check) */
        if (ec_gateway_item_target(&gateway, &x_mm10, &y_mm10)) {
            workspace_ok = ec_motion_plan_build(&program, x_mm10, y_mm10);
        }

        /* TODO: Add real safety checks for:
         * - Barrier collision (current barrier position vs target path)
         * - Danger area clear (e/stop, hand sensor, etc.)
         * - All safety interlocks engaged */

        if (workspace_ok) {
            ec_app_inject_simple(EC_EVENT_TASK_SAFETY_VALIDATED);
        } else {
            /* Coordinate out of bounds or unreachable */
            ec_app_inject_item_result(EC_RESULT_POSITION_UNREACHABLE);
        }
    }

    ec_app_flush_tx();
}

/* Power permission check: external power-enable signal (active-high).
 * Returns true if power permission is currently lost.
 *
 * SEMANTICS: active_inputs are active-low signals that have been triggered.
 * When EC_INPUT_POWER_PERMISSION bit is SET in active_inputs, it means the
 * external power line is LOW (permission lost). When CLEAR, power is present. */
static bool power_permission_check_lost(uint16_t active_inputs)
{
    /* P0-FIX: Inverted logic - active_inputs bit SET = signal triggered (LOW) = permission lost */
    return (active_inputs & EC_INPUT_POWER_PERMISSION) != 0U;
}

static void ec_app_poll_start_button(uint16_t active_inputs)
{
    ec_gateway_event_t event;
    ec_transition_t t;

    if (ec_gateway_state(&gateway) != EC_STATE_FAULT_LOCK) {
        return;
    }
    if ((active_inputs & EC_INPUT_START) == 0U) {
        return;
    }

    ++local_round_id;

    /* Reset startup sequence for new round to prevent deadlock on second item */
    ec_startup_sequence_reset();

    event.type = EC_EVENT_MANUAL_NEW_ROUND_CONFIRMED;
    event.round_id = local_round_id;
    event.round_closed = true;

    /* P0-FIX: Real danger area check using actual sensor inputs.
     * Danger area is clear when:
     * 1. ESTOP is not active (estop_released = true)
     * 2. No manual reset signal active (indicates operator intervention needed)
     *
     * LIMITATION: No dedicated "hand sensor" or "light curtain" input yet.
     * Current implementation uses ESTOP + MANUAL_RESET as proxy for danger area.
     * FUTURE: Add dedicated safety sensors when hardware is available.
     */
    event.danger_area_clear = ((active_inputs & EC_INPUT_ESTOP_FB) == 0U) &&
                              ((active_inputs & EC_INPUT_MANUAL_RESET) == 0U);
    event.estop_released = (active_inputs & EC_INPUT_ESTOP_FB) == 0U;
    event.content_validated = false;
    event.result_code = EC_RESULT_SUCCESS;

    t = ec_gateway_inject(&gateway, &event);
    ec_app_handle_transition(&t);
}

static void ec_app_poll_startup_sequence(uint32_t now_ms, uint16_t active_inputs)
{
    ec_startup_result_t result;

    /* Poll POST sequence */
    result = ec_startup_sequence_poll_post(now_ms, active_inputs);
    if (result == EC_STARTUP_PASSED) {
        ec_app_inject_simple(EC_EVENT_POST_PASSED);
    } else if (result == EC_STARTUP_FAILED) {
        ec_gateway_event_t event;
        ec_transition_t t;
        event.type = EC_EVENT_EMERGENCY_STOP;
        event.round_id = 0U;
        event.round_closed = false;
        event.danger_area_clear = false;
        event.estop_released = false;
        event.content_validated = false;
        event.result_code = EC_RESULT_UNKNOWN;
        t = ec_gateway_inject(&gateway, &event);
        ec_app_handle_transition(&t);
        return;
    }

    /* Poll homing sequence */
    result = ec_startup_sequence_poll_homing(now_ms, active_inputs);
    if (result == EC_STARTUP_PASSED) {
        ec_app_inject_simple(EC_EVENT_HOMING_PASSED);
    } else if (result == EC_STARTUP_FAILED) {
        ec_gateway_event_t event;
        ec_transition_t t;
        event.type = EC_EVENT_EMERGENCY_STOP;
        event.round_id = 0U;
        event.round_closed = false;
        event.danger_area_clear = false;
        event.estop_released = false;
        event.content_validated = false;
        event.result_code = EC_RESULT_UNKNOWN;
        t = ec_gateway_inject(&gateway, &event);
        ec_app_handle_transition(&t);
        return;
    }

    /* Poll barrier avoidance sequence */
    result = ec_startup_sequence_poll_barrier(now_ms, active_inputs);
    if (result == EC_STARTUP_PASSED) {
        ec_app_inject_simple(EC_EVENT_BARRIER_AVOIDANCE_VERIFIED);
    } else if (result == EC_STARTUP_FAILED) {
        ec_gateway_event_t event;
        ec_transition_t t;
        event.type = EC_EVENT_EMERGENCY_STOP;
        event.round_id = 0U;
        event.round_closed = false;
        event.danger_area_clear = false;
        event.estop_released = false;
        event.content_validated = false;
        event.result_code = EC_RESULT_UNKNOWN;
        t = ec_gateway_inject(&gateway, &event);
        ec_app_handle_transition(&t);
        return;
    }
}

static void ec_app_poll_motion(uint32_t now_ms, uint16_t active_inputs)
{
    ec_axis_state_t axis_state;
    ec_axis_result_t axis_result;
    ec_gateway_event_t event;
    ec_transition_t t;
    ec_state_t current_state = ec_gateway_state(&gateway);

    /* Deadline starts at motion and remains active until a validated DISPLAY_ACK.
     * It must also be checked while waiting for that acknowledgement. */
    if ((current_state != EC_STATE_EXECUTING) &&
        (current_state != EC_STATE_WAIT_ITEM_RESULT) &&
        (current_state != EC_STATE_WAIT_DISPLAY_ACK)) {
        return;
    }

    /* P0-FIX: Check for safety violations BEFORE polling axis driver.
     * Generate EMERGENCY_STOP / POWER_PERMISSION_LOST events immediately. */
    if ((active_inputs & EC_INPUT_ESTOP_FB) != 0U) {
        /* ESTOP_FB active-high means emergency stop is triggered */
        watchdog_active = false;
        event.type = EC_EVENT_EMERGENCY_STOP;
        event.round_id = 0U;
        event.round_closed = false;
        event.danger_area_clear = false;
        event.estop_released = false;
        event.content_validated = false;
        event.result_code = EC_RESULT_UNKNOWN;
        t = ec_gateway_inject(&gateway, &event);
        ec_app_handle_transition(&t);
        return;
    }

    /* Rolling no-motion watchdog check (design §3.3): the window closes when
     * the machine stays without observable progress for 15 s. The base is
     * last_observable_ms (motion start, or the last bench-validated progress
     * token). uint32 wrap-safe subtraction keeps this correct across the
     * 49.7-day tick rollover. */
    if (watchdog_active) {
        if ((uint32_t)(now_ms - last_observable_ms) >= UINT32_C(15000)) {
            watchdog_active = false;
            event.type = EC_EVENT_DEADLINE_EXPIRED;
            event.round_id = 0U;
            event.round_closed = false;
            event.danger_area_clear = false;
            event.estop_released = false;
            event.content_validated = false;
            event.result_code = EC_RESULT_UNKNOWN;
            t = ec_gateway_inject(&gateway, &event);
            ec_app_handle_transition(&t);
            return;
        }
    }

    /* Check for power permission loss.
     * External power-enable signal (EC_INPUT_POWER_PERMISSION) must remain active
     * throughout motion execution. Loss of power permission immediately triggers
     * EMERGENCY_STOP and clears the deadline. */
    if (power_permission_check_lost(active_inputs)) {
        if (!power_permission_lost) {
            power_permission_lost = true;
            watchdog_active = false;
            event.type = EC_EVENT_POWER_PERMISSION_LOST;
            event.round_id = 0U;
            event.round_closed = false;
            event.danger_area_clear = false;
            event.estop_released = false;
            event.content_validated = false;
            event.result_code = EC_RESULT_UNKNOWN;
            t = ec_gateway_inject(&gateway, &event);
            ec_app_handle_transition(&t);
            return;
        }
    } else {
        power_permission_lost = false;
    }

    /* Only poll axis driver in EXECUTING state */
    if (current_state != EC_STATE_EXECUTING) {
        return;
    }

    (void)ec_axis_driver_poll(now_ms, active_inputs);
    axis_state = ec_axis_driver_state();

    if (axis_state == EC_AXIS_STATE_DONE) {
        axis_result = ec_axis_driver_result();
        /* MOTION_DONE deliberately does NOT clear, restart or extend the
         * rolling no-motion window (design §3.3 item 3): the display phase
         * keeps the remaining budget of the same window, measured from the
         * last observable progress. Only the first valid DISPLAY_ACK closes
         * it (or a fault / deadline expiry). */
        ec_app_inject_simple(EC_EVENT_MOTION_DONE);
        /* PLACEHOLDER result classification: success on OK, else generic. */
        ec_app_inject_item_result((axis_result == EC_AXIS_RESULT_OK)
                                      ? EC_RESULT_SUCCESS
                                      : EC_RESULT_DROP_FAILED);
    } else if (axis_state == EC_AXIS_STATE_FAULT) {
        /* P0-FIX: Axis fault should trigger safety lockdown, not normal completion */
        watchdog_active = false;
        event.type = EC_EVENT_EMERGENCY_STOP;
        event.round_id = 0U;
        event.round_closed = false;
        event.danger_area_clear = false;
        event.estop_released = false;
        event.content_validated = false;
        event.result_code = EC_RESULT_UNKNOWN;
        t = ec_gateway_inject(&gateway, &event);
        ec_app_handle_transition(&t);
    }
}

void ec_app_init(void)
{
    ec_board_enter_safe_state();
    ec_gateway_init(&gateway);
    ec_safety_apply(EC_ACTION_SAFE_LOCK);
    ec_startup_sequence_init();
    local_round_id = 0U;
    watchdog_active = false;
    last_observable_ms = 0U;
    power_permission_lost = false;
#if EC_APP_PROGRESS_SOURCE_ENABLED
    /* Adapter switch boots OFF (fail-closed) on every init. */
    progress_source_enabled = false;
    last_progress_token_valid = false;
#endif

    ec_step_test_init();
    ec_servo_test_init();
    ec_group_test_init();
    ec_barrier_test_init();
    ec_demo_init();
    ec_diag_init();
    last_input_sample_ms = 0U;
    ec_board_poll_inputs(0U);
    ec_board_uart_start_rx();

#if EC_DIAGNOSTIC_BUILD
    ec_diag_port_write("BOOT SAFE HSI=16000000 SAFE_LOCK=1 ENABLES=DISABLED\r\n");
#endif
}

void ec_app_poll(uint32_t now_ms)
{
    ec_input_snapshot_t inputs;

    if ((uint32_t)(now_ms - last_input_sample_ms) >=
        EC_INPUT_SAMPLE_PERIOD_MS) {
        last_input_sample_ms = now_ms;
        ec_board_poll_inputs(now_ms);
    }

    inputs = ec_board_read_inputs();

    ec_app_poll_start_button(inputs.active_mask);
    ec_app_poll_startup_sequence(now_ms, inputs.active_mask);
    ec_app_poll_motion(now_ms, inputs.active_mask);

    /* P0-FIX: Poll UART RX ring buffer in main loop, not in ISR.
     * Process all available bytes serially to avoid ISR recursion. */
    while (ec_board_uart_rx_available()) {
        ec_app_on_uart_rx_byte(ec_board_uart_rx_read());
    }

    ec_step_test_poll(now_ms, inputs.active_mask);
    ec_servo_test_poll(now_ms, inputs.active_mask);
    ec_group_test_poll(now_ms, inputs.active_mask);
    ec_barrier_test_poll(now_ms, inputs.active_mask);
    ec_diag_poll();
    ec_demo_poll(now_ms, inputs.active_mask);
    ec_diag_tick(now_ms);
}

void ec_app_on_uart_rx_byte(uint8_t byte)
{
    /* Route: a 0xA5 starts (or continues) a binary frame; everything else is
     * ASCII diagnostics. ASCII command bytes are printable and never 0xA5. */
    if ((byte == EC_PROTO_HEADER_0) || ec_gateway_rx_active(&gateway)) {
        ec_transition_t t = ec_gateway_feed_byte(&gateway, byte);
        ec_app_handle_transition(&t);
    } else {
        ec_diag_on_rx_byte(byte);
    }
}

ec_state_t ec_app_state(void)
{
    return ec_gateway_state(&gateway);
}

#if EC_APP_TEST_HOOKS
/* Host-test seam (compiled out of production builds). The app boot chain
 * cannot reach WAIT_TASK on the host because no barrier-feedback input is
 * mapped (ec_startup_sequence.c keeps PREPARE_BARRIER blocked). This injects
 * the BARRIER_AVOIDANCE_VERIFIED event exactly as the real startup sequence
 * would, and neutralises the barrier timer so it cannot fire mid-test. */
void ec_app_test_force_barrier_verified(void)
{
    ec_startup_sequence_reset();
    ec_app_inject_simple(EC_EVENT_BARRIER_AVOIDANCE_VERIFIED);
}

bool ec_app_test_watchdog_active(void)
{
    return watchdog_active;
}

uint32_t ec_app_test_last_observable_ms(void)
{
    return last_observable_ms;
}
#endif
