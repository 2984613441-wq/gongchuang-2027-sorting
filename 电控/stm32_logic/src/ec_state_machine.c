#include "ec_state_machine.h"

#include <stddef.h>

static ec_transition_t snapshot(const ec_state_machine_t *machine)
{
    const ec_transition_t transition = {
        machine->state,
        machine->fault_reason,
        machine->actions
    };
    return transition;
}

static bool same_identity(ec_dedup_key_t left, ec_dedup_key_t right)
{
    return (left.task_id == right.task_id) &&
           (left.frame_seq == right.frame_seq) &&
           (left.payload_fingerprint == right.payload_fingerprint);
}

static bool matches_current_context(const ec_state_machine_t *machine,
                                    const ec_event_t *event)
{
    return machine->has_current_item &&
           (event->round_id == machine->round_id) &&
           same_identity(event->identity, machine->current_item);
}

static void lock_machine(ec_state_machine_t *machine,
                         ec_fault_reason_t reason)
{
    machine->state = EC_STATE_FAULT_LOCK;
    machine->fault_reason = reason;
    machine->actions = EC_ACTION_SAFE_LOCK;
}

void ec_sm_init(ec_state_machine_t *machine, ec_dedup_t *dedup)
{
    if (machine == NULL) {
        return;
    }

    machine->state = EC_STATE_FAULT_LOCK;
    machine->fault_reason = EC_FAULT_RESTART_CONTEXT_UNPROVEN;
    machine->actions = EC_ACTION_SAFE_LOCK;
    machine->dedup = dedup;
    machine->round_id = 0U;
    machine->current_item = (ec_dedup_key_t){0U, 0U, 0U};
    machine->has_current_item = false;
    machine->ack_consumed = false;
    machine->last_accepted_frame_seq = 0U;
}

