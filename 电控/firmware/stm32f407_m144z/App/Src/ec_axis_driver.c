#include "ec_axis_driver.h"

#include <stddef.h>   /* NULL */

#include "ec_inputs.h"
#include "ec_servo_test.h"

/* Safety inputs that must inhibit motion.
 * 2026-09-15 用户裁决：X/Y 不装限位开关，原点 = 上电位置，故 6 个限位输入
 * 已从遮罩移除，只保留 ESTOP 反馈。运动越界保护改由软件工作域承担
 * （ec_motion_plan.h EC_MOTION_WORKSPACE_LIMIT_MM10）。
 * 注意：与 ec_demo.c / ec_servo_test.c / ec_step_test.c 的三处遮罩必须保持一致。 */
#define EC_AXIS_SAFETY_MASK  (EC_INPUT_ESTOP_FB)

/* The state machine runs in the main-loop poll; the only thing the port ISR
 * can do concurrently is decrement the counted-step remaining counter, which
 * is already volatile in the port. These members are main-loop only, so they
 * stay non-volatile. */
static ec_axis_state_t state;
static ec_axis_result_t result;
static ec_axis_pick_place_t program;
static uint8_t step_index;            /* next step to execute (0..11) */
static uint8_t program_length;        /* used steps in the current program */
/* Monotonic token source for the 15-second watchdog.  It advances only when
 * the port reports a natural counted-move completion; servo settle and all
 * abort/timeout paths deliberately leave it unchanged. */
static uint32_t completed_move_count;
static uint32_t move_started_at_ms;
static uint32_t move_timeout_ms;
static uint32_t gripper_settle_at_ms;

static bool has_inhibit(uint16_t active_inputs)
{
    return (active_inputs & EC_AXIS_SAFETY_MASK) != 0U;
}

uint32_t ec_axis_mm10_to_steps(ec_axis_t axis, int16_t delta_mm10)
{
    uint32_t ratio;
    uint32_t distance;

    if (axis == EC_AXIS_X) {
        ratio = EC_AXIS_STEPS_PER_MM_X;
    } else if (axis == EC_AXIS_Y) {
        ratio = EC_AXIS_STEPS_PER_MM_Y;
    } else {
        /* Z is a servo; NONE is not an axis. Nothing to convert. */
        return 0U;
    }
    distance = (delta_mm10 < 0) ? (uint32_t)(-(int32_t)delta_mm10)
                                : (uint32_t)delta_mm10;
    return (distance * ratio) / 10U;
}

/* Sign convention of EC_AXIS_STEP_XY_INTERP's signed step targets: a positive
 * target maps to EC_DIRECTION_0. Same convention as ec_motion_plan.h
 * EC_MOTION_POSITIVE_X_DIR / EC_MOTION_POSITIVE_Y_DIR (= EC_DIRECTION_0). */
#define EC_AXIS_INTERP_POSITIVE_DIR EC_DIRECTION_0

static uint32_t axis_steps_from_signed(int32_t target)
{
    return (uint32_t)((target < 0) ? -target : target);
}

static ec_direction_t axis_dir_from_signed(int32_t target)
{
    return (target < 0) ? ((EC_AXIS_INTERP_POSITIVE_DIR == EC_DIRECTION_0)
                           ? EC_DIRECTION_1 : EC_DIRECTION_0)
                        : EC_AXIS_INTERP_POSITIVE_DIR;
}

/* Steps-per-millisecond deadline for the slower leg of a two-axis move:
 * the larger step count decides when the move is over. */
static uint32_t move_timeout_for(uint32_t steps)
{
    return ((steps * UINT32_C(1000)) / EC_AXIS_MOVE_FREQUENCY_HZ) +
           EC_AXIS_MOVE_TIMEOUT_MARGIN_MS;
}

