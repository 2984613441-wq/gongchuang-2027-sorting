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
        /* 2026-09-18 BU-FIX: ben ji mei jie ren he an jian, wu fa chan sheng
         * MANUAL_NEW_ROUND_CONFIRMED, lun ci yong yuan jian li bu qi lai.
         * xian zeng yi tiao: shou dao shu mei pai fa lai de ITEM_TASK shi, zhi jie
         * CONG ZHEN NEI DE task_id XUE XI lun ci —— ji "shu mei pai shuo di ji lun
         * jiu shi di ji lun", he xin ceng dui qi, bu zai yi lai ben di ji shu qi.
         * 🔴 an quan tiao jian reng ran bi xu cheng li (danger_area_clear / estop_released
         *    you App ceng yong zhen shi active_inputs ji suan hou tui jin, jian shang).
         * hou xu lun ci reng an != yan ge jiao yan, kua lun chi dao ren wu de fang hu ji xu you xiao. */
        /* 2026-09-18 ZERO-REPLY-FIX（实机定位，别再改回去）：
         * 原条件是 (event->round_id != machine->round_id)。问题：轮次号一旦学到
         * （例如 round_id=1），此后任何一次故障把状态机打回 FAULT_LOCK
         * （ec_app.c 的 15s 无进展看门狗 → EC_EVENT_DEADLINE_EXPIRED → lock_machine()
         * **只改 state、不动 round_id**）之后，同轮次号的 ITEM_TASK 会让两个分支
         * 全部落空，直接落到函数末尾的 return snapshot(machine)：
         *   · 不改 actions（仍是 SAFE_LOCK）→ consume_and_emit 无分支命中
         *   · ec_gateway_feed_byte() 每字节先把 tx_len 清 0 → **一个字节都不发**
         * 现象：板子 1Hz ASCII STATUS 照发、帧字节完全合法，但对 Pi 的每一次重传
         * 统统装死，Pi 侧连一条 FRAME_REJECTED 都看不到（feed_frame 压根没被调用）。
         * 实机复现（FAULT_LOCK 下同端口、同一个 PySerialLink）：
         *   task_id=1（== round_id）→ 4 秒零应答；task_id=2（!= round_id）→ BARRIER_READY。
         * 故去掉 != 限制：FAULT_LOCK 下只要安全条件成立，收到的 ITEM_TASK 就重新
         * 学轮次并重跑 POST —— 一次故障之后链路能自愈，不必人工按 RESET。
         * 安全边界未放宽：ESTOP / MANUAL_RESET 仍然让 danger_area_clear 与
         * estop_released 为假，分支进不去（fail-closed）；POST 自身还会再查一次
         * ESTOP 与电源许可（ec_startup_sequence.c:108-140）。
         * 不会因为重传反复重跑启动序列：本分支一进就把 state 置为 POWER_ON，
         * 后续重传到的是 POWER_ON/HOMING/... 而不是 FAULT_LOCK。 */
        if ((event->type == EC_EVENT_ITEM_TASK_ACCEPTED) &&
            event->danger_area_clear && event->estop_released) {
            ec_dedup_clear_for_verified_new_round(machine->dedup);
            machine->round_id = event->round_id;
            machine->last_accepted_frame_seq = 0U;
            machine->state = EC_STATE_POWER_ON;
            machine->fault_reason = EC_FAULT_NONE;
            machine->actions = EC_ACTION_BEGIN_POST;
            return snapshot(machine);
        }

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
    } else if ((machine->state == EC_STATE_EXECUTING) &&
               (event->type == EC_EVENT_ITEM_RESULT_RECORDED) &&
               matches_current_context(machine, event)) {
        /* Defect #2 fix: Motion failed to start (ec_axis_driver_start_pick_place
         * returned error in ec_app.c:186). Skip MOTION_DONE, go directly to
         * display phase so the failure is shown (interface-contract.md:247). */
        machine->state = EC_STATE_WAIT_DISPLAY_ACK;
        machine->actions = EC_ACTION_EMIT_ITEM_RESULT;
    } else if ((machine->state == EC_STATE_VALIDATE_TASK) &&
               (event->type == EC_EVENT_ITEM_RESULT_RECORDED) &&
               matches_current_context(machine, event)) {
        /* Defect #1 fix: Failed item (e.g. POSITION_UNREACHABLE) detected
         * during validation. No motion will happen, but failure must still be
         * displayed (赛规: "本次分拣信息没有显示前而分拣下一件货物不得分").
         * Go directly to WAIT_DISPLAY_ACK (interface-contract.md:247:
         * "失败结果仍须显示并完成本件渲染确认流程"). */
        machine->state = EC_STATE_WAIT_DISPLAY_ACK;
        machine->actions = EC_ACTION_EMIT_ITEM_RESULT;
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