ec_transition_t ec_sm_consume(ec_state_machine_t *machine,
                              const ec_event_t *event)
{
    if ((machine == NULL) || (event == NULL)) {
        const ec_transition_t invalid = {
            EC_STATE_FAULT_LOCK,
            EC_FAULT_RESTART_CONTEXT_UNPROVEN,
            EC_ACTION_SAFE_LOCK
        };
        return invalid;
    }

    if (machine->state == EC_STATE_FAULT_LOCK) {
        if ((event->type == EC_EVENT_MANUAL_NEW_ROUND_CONFIRMED) &&
            event->round_closed && event->danger_area_clear &&
            event->estop_released && (event->round_id != machine->round_id)) {
            ec_dedup_clear_for_verified_new_round(machine->dedup);
            machine->round_id = event->round_id;
            machine->last_accepted_frame_seq = 0U;
            machine->state = EC_STATE_POWER_ON;
            machine->fault_reason = EC_FAULT_NONE;
            machine->actions = EC_ACTION_BEGIN_POST;
        }
        return snapshot(machine);
    }

    if (event->type == EC_EVENT_EMERGENCY_STOP) {
        lock_machine(machine, EC_FAULT_EMERGENCY_STOP);
        return snapshot(machine);
    }
    if (event->type == EC_EVENT_POWER_PERMISSION_LOST) {
        lock_machine(machine, EC_FAULT_POWER_PERMISSION_LOST);
        return snapshot(machine);
    }
    if (event->type == EC_EVENT_DEADLINE_EXPIRED) {
        lock_machine(machine, EC_FAULT_DEADLINE_EXPIRED);
        return snapshot(machine);
    }
    if (event->type == EC_EVENT_DEDUP_CAPACITY_EXHAUSTED) {
        lock_machine(machine, EC_FAULT_DEDUP_CAPACITY_EXHAUSTED);
        return snapshot(machine);
    }

    machine->actions = EC_ACTION_NONE;
    if ((machine->state == EC_STATE_POWER_ON) &&
        (event->type == EC_EVENT_POST_PASSED)) {
        machine->state = EC_STATE_HOMING;
        machine->actions = EC_ACTION_BEGIN_HOMING;
    } else if ((machine->state == EC_STATE_HOMING) &&
               (event->type == EC_EVENT_HOMING_PASSED)) {
        machine->state = EC_STATE_PREPARE_BARRIER;
        machine->actions = EC_ACTION_PREPARE_BARRIER;
    } else if ((machine->state == EC_STATE_PREPARE_BARRIER) &&
               (event->type == EC_EVENT_BARRIER_AVOIDANCE_VERIFIED)) {
        machine->state = EC_STATE_WAIT_TASK;
        machine->actions = EC_ACTION_EMIT_BARRIER_READY;
        machine->has_current_item = false;
    } else if ((event->type == EC_EVENT_ITEM_TASK_ACCEPTED) &&
               (machine->state != EC_STATE_WAIT_TASK)) {
        machine->actions = matches_current_context(machine, event)
                               ? EC_ACTION_RESEND_CACHED_RESPONSE
                               : EC_ACTION_REJECT_NEW_TASK;
    } else if ((event->type == EC_EVENT_ITEM_TASK_ACCEPTED) &&
               (event->round_id != machine->round_id)) {
        machine->actions = EC_ACTION_REJECT_NEW_TASK;
    } else if (event->type == EC_EVENT_ITEM_TASK_ACCEPTED) {
        const ec_dedup_result_t result =
            ec_dedup_observe(machine->dedup, event->identity);

        if (result == EC_DEDUP_DUPLICATE) {
            machine->actions = EC_ACTION_RESEND_CACHED_RESPONSE;
        } else if (result == EC_DEDUP_CONFLICT) {
            lock_machine(machine, EC_FAULT_DEDUP_CONFLICT);
        } else if ((result == EC_DEDUP_FULL) ||
                   (result == EC_DEDUP_INVALID)) {
            lock_machine(machine, EC_FAULT_DEDUP_CAPACITY_EXHAUSTED);
        } else if (result == EC_DEDUP_NEW) {
            /* Order gate (aligned with Python state_machine/core.py): a frame
             * whose seq is <= the last accepted seq is stale/out-of-order and
             * is rejected. Dedup DUPLICATE takes priority (handled above), so
             * this gate only catches old-but-never-seen identities. */
            if ((machine->last_accepted_frame_seq != 0U) &&
                (event->identity.frame_seq <=
                 machine->last_accepted_frame_seq)) {
                machine->actions = EC_ACTION_REJECT_NEW_TASK;
            } else if (machine->state == EC_STATE_WAIT_TASK) {
                machine->current_item = event->identity;
                machine->has_current_item = true;
                machine->ack_consumed = false;
                machine->last_accepted_frame_seq = event->identity.frame_seq;
                machine->state = EC_STATE_VALIDATE_TASK;
                machine->actions = EC_ACTION_ACK_ITEM_ACCEPTED;
            }
        }
    } else if ((machine->state == EC_STATE_VALIDATE_TASK) &&
               (event->type == EC_EVENT_TASK_SAFETY_VALIDATED) &&
               event->content_validated &&
               matches_current_context(machine, event)) {
        machine->state = EC_STATE_EXECUTING;
        machine->actions = EC_ACTION_START_MOTION;
    } else if ((machine->state == EC_STATE_EXECUTING) &&
               (event->type == EC_EVENT_MOTION_DONE) &&
               matches_current_context(machine, event)) {
        machine->state = EC_STATE_WAIT_ITEM_RESULT;
        machine->actions = EC_ACTION_EMIT_MOTION_DONE;
    } else if ((machine->state == EC_STATE_WAIT_ITEM_RESULT) &&
               (event->type == EC_EVENT_ITEM_RESULT_RECORDED) &&
               matches_current_context(machine, event)) {
        machine->state = EC_STATE_WAIT_DISPLAY_ACK;
        machine->actions = EC_ACTION_EMIT_ITEM_RESULT;
    } else if ((machine->state == EC_STATE_WAIT_DISPLAY_ACK) &&
               (event->type == EC_EVENT_DISPLAY_ACK_VALIDATED) &&
               event->content_validated &&
               matches_current_context(machine, event)) {
        machine->state = EC_STATE_PREPARE_BARRIER;
        machine->actions =
            EC_ACTION_PREPARE_BARRIER | EC_ACTION_ACK_DISPLAY_CONSUMED;
        machine->ack_consumed = true;
    } else if ((event->type == EC_EVENT_DISPLAY_ACK_VALIDATED) &&
               matches_current_context(machine, event) &&
               machine->ack_consumed) {
        /* Repeat DISPLAY_ACK for the already-consumed current item: only
         * re-send the cached state, never consume twice (state-machine
         * pseudocode "duplicate ACK -> resend only"). */
        machine->actions = EC_ACTION_RESEND_CACHED_RESPONSE;
    }
    return snapshot(machine);
}