static bool step_is_valid(const ec_axis_step_t *s)
{
    if (s->kind == EC_AXIS_STEP_MOVE) {
        if ((s->axis != EC_AXIS_X) && (s->axis != EC_AXIS_Y)) {
            return false;
        }
        if ((s->direction != EC_DIRECTION_0) &&
            (s->direction != EC_DIRECTION_1)) {
            return false;
        }
        if ((s->steps == 0U) || (s->steps > EC_STEP_MAX_STEPS)) {
            return false;
        }
    } else if (s->kind == EC_AXIS_STEP_MOVE_XY) {
        /* X leg uses axis/steps/direction, Y leg y_steps/y_direction. Either
         * leg may be zero (an axis-aligned dual-axis move is still a legal
         * MOVE_XY), but not both: a zero/zero move is a no-op. */
        if ((s->steps > EC_STEP_MAX_STEPS) ||
            (s->y_steps > EC_STEP_MAX_STEPS)) {
            return false;
        }
        if ((s->steps == 0U) && (s->y_steps == 0U)) {
            return false;
        }
        if ((s->direction != EC_DIRECTION_0) &&
            (s->direction != EC_DIRECTION_1)) {
            return false;
        }
        if ((s->y_direction != EC_DIRECTION_0) &&
            (s->y_direction != EC_DIRECTION_1)) {
            return false;
        }
    } else if (s->kind == EC_AXIS_STEP_XY_INTERP) {
        uint32_t x = axis_steps_from_signed(s->target_x_steps);
        uint32_t y = axis_steps_from_signed(s->target_y_steps);

        if ((x > EC_STEP_MAX_STEPS) || (y > EC_STEP_MAX_STEPS)) {
            return false;
        }
        if ((x == 0U) && (y == 0U)) {
            return false;
        }
    } else if ((s->kind == EC_AXIS_STEP_GRIPPER) ||
               (s->kind == EC_AXIS_STEP_Z_SERVO)) {
        if (s->servo_pulse_us == 0U) return false;
    } else if (s->kind == EC_AXIS_STEP_WAIT) {
        /* 等待步（2026-09-19）：servo_pulse_us 在本步语义为**毫秒**，
         * 见 ec_axis_driver.h 的 EC_AXIS_STEP_WAIT 说明。
         * 0 视为非法 —— "等待 0ms"是无意义步，应当被 program_is_valid 拒掉。 */
        if (s->servo_pulse_us == 0U) return false;
    } else {
        return false;
    }
    return true;
}

static void stop_all(void)
{
    ec_step_port_stop_all();
    ec_servo_port_stop();
    ec_servo_port_stop_z();
    ec_step_port_disable_all();
}

/* A zero-filled slot of the fixed-size program array is an UNUSED step, not a
 * command: the array holds EC_AXIS_PICK_PLACE_STEP_COUNT slots; the
 * interpolated planner emits 6 steps and the production sequential planner
 * emits up to 10 steps, leaving the tail zeroed. A zeroed slot must not be
 * mistaken for a "move 0 steps" command. */
static bool step_is_unused(const ec_axis_step_t *s)
{
    return (s->kind == EC_AXIS_STEP_MOVE) && (s->axis == EC_AXIS_NONE) &&
           (s->direction == EC_DIRECTION_0) && (s->steps == 0U) &&
           (s->y_steps == 0U) && (s->y_direction == EC_DIRECTION_0) &&
           (s->servo_pulse_us == 0U) && (s->target_x_steps == 0) &&
           (s->target_y_steps == 0);
}

/* Validate a whole program and report how many leading steps are used.
 * Only trailing slots may be unused: a used step after an unused one would be
 * silently skipped, so it is rejected instead. */
static bool program_is_valid(const ec_axis_pick_place_t *p, uint8_t *length)
{
    uint8_t i;
    uint8_t used = EC_AXIS_PICK_PLACE_STEP_COUNT;
    bool seen_unused = false;

    for (i = 0U; i < EC_AXIS_PICK_PLACE_STEP_COUNT; ++i) {
        if (step_is_unused(&p->step[i])) {
            if (!seen_unused) {
                seen_unused = true;
                used = i;
            }
            continue;
        }
        if (seen_unused || !step_is_valid(&p->step[i])) {
            return false;
        }
    }
    if (used == 0U) {
        return false;   /* every slot unused: no program at all */
    }
    *length = used;
    return true;
}

