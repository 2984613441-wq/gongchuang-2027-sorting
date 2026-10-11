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
 * (when the compile-time source is enabled). Heartbeat,
 * retransmits, ACK/NACK, repeated DISPLAY_ACK and MOTION_DONE never touch it.
 * watchdog_active is true while a window is open. All comparisons use uint32
 * wrap-safe subtraction. */
static uint32_t last_observable_ms;
static bool watchdog_active;
/* 2026-09-22：开窗那一刻的计数移动数快照（配合 ec_app_stop_snapshot_t 诊断续命为何没生效）。 */
static uint32_t moves_at_arm;

#if EC_APP_PROGRESS_SOURCE_ENABLED
/* Progress-source adapter switch (see ec_app.h). A build that explicitly
 * compiles the source in still boots this gate OFF until HIL-PROGRESS-001 has
 * established that the selected completion signal is externally observable.
 * It remains a runtime kill switch after validation. */
static bool progress_source_enabled;
/* Process-monotonic token dedup: only a token strictly newer than the last
 * consumed one may re-base the window. Same token re-delivered, or an older
 * token (including one from a prior item), is dropped. */
static uint32_t last_progress_token;
static bool last_progress_token_valid;
#endif

/* Power permission monitoring: last known state */
static bool power_permission_lost;

/* 2026-09-22：非 fault 路径的「停轴现场」（见 ec_app.h 的 ec_app_stop_snapshot_t）。
 * ec_axis_driver_diag() 只在 fault() 里写，而「轴被孤立」保护走的是 stop() ⇒ 那份读不到。 */
static ec_app_stop_snapshot_t last_stop_snapshot;
/* 上一次的现场：第二次卡顿会覆盖 last（实测丢过一次线索）⇒ 保一份。 */
static ec_app_stop_snapshot_t prev_stop_snapshot;
/* 从转移量里抓到的最近一次锁机原因。ec_transition_t 本来就带着 fault_reason
 * （ec_state_machine.h:85，lock_machine 在 ec_state_machine.c:34 写入），
 * 但此前全链路没有任何地方读过它 ⇒ 真因查不出来。 */
static uint8_t last_lock_fault_reason;
/* 2026-09-22 第三批：最近一次「离开 EXECUTING」的去向与原因。非粘性 —— 只记本次转换，
 * 因为首战/次战都出现过"读到的 FAULT 是上一次留下的"这种误读。 */
static ec_state_t last_app_state;
static uint8_t exec_exit_to;
static uint8_t exec_exit_reason;

/* ── 2026-09-22 A0：位置失效门 ──────────────────────────────────────────
 * 为什么需要它：实测出现「基准已错，系统仍按增量继续执行」⇒ 机器朝同一侧反复猛冲、
 * 顶死堵转（本机 X/Y 无限位开关，没有任何硬件能拦）。
 * 语义（严格 fail-closed）：任何一次异常停止（进 FAULT_LOCK）都把位置判为失效；
 * 失效期间 ec_app_start_motion() 拒绝启动任何新运动，只报失败并显示。
 * 恢复路径唯一：断电 → 手推 X/Y 回负向最里角 → 上电（ec_app_init 里恢复为真），
 * 与项目既有纪律「上电位置即原点」完全一致，不新增任何操作。 */
static bool position_valid;

bool ec_app_last_stop_snapshot(ec_app_stop_snapshot_t *out)
{
    if ((out == NULL) || (last_stop_snapshot.valid == 0U)) {
        return false;
    }
    *out = last_stop_snapshot;
    return true;
}

bool ec_app_stop_snapshot_at(uint8_t which, ec_app_stop_snapshot_t *out)
{
    const ec_app_stop_snapshot_t *src = (which == 1U) ? &prev_stop_snapshot
                                                      : &last_stop_snapshot;
    if ((out == NULL) || (src->valid == 0U)) {
        return false;
    }
    *out = *src;
    return true;
}

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
 * Only bench-validated observable progress may re-base the 15 s window. The
 * production adapter observes the executor's explicit natural-completion
 * progress count; this count is eligible only after HIL-PROGRESS-001
 * establishes that the corresponding actuator completion is externally
 * observable. With EC_APP_PROGRESS_SOURCE_ENABLED 0 this is a hard no-op,
 * fail-closed. When compiled in, the runtime adapter switch remains OFF until
 * that evidence exists. Same-token re-delivery (and any older token) never
 * re-extends. */
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
 * this is locked closed: nothing can enable the token path in a build that
 * was compiled fail-closed. */
