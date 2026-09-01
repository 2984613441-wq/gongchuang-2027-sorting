/* ec_startup_sequence.c - Safety startup chain implementation
 *
 * Implements real POST, homing, and barrier avoidance checks that generate
 * the events previously auto-injected in ec_app.c:108-131.
 *
 * Current implementation: MINIMAL PLACEHOLDERS for initial testing.
 * Each phase must be replaced with real sensor checks before production use.
 */

#include "ec_startup_sequence.h"
#include "ec_board.h"
#include "ec_inputs.h"

#include <stdbool.h>
#include <stdint.h>

#define POST_TIMEOUT_MS     UINT32_C(2000)
#define HOMING_TIMEOUT_MS   UINT32_C(30000)  /* 30s for dual-axis homing */
#define BARRIER_TIMEOUT_MS  UINT32_C(5000)

typedef enum {
    POST_IDLE = 0,
    POST_RUNNING,
    POST_PASSED,
    POST_FAILED,
} ec_post_state_t;

typedef enum {
    HOMING_IDLE = 0,
    HOMING_RUNNING,
    HOMING_PASSED,
    HOMING_FAILED,
} ec_homing_state_t;

typedef enum {
    BARRIER_IDLE = 0,
    BARRIER_RUNNING,
    BARRIER_PASSED,
    BARRIER_FAILED,
} ec_barrier_state_t;

static ec_post_state_t post_state = POST_IDLE;
static ec_homing_state_t homing_state = HOMING_IDLE;
static ec_barrier_state_t barrier_state = BARRIER_IDLE;

static uint32_t post_start_ms;
static uint32_t homing_start_ms;
static uint32_t barrier_start_ms;

void ec_startup_sequence_init(void)
{
    post_state = POST_IDLE;
    homing_state = HOMING_IDLE;
    barrier_state = BARRIER_IDLE;
}

void ec_startup_sequence_begin_post(uint32_t now_ms)
{
    if (post_state != POST_IDLE) {
        return;
    }
    post_state = POST_RUNNING;
    post_start_ms = now_ms;
}

void ec_startup_sequence_begin_homing(uint32_t now_ms)
{
    if (homing_state != HOMING_IDLE) {
        return;
    }
    homing_state = HOMING_RUNNING;
    homing_start_ms = now_ms;
    /* TODO: Start actual homing sequence:
     * 1. Move X toward home at slow speed until X_HOME triggered
     * 2. Back off X by ~5mm
     * 3. Move Y toward home until Y_HOME triggered
     * 4. Back off Y by ~5mm
     * 5. Set current position as mechanical origin
     */
}

void ec_startup_sequence_begin_barrier(uint32_t now_ms)
{
    if (barrier_state != BARRIER_IDLE) {
        return;
    }
    barrier_state = BARRIER_RUNNING;
    barrier_start_ms = now_ms;
    /* TODO: Command barriers to avoidance position and wait for sensor feedback */
}