/* ── 诊断快照（2026-09-18 新增，纯诊断）────────────────────────────────
 * 详见 ec_axis_driver.h 的说明。**刻意不被 ec_axis_driver_init() 清除** ——
 * 否则故障被重传恢复后证据就没了。 */
static ec_axis_driver_diag_t diag;

static void latch_fault_diag(ec_axis_result_t code, uint32_t now_ms)
{
    diag.last_result = (uint8_t)code;
    diag.last_step_index = step_index;
    diag.last_program_length = program_length;
    diag.last_elapsed_ms = (uint32_t)(now_ms - move_started_at_ms);
    diag.last_timeout_ms = move_timeout_ms;
    if (step_index < program_length) {
        const ec_axis_step_t *s = &program.step[step_index];
        diag.last_kind = (uint8_t)s->kind;
        diag.last_axis = (uint8_t)s->axis;
        diag.last_steps = s->steps;
        diag.last_pulse_us = s->servo_pulse_us;
    } else {
        /* 故障时已越过程序末尾（例如 DONE 判定路径），没有"当前步"可记。 */
        diag.last_kind = 0xFFU;
        diag.last_axis = 0xFFU;
        diag.last_steps = 0U;
        diag.last_pulse_us = 0U;
    }
    ++diag.fault_count;
}

static void fault(ec_axis_result_t code)
{
    latch_fault_diag(code, ec_step_port_now_ms());
    stop_all();
    result = code;
    state = EC_AXIS_STATE_FAULT;
}

/* Per-axis rate for an interpolated dual-axis move: the axis with fewer steps
 * is slowed down proportionally so both legs finish at the same instant. That
 * makes the carriage follow the straight line between the two waypoints at a
 * constant rate - the trajectory Bresenham would produce - expressed through
 * the port's (steps, frequency) contract instead of a per-tick step decision
 * (the port counts a whole move itself; see ec_interp.h note in the report). */
static uint32_t interp_axis_hz(uint32_t steps, uint32_t major_steps)
{
    uint32_t hz;

    if (major_steps == 0U) return EC_AXIS_MOVE_FREQUENCY_HZ;
    hz = (EC_AXIS_MOVE_FREQUENCY_HZ * steps) / major_steps;
    return (hz < EC_STEP_MIN_HZ) ? EC_STEP_MIN_HZ : hz;
}

/* Start an X+Y counted move: both axes are enabled and armed together through
 * the dual-axis port, never as two serial single-axis moves. */
static void start_dual_axis(uint32_t x_steps, ec_direction_t x_direction,
                            uint32_t x_hz, uint32_t y_steps,
                            ec_direction_t y_direction, uint32_t y_hz,
                            uint32_t now_ms)
{
    if (!ec_step_port_set_direction(EC_AXIS_X, x_direction) ||
        !ec_step_port_set_direction(EC_AXIS_Y, y_direction) ||
        !ec_step_port_enable_xy() ||
        !ec_step_port_start_counted_xy(x_steps, x_hz, y_steps, y_hz)) {
        fault(EC_AXIS_RESULT_PORT_FAIL);
        return;
    }
    move_started_at_ms = now_ms;
    move_timeout_ms = move_timeout_for((x_steps > y_steps) ? x_steps : y_steps);
    state = EC_AXIS_STATE_MOVING;
}

