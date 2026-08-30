#ifndef EC_STATE_MACHINE_H
#define EC_STATE_MACHINE_H

#include "ec_dedup.h"

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    EC_STATE_FAULT_LOCK = 0,
    EC_STATE_POWER_ON,
    EC_STATE_POST,
    EC_STATE_HOMING,
    EC_STATE_READY,
    EC_STATE_PREPARE_BARRIER,
    EC_STATE_WAIT_TASK,
    EC_STATE_VALIDATE_TASK,
    EC_STATE_EXECUTING,
    EC_STATE_WAIT_ITEM_RESULT,
    EC_STATE_WAIT_DISPLAY_ACK,
    EC_STATE_COMPLETE
} ec_state_t;

typedef enum {
    EC_FAULT_NONE = 0,
    EC_FAULT_RESTART_CONTEXT_UNPROVEN,
    EC_FAULT_DEDUP_CONFLICT,
    EC_FAULT_DEDUP_CAPACITY_EXHAUSTED,
    EC_FAULT_EMERGENCY_STOP,
    EC_FAULT_POWER_PERMISSION_LOST,
    EC_FAULT_DEADLINE_EXPIRED
} ec_fault_reason_t;

typedef enum {
    EC_EVENT_MANUAL_NEW_ROUND_CONFIRMED = 0,
    EC_EVENT_POST_PASSED,
    EC_EVENT_HOMING_PASSED,
    EC_EVENT_BARRIER_AVOIDANCE_VERIFIED,
    EC_EVENT_ITEM_TASK_ACCEPTED,
    EC_EVENT_TASK_SAFETY_VALIDATED,
    EC_EVENT_MOTION_DONE,
    EC_EVENT_ITEM_RESULT_RECORDED,
    EC_EVENT_DISPLAY_ACK_VALIDATED,
    EC_EVENT_EMERGENCY_STOP,
    EC_EVENT_POWER_PERMISSION_LOST,
    EC_EVENT_DEADLINE_EXPIRED,
    EC_EVENT_DEDUP_CAPACITY_EXHAUSTED
} ec_event_type_t;

typedef uint32_t ec_action_t;

#define EC_ACTION_NONE UINT32_C(0)
#define EC_ACTION_STOP_ALL (UINT32_C(1) << 0U)
#define EC_ACTION_DISABLE_DRIVERS (UINT32_C(1) << 1U)
#define EC_ACTION_INHIBIT_POWER (UINT32_C(1) << 2U)
#define EC_ACTION_BEGIN_POST (UINT32_C(1) << 3U)
#define EC_ACTION_BEGIN_HOMING (UINT32_C(1) << 4U)
#define EC_ACTION_PREPARE_BARRIER (UINT32_C(1) << 5U)
#define EC_ACTION_EMIT_BARRIER_READY (UINT32_C(1) << 6U)
#define EC_ACTION_START_MOTION (UINT32_C(1) << 7U)
#define EC_ACTION_EMIT_MOTION_DONE (UINT32_C(1) << 8U)
#define EC_ACTION_EMIT_ITEM_RESULT (UINT32_C(1) << 9U)
#define EC_ACTION_RESEND_CACHED_RESPONSE (UINT32_C(1) << 10U)
#define EC_ACTION_REJECT_NEW_TASK (UINT32_C(1) << 11U)
/* ACK/NACK response actions (proposal 2026-08-29 sec. 3.3.4): the gateway
 * materialises these as ACK/NACK frames and caches the response bytes. */
#define EC_ACTION_ACK_ITEM_ACCEPTED (UINT32_C(1) << 12U)
#define EC_ACTION_ACK_DISPLAY_CONSUMED (UINT32_C(1) << 13U)

#define EC_ACTION_SAFE_LOCK                                                   \
    (EC_ACTION_STOP_ALL | EC_ACTION_DISABLE_DRIVERS | EC_ACTION_INHIBIT_POWER)

typedef struct {
    ec_event_type_t type;
    ec_dedup_key_t identity;
    uint32_t round_id;
    bool round_closed;
    bool danger_area_clear;
    bool estop_released;
    bool content_validated;
} ec_event_t;

typedef struct {
    ec_state_t state;
    ec_fault_reason_t fault_reason;
    ec_action_t actions;
} ec_transition_t;

typedef struct {
    ec_state_t state;
    ec_fault_reason_t fault_reason;
    ec_action_t actions;
    ec_dedup_t *dedup;
    uint32_t round_id;
    ec_dedup_key_t current_item;
    bool has_current_item;
    bool ack_consumed;
    /* Order-gate watermark (proposal 2026-08-29 sec. 3.5): the frame_seq of
     * the last accepted item this round. An ITEM_TASK whose frame_seq is
     * <= this value and is not a dedup hit is stale/out-of-order and is
     * rejected (aligned with Python state_machine/core.py). 0 = none
     * accepted this round; cleared on a verified new round. */
    uint32_t last_accepted_frame_seq;
} ec_state_machine_t;

void ec_sm_init(ec_state_machine_t *machine, ec_dedup_t *dedup);
ec_transition_t ec_sm_consume(ec_state_machine_t *machine,
                              const ec_event_t *event);

#endif