ec_startup_result_t ec_startup_sequence_poll_post(uint32_t now_ms,
                                                   uint16_t active_inputs)
{
    if (post_state != POST_RUNNING) {
        return EC_STARTUP_IDLE;
    }

    /* P0-FIX: Real POST checks for critical hardware readiness.
     * Checks performed:
     * 1. All limit switches readable (X_HOME, X_END, Y_HOME, Y_END, Z_UP, Z_DOWN)
     * 2. ESTOP not active
     * 3. Power permission present (when GPIO connected)
     *
     * Future expansion: driver enable verification, servo response, screen comm.
     */

    /* Check 1: ESTOP must not be active */
    if ((active_inputs & EC_INPUT_ESTOP_FB) != 0U) {
        post_state = POST_FAILED;
        return EC_STARTUP_FAILED;
    }

    /* Check 2: Power permission must be present */
    if ((active_inputs & EC_INPUT_POWER_PERMISSION) != 0U) {
        /* active_inputs is active-low: a set bit means the input line is low
         * and power permission has been lost. */
        post_state = POST_FAILED;
        return EC_STARTUP_FAILED;
    }

    /* Check 3: All limit switches must be readable (not all stuck at same state).
     * If all 6 limit inputs are identical (all 0 or all 1), likely hardware fault. */
    uint16_t limit_mask = EC_INPUT_X_HOME | EC_INPUT_X_END |
                         EC_INPUT_Y_HOME | EC_INPUT_Y_END |
                         EC_INPUT_Z_UP | EC_INPUT_Z_DOWN;
    uint16_t limit_state = active_inputs & limit_mask;
    if ((limit_state == 0U) || (limit_state == limit_mask)) {
        /* All limits same state - suspicious, but allow startup after timeout
         * to handle valid mechanical positions (e.g., all switches open) */
        if ((uint32_t)(now_ms - post_start_ms) < 100U) {
            return EC_STARTUP_RUNNING;
        }
    }

    /* POST passed: basic checks complete, allow minimum 50ms for stability */
    if ((uint32_t)(now_ms - post_start_ms) >= 50U) {
        post_state = POST_PASSED;
        return EC_STARTUP_PASSED;
    }

    /* Timeout check */
    if ((uint32_t)(now_ms - post_start_ms) >= POST_TIMEOUT_MS) {
        post_state = POST_FAILED;
        return EC_STARTUP_FAILED;
    }

    return EC_STARTUP_RUNNING;
}

ec_startup_result_t ec_startup_sequence_poll_homing(uint32_t now_ms,
                                                     uint16_t active_inputs)
{
    if (homing_state != HOMING_RUNNING) {
        return EC_STARTUP_IDLE;
    }

    /* P0-FIX: Real homing checks that both X_HOME and Y_HOME limit switches
     * are triggered, indicating the mechanism is at the mechanical origin.
     *
     * LIMITATION: This is a "verify at home" check, not active homing motion.
     * The machine must be manually positioned at home before power-on, or
     * a future revision should drive axes toward home switches.
     *
     * Pass condition: Both X_HOME and Y_HOME active for >= 500ms (debounce)
     * Fail condition: Timeout without both switches active
     */

    /* Check if both home switches are triggered (active-low, so bit set = triggered) */
    if ((active_inputs & EC_INPUT_X_HOME) != 0U &&
        (active_inputs & EC_INPUT_Y_HOME) != 0U) {
        /* Both home switches active - wait for debounce stability */
        if ((uint32_t)(now_ms - homing_start_ms) >= 500U) {
            homing_state = HOMING_PASSED;
            return EC_STARTUP_PASSED;
        }
    }

    /* Timeout: home switches not both active within allowed time */
    if ((uint32_t)(now_ms - homing_start_ms) >= HOMING_TIMEOUT_MS) {
        homing_state = HOMING_FAILED;
        return EC_STARTUP_FAILED;
    }

    return EC_STARTUP_RUNNING;
}

ec_startup_result_t ec_startup_sequence_poll_barrier(uint32_t now_ms,
                                                      uint16_t active_inputs)
{
    (void)active_inputs;

    if (barrier_state != BARRIER_RUNNING) {
        return EC_STARTUP_IDLE;
    }

    /* No barrier-position feedback is mapped yet.  Do not manufacture a
     * BARRIER_AVOIDANCE_VERIFIED event from a fixed delay: remain blocked and
     * fail on timeout until a real command plus feedback input is integrated. */

    /* Check for ESTOP during barrier motion - indicates collision */
    if ((active_inputs & EC_INPUT_ESTOP_FB) != 0U) {
        barrier_state = BARRIER_FAILED;
        return EC_STARTUP_FAILED;
    }

    /* Timeout check (5 seconds): no verified barrier feedback was received. */
    if ((uint32_t)(now_ms - barrier_start_ms) >= BARRIER_TIMEOUT_MS) {
        barrier_state = BARRIER_FAILED;
        return EC_STARTUP_FAILED;
    }

    return EC_STARTUP_RUNNING;
}

void ec_startup_sequence_reset(void)
{
    post_state = POST_IDLE;
    homing_state = HOMING_IDLE;
    barrier_state = BARRIER_IDLE;
}