static void start_step(uint8_t index, uint32_t now_ms)
{
    const ec_axis_step_t *s = &program.step[index];

    if (s->kind == EC_AXIS_STEP_MOVE) {
        if (!ec_step_port_set_direction(s->axis, s->direction) ||
            !ec_step_port_enable_axis(s->axis) ||
            !ec_step_port_start_counted(s->axis, EC_AXIS_MOVE_FREQUENCY_HZ,
                                        s->steps)) {
            fault(EC_AXIS_RESULT_PORT_FAIL);
            return;
        }
        move_started_at_ms = now_ms;
        move_timeout_ms = move_timeout_for(s->steps);
        state = EC_AXIS_STATE_MOVING;
    } else if (s->kind == EC_AXIS_STEP_MOVE_XY) {
        start_dual_axis(s->steps, s->direction, EC_AXIS_MOVE_FREQUENCY_HZ,
                        s->y_steps, s->y_direction,
                        EC_AXIS_MOVE_FREQUENCY_HZ, now_ms);
    } else if (s->kind == EC_AXIS_STEP_XY_INTERP) {
        uint32_t x_steps = axis_steps_from_signed(s->target_x_steps);
        uint32_t y_steps = axis_steps_from_signed(s->target_y_steps);
        uint32_t major_steps = (x_steps > y_steps) ? x_steps : y_steps;

        start_dual_axis(x_steps, axis_dir_from_signed(s->target_x_steps),
                        interp_axis_hz(x_steps, major_steps),
                        y_steps, axis_dir_from_signed(s->target_y_steps),
                        interp_axis_hz(y_steps, major_steps), now_ms);
    } else if (s->kind == EC_AXIS_STEP_GRIPPER) {
        if (!ec_servo_port_start(s->servo_pulse_us)) {
            fault(EC_AXIS_RESULT_PORT_FAIL);
            return;
        }
        gripper_settle_at_ms = now_ms;
        state = EC_AXIS_STATE_GRIPPING;
    } else if (s->kind == EC_AXIS_STEP_WAIT) {
        /* 等待步（2026-09-19 新增）：**不碰任何硬件**，只把"已到位"的时刻记下来，
         * 由 poll 的 GRIPPING 分支按【本步】时长计时后推进下一步。
         * 用户用途：HOME→PICK 到位后停一段（EC_AXIS_PICK_DWELL_MS=2000ms），
         * 让人肉眼确认滑台确实停在目标物块的位置上，然后再执行夹取。
         * 复用 GRIPPING 状态是有意的：两者语义一致（"停在这里等"），
         * 区别只在时长来源 —— 见 poll 里对 settle_ms 的取法。 */
        gripper_settle_at_ms = now_ms;
        state = EC_AXIS_STATE_GRIPPING;
    } else { /* EC_AXIS_STEP_Z_SERVO */
        /* 2026-09-16：实机单舵机接在 PB10 = TIM2_CH3，不是本分支原本指向的
         * PB11 = TIM2_CH4。两条理由：
         *   1) 台架 SERVO 命令（ec_diag.c）打的也是 PB10，Z 留在 PB10 才能
         *      用现成台架做脉宽标定（P4 是必做项，旧 1100/1900 已作废）；
         *   2) ec_safety_port_stop_all() 只停 PB10 —— Z 在 PB11 时急停停不掉
         *      它，在 PB10 才停得掉。
         * 两个函数都在 ec_servo_test.h 声明，本文件第 4 行已 include。 */
        if (!ec_servo_port_start(s->servo_pulse_us)) {
            fault(EC_AXIS_RESULT_PORT_FAIL);
            return;
        }
        gripper_settle_at_ms = now_ms;
        state = EC_AXIS_STATE_GRIPPING;
    }
}

void ec_axis_driver_init(void)
{
    state = EC_AXIS_STATE_IDLE;
    result = EC_AXIS_RESULT_OK;
    step_index = 0U;
    program_length = 0U;
    completed_move_count = 0U;
    move_started_at_ms = 0U;
    move_timeout_ms = 0U;
    gripper_settle_at_ms = 0U;
}

ec_axis_result_t ec_axis_driver_self_test(void)
{
    /* Placeholder: real driver self-test (stepper fault pin, servo power) is
     * deferred until the hardware interface is defined. Return OK so the
     * production state machine can advance past POST for host testing. */
    return EC_AXIS_RESULT_OK;
}