void ec_app_progress_source_set_enabled(bool enabled)
{
#if EC_APP_PROGRESS_SOURCE_ENABLED
    progress_source_enabled = enabled;
#else
    (void)enabled; /* compile-time OFF: locked closed (fail-closed) */
#endif
}

/* Build the pick-place program from the current item's pick + drop coordinates
 * (latched by the gateway from ITEM_TASK) and arm the axis driver. The mm->steps
 * / direction mapping and the HOME waypoint live in ec_motion_plan; those are
 * still placeholders pending the real mechanical layout.
 *
 * The pick point comes from ec_gateway_item_pick(). 2026-09-16 台架临时态：
 * 它现在返回一个【固定】抓取点（EC_GATEWAY_PICK_STUB_*，见
 * ec_protocol_gateway.c 里该函数上方的注释），好让机构能在 P3 把抓取点放上
 * wire 之前先跑通全链路。P3 落地后它恢复读 latch 的真实现，这段注释也要改回
 * fail-closed 的说明（未知抓取点绝不能被猜出来）。 */
static void ec_app_start_motion(void)
{
    /* 2026-09-22 P0-FIX（栈溢出）：原本是 364 B 的【栈上】局部。它与
     * ec_app_handle_transition() 里同名的那个合计约 728 B，把 1208 B 的最深
     * 调用链顶出了 1024 B 的栈（交接文档 §1）⇒ 改 static，不占栈。
     * ⚠️ 重入约束（链接图里 ec_app_inject_simple ⇒ ec_app_handle_transition 是
     * (Cycle)，本函数的失败分支里也会 inject_* 重入）：本缓冲只允许在【注入
     * 之前】使用。当前安全 —— ec_axis_driver_start_pick_place() 是【按值拷贝】
     * （ec_axis_driver.c 里 `program = *p`），调用返回后本缓冲即死。 */
    static ec_axis_pick_place_t program;
    ec_axis_result_t result;
    int16_t pick_x_mm10;
    int16_t pick_y_mm10;
    int16_t place_x_mm10;
    int16_t place_y_mm10;
    uint8_t class_id = 0U;
    uint16_t open_pulse_us;

    /* ── 2026-09-22 A0：位置失效门（必须在本函数最前面）─────────────────
     * 实测现象：某次异常停止后，板子仍以为自己在 HOME，于是每一件都按增量朝同一侧
     * 多冲一截 ⇒「一直猛攻一个方向」⇒ 顶死堵转（X/Y 无限位，无硬件可拦）。
     * 处置：位置失效时【拒绝启动任何运动】，复用下面已有的"启动失败 ⇒ 报
     * POSITION_UNREACHABLE ⇒ 显示失败"通路 —— 机器一步都不动，本轮干净结束。
     * 这是一种刻意选择的 fail-closed：宁可这一轮全废，也不让机构去顶死。 */
    if (!position_valid) {
        ec_app_inject_item_result(EC_RESULT_POSITION_UNREACHABLE);
        return;
    }

    /* 2026-09-21：按类别选张开脉宽。类别读不到（未受理/无法读出）⇒ class_id 保持 0
     * ⇒ ec_motion_plan_open_us_for_class() 退回 EC_AXIS_GRIPPER_OPEN_US，
     * 也就是"与改动前逐字节相同"的默认行为。**绝不因为读不到类别就猜一个。** */
    (void)ec_gateway_item_class(&gateway, &class_id);
    open_pulse_us = ec_motion_plan_open_us_for_class(class_id);

    /* Evaluation order matters: the short circuit guarantees ec_motion_plan_build
     * is only reached once both accessors succeeded, so neither the pick nor the
     * place locals can be read uninitialised. */
    if (!ec_gateway_item_target(&gateway, &place_x_mm10, &place_y_mm10) ||
        !ec_gateway_item_pick(&gateway, &pick_x_mm10, &pick_y_mm10) ||
        !ec_motion_plan_build_with_open(&program, pick_x_mm10, pick_y_mm10,
                                        place_x_mm10, place_y_mm10,
                                        open_pulse_us)) {
        /* No latched coordinates, no pick point, or an out-of-workspace
         * waypoint -> unreachable. */
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
     * (design §3.3). The base only moves again on validated actuator-completion
     * tokens (when the source is compiled/enabled) or the first valid
     * DISPLAY_ACK. */
    last_observable_ms = HAL_GetTick();
    watchdog_active = true;
    /* 2026-09-22：记下开窗时的计数移动数 —— 停轴现场靠它算出"窗口期内到底完成了几次
     * 计数移动"（0 次 ⇒ 根本没有续命机会；>0 次 ⇒ 续命被某道门拒了）。 */
    moves_at_arm = ec_axis_driver_completed_move_count();
    /* Do not reset token history at a new window. The executor token is
     * process-monotonic, and an old token must remain stale across items. */
}

static void ec_app_handle_transition(const ec_transition_t *t)
{
    /* 2026-09-22：把锁机原因留下来。状态机一直在写 fault_reason
     * （ec_state_machine.c:34），但全项目没有一处读过 ⇒ 现场只剩 FAULTS=0。 */
    if (t->state == EC_STATE_FAULT_LOCK) {
        last_lock_fault_reason = (uint8_t)t->fault_reason;
        /* A0（2026-09-22，范围已收紧）：只把【运动期间】出的故障判为位置失效 ——
         * 那才是"基准已错却继续按增量冲"的危险情形。
         * ⚠️ 首版写成"进 FAULT_LOCK 就失效"，结果上电阶段 POST 的故障也把位置废掉
         *    ⇒ 一上电就永久拒绝运动（实测：ITEM_TASK 后 50ms 直接报
         *    POSITION_UNREACHABLE ⇒ Pi 侧 "result arrived in wrong state"）。
         * 现在只有"上一状态是 EXECUTING"或"轴正在 MOVING/GRIPPING"才失效。 */
        if ((last_app_state == EC_STATE_EXECUTING) ||
            (ec_axis_driver_state() == EC_AXIS_STATE_MOVING) ||
            (ec_axis_driver_state() == EC_AXIS_STATE_GRIPPING)) {
            position_valid = false;
        }
    }
    /* 2026-09-22 第三批：记录"离开 EXECUTING"这一转换（去向 + 当时原因）。
     * 次战读数 WD=0/SILENT_MS=0 证明第二次卡顿不是 15 秒窗，但看不出是谁把它踢出去的
     * ⇒ 这两个字节就是为那一步准备的。非粘性：只反映最近一次转换。 */
    if ((last_app_state == EC_STATE_EXECUTING) && (t->state != EC_STATE_EXECUTING)) {
        exec_exit_to = (uint8_t)t->state;
        exec_exit_reason = (uint8_t)t->fault_reason;
    }
    last_app_state = t->state;
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
        ec_startup_sequence_reset();   /* 2026-09-18 BU-FIX: POST qian bi xu reset, fou ze zi dong jian lun ci lu jing hui cong zang zhuang tai qi bu dao zhi POST shi bai */
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
        /* 2026-09-22 P0-FIX（栈溢出）：static，理由见 ec_app_start_motion()。
         * 当前重入安全：本缓冲只在下方 ec_motion_plan_build() 用一次，结果收进
         * workspace_ok、program 随即作废（"discarded and nothing is armed"）；
         * 其后的 ec_app_inject_*() 重入即使覆盖它也无人再读。 */
        static ec_axis_pick_place_t program;
        int16_t place_x_mm10, place_y_mm10;
        bool workspace_ok = false;

        /* P0-FIX (2026-09-16): flush the ACK(ACCEPTED) that ec_gateway_feed_byte()
         * already queued, BEFORE the gateway re-entry below discards it.
         *
         * Mechanism: feed_byte queues ACK(ACCEPTED) into tx_buf and returns
         * state == VALIDATE_TASK. Both ec_gateway_feed_byte() and
         * ec_gateway_inject() clear tx_len on entry, so the
         * ec_app_inject_simple()/ec_app_inject_item_result() calls below would
         * silently drop the queued ACK before the trailing ec_app_flush_tx()
         * ever runs. Measured symptom: feeding one valid ITEM_TASK emits exactly
         * one frame (the boot BARRIER_READY) and no ACK at all.
         *
         * Placement is load-bearing - do NOT move this to the top of
         * ec_app_handle_transition(). On paths that perform no gateway re-entry
         * the tx_len clear would never happen and the trailing flush would send
         * the same frame twice (e.g. a duplicated MOTION_DONE).
         *
         * Do NOT fix this instead by removing the tx_len = 0U clears in the
         * gateway: those are its declared contract ("valid until the next
         * dispatch/inject"). Without them every subsequent RX byte would
         * re-flush the stale frame - a 22-byte frame re-sent up to 21 times. */
        ec_app_flush_tx();

        /* Reachability probe on the DROP coordinate. The pick point is not on
         * the wire yet (P3), so the pick arguments deliberately repeat the drop
         * coordinate: this is a probe, not a plan - the resulting program is
         * discarded and nothing is armed here. The pick point is NOT guessed at;
         * the gate that refuses to move without one is ec_app_start_motion().
         *
         * 2026-09-16 UPDATE: After defect #1 fix (VALIDATE_TASK can now handle
         * ITEM_RESULT_RECORDED → WAIT_DISPLAY_ACK transition), it is SAFE to
         * inject failure here if pick point is missing. However, the current
         * design keeps the pick-point gate at START_MOTION (ec_app.c:172-179)
         * for separation of concerns:
         * - Validation checks workspace reachability (this block)
         * - Execution checks data completeness (START_MOTION)
         * This avoids mixing "is the target valid?" with "do we have all inputs?"
         * Both are fail-closed: missing pick → START_MOTION fails → injection
         * → state machine routes to WAIT_DISPLAY_ACK (same as validation failure).
         */
        if (ec_gateway_item_target(&gateway, &place_x_mm10, &place_y_mm10)) {
            workspace_ok = ec_motion_plan_build(&program, place_x_mm10,
                                                place_y_mm10, place_x_mm10,
                                                place_y_mm10);
        }

        /* TODO: Add real safety checks for:
         * - Barrier collision (current barrier position vs target path)
         * - Danger area clear (e/stop, hand sensor, etc.)
         * - All safety interlocks engaged
         * The 2026-09-15 workspace check above only covers reachability of the
         * two commanded waypoints. */

        if (workspace_ok) {
            ec_app_inject_simple(EC_EVENT_TASK_SAFETY_VALIDATED);
        } else {
            /* Coordinate out of bounds or unreachable.
             * Defect #1 坑4 fix: Start watchdog for failed items too. They skip
             * START_MOTION (no motion to execute) but still need 15s protection
             * during WAIT_DISPLAY_ACK phase. Without this, a stuck/dead Pi leaves
             * the system permanently frozen (no timeout). */
            last_observable_ms = HAL_GetTick();
            watchdog_active = true;
            moves_at_arm = ec_axis_driver_completed_move_count();  /* 2026-09-22 同开窗处 */
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
        /* 🔴 2026-09-21 修「轴被孤立」这个洞。
         *
         * 轴驱动器**只在本函数里被轮询**（:504 的 goto 与下面的 ec_axis_driver_poll），
         * 而它的**完成锁存消费**与**超时判据**也**只在 poll() 内部**
         * （App/Src/ec_axis_driver.c:388-402）。
         * ⇒ 一旦 app 在"轴还在走"的时候离开这三个状态，那一动就**永久挂住**：
         *    没人取完成锁存、超时永不触发 ⇒ STATE 永远 MOVING、RESULT 永远 0、
         *    PROGRESS 停在原地，机器静默卡死，而 AXIS 快照看起来"没有故障"。
         *    2026-09-21 现场实测复现（多发一帧 ITEM_TASK 触发 HOMING ⇒ 卡在
         *    PROGRESS=2/MOVES=1/STATE=1，只能靠断电复位恢复）。
         *
         * 处置：离开这三个状态时，把驱动器从 MOVING/GRIPPING 收回到 IDLE
         * （ec_axis_driver_stop() 会 stop_all() 并置 IDLE/OK/step_index=0）。
         * 只在这两个状态下才动，避免每轮 poll 都无谓地碰一次端口。 */
        ec_axis_state_t orphaned = ec_axis_driver_state();

        if ((orphaned == EC_AXIS_STATE_MOVING) ||
            (orphaned == EC_AXIS_STATE_GRIPPING)) {
            /* 2026-09-22：先落现场再停轴 —— ec_axis_driver_stop() 会把 progress 清成 0，
             * 之后再读就只能看到 PROGRESS=0，正是此前"读不出原因"的直接原因。
             * 同时把上一次的记录挪到 prev：第二次卡顿会覆盖 last（已吃过一次亏）。 */
            prev_stop_snapshot = last_stop_snapshot;
            last_stop_snapshot.valid = 1U;
            last_stop_snapshot.app_state = (uint8_t)current_state;
            last_stop_snapshot.driver_state = (uint8_t)orphaned;
            last_stop_snapshot.fault_reason = last_lock_fault_reason;
            last_stop_snapshot.active_inputs = active_inputs;
            last_stop_snapshot.step_index = (uint16_t)ec_axis_driver_progress();
            last_stop_snapshot.moves = ec_axis_driver_completed_move_count();
            last_stop_snapshot.tick_ms = now_ms;
            /* 2026-09-22 第二批：续命三道门的现场（首战读出 FAULT=6=DEADLINE_EXPIRED） */
            last_stop_snapshot.wd_active = watchdog_active ? 1U : 0U;
            last_stop_snapshot.reserved = 0U;
            last_stop_snapshot.last_obs_ms = last_observable_ms;
            last_stop_snapshot.silent_ms = (uint32_t)(now_ms - last_observable_ms);
            last_stop_snapshot.moves_at_arm = moves_at_arm;
            /* 2026-09-22 第三批 */
            last_stop_snapshot.position_valid = position_valid ? 1U : 0U;
            last_stop_snapshot.exec_exit_to = exec_exit_to;
            last_stop_snapshot.exec_exit_reason = exec_exit_reason;
            last_stop_snapshot.pad0 = 0U;
            ec_axis_driver_stop();
        }
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

    /* Only poll axis driver in EXECUTING state. The progress snapshot surrounds
     * the driver poll so a token can only come from a newly completed actuator
     * step reported by the executor; no timer, heartbeat, log, retry or ACK path
     * can reach this call. */
    if (current_state != EC_STATE_EXECUTING) {
        goto check_watchdog;
    }

#if EC_APP_PROGRESS_SOURCE_ENABLED
    {
        uint32_t progress_before = ec_axis_driver_completed_move_count();

    (void)ec_axis_driver_poll(now_ms, active_inputs);

        if (ec_axis_driver_completed_move_count() > progress_before) {
            /* The driver increments this source only after a counted X/Y move
             * has raised the port's normal-completion latch. Servo settle,
             * timers, retries, and aborts cannot reach this call. */
            ec_app_note_observable_progress(
                ec_axis_driver_completed_move_count());
        }
    }
#else
    (void)ec_axis_driver_poll(now_ms, active_inputs);
#endif
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

check_watchdog:
    /* Rolling no-motion watchdog check (design §3.3): the window closes when
     * the machine stays without observable progress for 15 s. This check is
     * deliberately after ec_axis_driver_poll(): a completion observed at the
     * boundary gets first chance to re-base the window. The base is
     * last_observable_ms (motion start, or the last validated completion
     * token). uint32 wrap-safe subtraction keeps this correct across the
     * 49.7-day tick rollover. */
    if (watchdog_active) {
        /* 🔴 2026-09-22 修「运动期间误判失活」。
         *
         * 现场证据（A0b 那版仪表的 4 行读数，第一件就死）：
         *   STOPCAUSE=ORPHAN APP_STATE=0 DRV_STATE=1(MOVING) FAULT=6 STEP=7
         *   WINDOW WD=0 SILENT_MS=0 LAST_OBS=TICK_MS MOVES_AT_ARM=0 MOVES=3
         *   EXIT EXEC_EXIT_TO=0 EXEC_EXIT_REASON=6(DEADLINE_EXPIRED)
         * ⇒ 运动只走完 3 条腿（≈3 秒）、机器正在 MOVING，判据却按"失活 15 秒"锁了机；
         *   而且 WD=0 与 SILENT_MS=0 与"静默 15 秒"字面矛盾 ⇒ 记账不可信。
         *
         * 赛规口径（要求汇总.md:102 / R-R04，PDF 第 12 页）：
         *   「超过 15 秒装置【没有动作】，或没有显示本次分拣信息，本轮比赛结束」
         * ⇒ 装置【正在动】时"没有动作"不成立 ⇒ 本判据在运动期间【本就不该判】。
         *
         * 处置：轴处于 MOVING/GRIPPING 时不计时、不判。（轴停止后窗口仍照原样计时，
         * 显示阶段的剩余预算语义不变。）注意此处必须现取状态：本标签也会被上面的
         * `goto check_watchdog` 跳到，那条路径上局部变量 axis_state 未赋值。 */
        const ec_axis_state_t ax_now = ec_axis_driver_state();

        if ((ax_now != EC_AXIS_STATE_MOVING) &&
            (ax_now != EC_AXIS_STATE_GRIPPING) &&
            ((uint32_t)(now_ms - last_observable_ms) >= UINT32_C(15000))) {
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
    /* 2026-09-22 A0：上电（含复位键）即视为"位置可信" —— 与既有纪律一致
     * （上电前必须手推到负向最里角）。异常停止会把它清掉，届时只能靠重新上电恢复。 */
    position_valid = true;
    last_app_state = EC_STATE_FAULT_LOCK;
    exec_exit_to = 0U;
    exec_exit_reason = 0U;
#if EC_APP_PROGRESS_SOURCE_ENABLED
    /* 🔴 2026-09-21 用户裁决：随编译开关一起打开（三处必须同时）。见 ec_app.h
     * 的说明：打开后每次"X/Y 计数移动自然完成"即续命，回到赛规口径。 */
    progress_source_enabled = true;
    last_progress_token_valid = false;
#endif

    ec_axis_driver_init();
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

    /* 2026-09-18 BU-FIX: ba BEN LUN de zhen shi an quan zhuang tai tui jin wang guan.
     * wang guan zai gou zao shi jian shi hui dai shang ta men (jian shang last_*), er
     * bu zai ying bian ma false —— fou ze zhuang tai ji yong yuan wu fa zai
     * FAULT_LOCK xia tong guo an quan tiao jian, lun ci jian li bu qi lai.
     * 🔴 zhe liang ge zhi jie ding lun ci neng bu neng jian li, JUE DUI bu ke xie si true. */
    ec_gateway_update_safety_state(&gateway,
        ((inputs.active_mask & EC_INPUT_ESTOP_FB) == 0U) &&
        ((inputs.active_mask & EC_INPUT_MANUAL_RESET) == 0U),
        (inputs.active_mask & EC_INPUT_ESTOP_FB) == 0U);

    ec_app_poll_start_button(inputs.active_mask);
    ec_app_poll_startup_sequence(now_ms, inputs.active_mask);
    ec_app_poll_motion(now_ms, inputs.active_mask);

    /* P0-FIX: Poll UART RX ring buffer in main loop, not in ISR.
     * Process all available bytes serially to avoid ISR recursion.
     * 2026-09-18 RX-DEAF-FIX: 这个循环现在真的有字节了（以前 ec_board_uart_rx_available()
     * 恒返回 false），所以必须加上界：ISR 会持续往缓冲里补字节，无界排空在对方一直
     * 占用线路时可能永远不返回，而 HAL_IWDG_Refresh() 在 main.c 的循环里、排空之后
     * —— 那样就是看门狗复位。
     * 缓冲一次最多存 EC_BOARD_RX_CAPACITY-1 字节，故按容量收敛即可在本次 poll 内
     * 排空进入时已到达的全部字节；多出来的留到下一次 poll。 */
    {
        uint16_t drained = 0U;

        while (ec_board_uart_rx_available() &&
               (drained < EC_BOARD_RX_CAPACITY)) {
            ec_app_on_uart_rx_byte(ec_board_uart_rx_read());
            ++drained;
        }
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