ec_axis_result_t ec_axis_driver_start_pick_place(
    const ec_axis_pick_place_t *p)
{
    uint8_t length;

    if (state == EC_AXIS_STATE_MOVING || state == EC_AXIS_STATE_GRIPPING) {
        return EC_AXIS_RESULT_BUSY;
    }
    if (p == NULL) return EC_AXIS_RESULT_INVALID_PARAM;

    if (!program_is_valid(p, &length)) {
        return EC_AXIS_RESULT_INVALID_PARAM;
    }

    program = *p;
    program_length = length;
    result = EC_AXIS_RESULT_OK;
    step_index = 0U;
    start_step(0U, ec_step_port_now_ms());
    return result;
}

ec_axis_result_t ec_axis_driver_poll(uint32_t now_ms, uint16_t active_inputs)
{
    ec_axis_t completed_axis;

    if ((state == EC_AXIS_STATE_IDLE) || (state == EC_AXIS_STATE_DONE) ||
        (state == EC_AXIS_STATE_FAULT)) {
        return result;
    }

    if (has_inhibit(active_inputs)) {
        fault(EC_AXIS_RESULT_ABORTED);
        return result;
    }

    /* The port latches safety aborts because its normal remaining counter is
     * also cleared by an abort.  Consume that explicit event before checking
     * for a natural completion. */
    if ((state == EC_AXIS_STATE_MOVING) &&
        ec_step_port_take_counted_abort()) {
        fault(EC_AXIS_RESULT_ABORTED);
        return result;
    }

    if (state == EC_AXIS_STATE_MOVING) {
        /* A counted move is complete only after the port's natural-completion
         * latch is consumed.  Remaining==0 is not sufficient: stop/abort paths
         * clear the same counter. Check this before the deadline so a
         * completion published by the ISR at the boundary is not misclassified
         * as a timeout. */
        if (ec_step_port_take_counted_completion(&completed_axis)) {
            (void)completed_axis;
            ++completed_move_count;
            ++step_index;
            if (step_index >= program_length) {
                stop_all();
                result = EC_AXIS_RESULT_OK;
                state = EC_AXIS_STATE_DONE;
                return result;
            }
            start_step(step_index, now_ms);
        } else if ((uint32_t)(now_ms - move_started_at_ms) >= move_timeout_ms) {
            fault(EC_AXIS_RESULT_TIMEOUT);
            return result;
        }
    } else if (state == EC_AXIS_STATE_GRIPPING) {
        /* 停留时长按【当前步】取（2026-09-19）：
         *   · WAIT 步   → servo_pulse_us，单位 ms（见 EC_AXIS_STEP_WAIT）
         *   · 其余舵机步 → EC_AXIS_GRIPPER_SETTLE_MS（脉宽生效所需的稳定时间）
         * GRIPPING 期间 step_index 仍指向**正在执行的这一步** —— 推进发生在下面的
         * ++step_index，所以此处读到的就是当前步，不会错位。 */
        uint32_t settle_ms =
            (program.step[step_index].kind == EC_AXIS_STEP_WAIT)
                ? (uint32_t)program.step[step_index].servo_pulse_us
                : EC_AXIS_GRIPPER_SETTLE_MS;

        if ((uint32_t)(now_ms - gripper_settle_at_ms) >= settle_ms) {
            ++step_index;
            if (step_index >= program_length) {
                stop_all();
                result = EC_AXIS_RESULT_OK;
                state = EC_AXIS_STATE_DONE;
                return result;
            }
            start_step(step_index, now_ms);
        }
    }

    return result;
}

void ec_axis_driver_stop(void)
{
    stop_all();
    state = EC_AXIS_STATE_IDLE;
    result = EC_AXIS_RESULT_OK;
    step_index = 0U;
    /* Keep completed_move_count monotonic until the next full driver init;
     * an old token must remain stale across a stopped/restarted item. */
}

ec_axis_state_t ec_axis_driver_state(void)
{
    return state;
}

ec_axis_result_t ec_axis_driver_result(void)
{
    return result;
}

uint32_t ec_axis_driver_progress(void)
{
    return (uint32_t)step_index;
}

uint32_t ec_axis_driver_completed_move_count(void)
{
    return completed_move_count;
}

const ec_axis_driver_diag_t *ec_axis_driver_diag(void)
{
    return &diag;
}
