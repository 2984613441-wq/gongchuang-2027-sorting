#ifndef EC_AXIS_DRIVER_H
#define EC_AXIS_DRIVER_H

/* Production pick-place executor (stm32-state-machine-pseudocode.md sec. 2
 * "AxisDriver" + sec. 6 "EXECUTE_PICK_PLACE").
 *
 * This is a polled state machine that drives the fixed-size pick-place
 * sequence through the existing `ec_step_port_*` (PWM + counted steps) and
 * `ec_servo_port_*` (gripper) ports. It does NOT depend on the diagnostic
 * `ec_step_test` / `ec_motion_test_*` machinery; both share only the port
 * layer, and the "one counted move at a time" invariant is enforced by the
 * port's own re-entry guard (P2-5).
 *
 * NOTE: the per-move axis/direction/step-count are supplied by the caller
 * (they are the product of the pixel->steps coordinate mapping, which is
 * BLOCKED on the mechanical transmission + A4988 MS1-3 microstepping). The
 * constants below are placeholders and are explicitly NOT calibrated.
 */

#include "ec_step_test.h"

#include <stdbool.h>
#include <stdint.h>

/* --- Config constants ---
 * steps_per_mm: 2026-09-15 用户裁决 —— 以 165mm 单腿行程为准。
 * 依据 docs/reports/2026-08-27-stm32-xy-demo-handoff.md:13,21：
 *   单腿行程 16.5s = 165mm = 13200 步  =>  13200 / 165 = 80 steps/mm
 * 与 ec_motion_plan.h:8-9 注释自述的 "80 steps/mm" 一致（此前后者与 100 冲突）。
 * 传动：GT2 20 齿同步带 + 16 微步。
 * 仍属理论/逼近值 —— 卡尺实测后若不符，须同时改本处与 ec_motion_plan 注释。 */
#define EC_AXIS_STEPS_PER_MM_X UINT32_C(80)
#define EC_AXIS_STEPS_PER_MM_Y UINT32_C(80)
/* 行程（2026-09-15 用户裁决：**165mm 为全程**，不是单腿）。
 * 本坐标系原点 = 装置中心，故单侧可达 = 165/2 = 82.5mm。
 * 见 ec_motion_plan.h 的域说明与 EC_MOTION_REACH_LIMIT_MM10。 */
#define EC_AXIS_TRAVEL_TOTAL_MM UINT32_C(165)
#define EC_AXIS_MOVE_FREQUENCY_HZ UINT32_C(500)
/* —— Z 轴 / 夹爪舵机脉宽（2026-09-15：用户确认为【实测值】，不再是占位）——
 *
 * 实测事实（发给机械组.txt:29，该文件 :5 标明"电控已有的信息（实测）"）：
 *      1100us = 张开 + 下降
 *      1900us = 闭合 + 上升
 *   —— 单舵机联动：一个舵机同时决定"升降"与"夹爪开合"。
 *
 * ⚠️ 2026-09-15 数值更正：【张开 + 下降 实为 1100us，不是 1000us】。
 *      原记录文件 发给机械组.txt:29 写的是 1000，该 1000 系笔误，
 *      经用户 2026-09-15 当面口头更正为 1100。故 GRIPPER_OPEN_US 与
 *      Z_DOWN_US 同时改为 1100（两者是同一个联动动作）。
 *      闭合/上升 1900us 不变。
 *
 * ⚠️ 2026-09-15 方向修正（更早一次）：代码曾把 Z 升降这一对写反
 *      （Z_UP_US=1000 / Z_DOWN_US=1900），与同文件的 GRIPPER_OPEN_US 自相矛盾。
 *      已按记录纠正为"下降=1000us / 上升=1900us"；其中 1000 又按上面
 *      的数值更正改为 1100us。
 *      若实机舵机摇臂是反向安装，则把这两行的数值换回来即可（反向同理）。
 *
 * 脉宽数值本身已实测；剩余待实测的是机械行程（升降全行程、夹爪开合距离）。 */
#define EC_AXIS_GRIPPER_OPEN_US UINT16_C(900)
#define EC_AXIS_GRIPPER_CLOSE_US UINT16_C(1900)
#define EC_AXIS_GRIPPER_SETTLE_MS UINT32_C(200)
/* How long to wait for a servo pulse to take effect before advancing to the
 * next program step. GRIPPER and Z_SERVO share the same single-servo linkage
 * mechanics, so they share the same settle time (alias, not a second value). */
#define EC_AXIS_SERVO_SETTLE_MS EC_AXIS_GRIPPER_SETTLE_MS
/* 🔴 2026-09-19 实测标定（用户在现场逐档目视，台架 SERVO PB10 Pxxxx）：
 *
 *   增量扫描结果（`工具/pi_servo_sweep.py`，P1000→P1900 每档停 3 秒）：
 *     · 脉宽越大 → 夹爪越【闭合】、升降越【下降】（单调，无死区）
 *     · P900 / P950 已验证可用且不发堵转异响 ⇒ 开度比 P1000 更大
 *   故"完全张开"= 900（或更低，尚未继续下探）。原值 1100 **并非最大开度** ——
 *   也就是说此前落料释放时夹爪其实没开到底，容易释放不干脆。
 *
 *   ⚠️ 只把开度端从 1100 改到 900；闭合端 1900 经现场确认已能完全夹紧，未动。
 *   ⚠️ 900 是"已验证可用的最低值"，不是"机械端点"（P900 无堵转声说明仍有行程余量）。
 *      若日后需要更大开度，可按同一方法加 P850/P800 继续小步下探，**不要一次跳远**：
 *      越过机械端点会持续堵转、电流拉满、发热甚至烧舵机。
 *   ⚠️ 台架命令的两道闸（ec_diag.c 的 servo_pulse_from_command 与
 *      ec_servo_test.c 的 is_allowed_pulse）已同步加入 900/950。 */
#define EC_AXIS_Z_DOWN_US EC_AXIS_GRIPPER_CLOSE_US  /* 取料点：闭合 + 下压（夹住）= 1900 */
#define EC_AXIS_Z_UP_US   EC_AXIS_GRIPPER_OPEN_US   /* 落料点：张开 + 抬起（释放）= 900 */
/* Counted-move timeout margin, mirroring ec_step_test.c. */
#define EC_AXIS_MOVE_TIMEOUT_MARGIN_MS UINT32_C(1000)

typedef enum {
    EC_AXIS_RESULT_OK = 0,
    EC_AXIS_RESULT_BUSY,
    EC_AXIS_RESULT_INVALID_PARAM,
    EC_AXIS_RESULT_INHIBITED,
    EC_AXIS_RESULT_TIMEOUT,
    EC_AXIS_RESULT_ABORTED,
    EC_AXIS_RESULT_PORT_FAIL
} ec_axis_result_t;

typedef enum {
    EC_AXIS_STATE_IDLE = 0,
    EC_AXIS_STATE_MOVING,
    EC_AXIS_STATE_GRIPPING,
    EC_AXIS_STATE_DONE,
    EC_AXIS_STATE_FAULT
} ec_axis_state_t;

typedef enum {
    /* Single-axis counted move: axis/direction/steps. */
    EC_AXIS_STEP_MOVE = 0,
    EC_AXIS_STEP_GRIPPER,
    EC_AXIS_STEP_Z_SERVO,
    /* Legacy dual-axis counted move (2026-09-15 双轴路线): X and Y start
     * together and run concurrently. Retained for existing diagnostics/tests;
     * the production planner now emits EC_AXIS_STEP_MOVE pairs. X leg =
     * axis/direction/steps, Y leg = y_direction/y_steps. The kind is appended
     * (not inserted) so the existing enumerators keep their values. */
    EC_AXIS_STEP_MOVE_XY,
    /* Dual-axis interpolated move: target_x_steps/target_y_steps are SIGNED
     * per-axis increments in steps, so one step can express an arbitrary
     * diagonal in either quadrant. */
    EC_AXIS_STEP_XY_INTERP,
    /* 🔴 2026-09-19 新增：**纯等待步**（不驱动任何硬件，只占时间）。
     *
     * 用途（用户实机要求）：在 HOME→PICK 到位之后、Z_DOWN(闭合夹取)之前停一段，
     * 让人肉眼确认滑台确实停在目标物块的位置上，然后再执行夹取。
     *
     * 时长承载方式：**复用 servo_pulse_us 字段**，单位改为 **ms**。
     *   理由：这样不必扩 ec_axis_step_t（不必动其他步类型的初始化）、
     *   不影响已有枚举值（本值追加在末尾，符合上面 :112 的约定）、
     *   也不影响 program_is_valid 的长度推导（WAIT 步的 kind 非 MOVE，
     *   不会被 step_is_unused() 误判为空槽）。
     *   GRIPPER / Z_SERVO 的 servo_pulse_us 语义仍是**脉宽(us)**，只有 WAIT 是 ms。
     *
     * 必须有值：WAIT 步 servo_pulse_us == 0 视为非法（会被 program_is_valid 拒掉），
     * 避免"等待 0ms"这种无意义步混进程序。 */
    EC_AXIS_STEP_WAIT
} ec_axis_step_kind_t;

/* 到位后、夹取前的默认停留时长（ms）。见 EC_AXIS_STEP_WAIT 的说明。
 * ⚠️ 它会计入整链时长，须与 ec_app.c:553 的 15000ms 失活窗口对账：
 *    当前整链约 11.1s（accel/decel 已提到 10000 Hz/s），加本值后约 13.1s。 */
#define EC_AXIS_PICK_DWELL_MS UINT32_C(2000)

/* One step of the pick-place program: a single-axis or dual-axis counted move,
 * or one command to the single linked Z/gripper servo. EC_AXIS_STEP_GRIPPER and
 * EC_AXIS_STEP_Z_SERVO both drive that SAME servo -- one LDX-335MG on
 * PB10 = TIM2_CH3, lift and jaw linked, one single degree of freedom. They are
 * two step kinds, not two servos (see the pulse-width block above). */
typedef struct {
    ec_axis_step_kind_t kind;
    ec_axis_t axis;            /* MOVE / MOVE_XY (X leg) */
    ec_direction_t direction;  /* MOVE / MOVE_XY (X leg) */
    uint32_t steps;            /* MOVE / MOVE_XY (X leg), <= EC_STEP_MAX_STEPS */
    uint16_t servo_pulse_us;   /* GRIPPER / Z_SERVO only */
    uint32_t y_steps;          /* MOVE_XY: Y leg, <= EC_STEP_MAX_STEPS */
    ec_direction_t y_direction;/* MOVE_XY: Y leg */
    int32_t target_x_steps;    /* XY_INTERP: signed X increment, steps */
    int32_t target_y_steps;    /* XY_INTERP: signed Y increment, steps */
} ec_axis_step_t;

/* Fixed-size program storage for the production pick-place sequence. The
 * sequential XY planner emits up to 10 used steps:
 *   X/Y HOME->PICK, Z down, Z up,
 *   X/Y PICK->PLACE, Z down, Z up,
 *   X/Y PLACE->HOME.
 *
 * The array has one spare slot so every emitted program keeps a zero-filled
 * tail. A zeroed slot is an UNUSED step (not "move 0 steps"): the driver
 * validates only the leading used steps and tolerates the unused tail. Only
 * the tail may be zeroed - a used step after an unused one is rejected. */
#define EC_AXIS_PICK_PLACE_STEP_COUNT 11U

typedef struct {
    ec_axis_step_t step[EC_AXIS_PICK_PLACE_STEP_COUNT];
} ec_axis_pick_place_t;

void ec_axis_driver_init(void);

/* Convert a signed displacement in 0.1 mm (mm10) into a NON-NEGATIVE step
 * count for X or Y, using EC_AXIS_STEPS_PER_MM_X/Y. The sign is deliberately
 * dropped: direction is carried separately by ec_axis_step_t.direction, so the
 * caller pairs this with the sign of its own delta. Returns 0 for EC_AXIS_Z
 * (servo, not a stepper) and EC_AXIS_NONE. */
uint32_t ec_axis_mm10_to_steps(ec_axis_t axis, int16_t delta_mm10);

ec_axis_result_t ec_axis_driver_self_test(void);
ec_axis_result_t ec_axis_driver_start_pick_place(
    const ec_axis_pick_place_t *program);
ec_axis_result_t ec_axis_driver_poll(uint32_t now_ms, uint16_t active_inputs);
void ec_axis_driver_stop(void);
ec_axis_state_t ec_axis_driver_state(void);
ec_axis_result_t ec_axis_driver_result(void);
/* Number of completed program steps (0..EC_AXIS_PICK_PLACE_STEP_COUNT). This
 * includes servo-settle steps and is retained for diagnostics/state tests; it
 * is not the 15-second watchdog token source. */
uint32_t ec_axis_driver_progress(void);

/* Number of counted X/Y actuator moves completed through the port's normal
 * completion latch. Servo settle, timeout, ESTOP abort, and externally stopped
 * counters do not increment this value. */
uint32_t ec_axis_driver_completed_move_count(void);

/* ── 生产路径诊断快照（2026-09-18 新增，纯诊断）────────────────────────
 * 背景：STATUS 的 STEP_* 字段全部来自诊断模块 ec_motion_test_*（ec_diag.c:383-397），
 * 生产运动路径（本模块）在线上此前**零可观测性**。实机现象「板子受理 ITEM_TASK 后
 * 5 秒内进 FAULT_LOCK、且从不发 MOTION_DONE」因此无法从板子外部定位。
 *
 * 本结构体是**只读诊断快照**，不参与任何控制流，不改变任何运动行为。
 *
 * 为什么必须"锁存"：故障后板子会被 ITEM_TASK 重传恢复，而 ec_axis_driver_init()
 * 会把 state→IDLE、result→OK，瞬时值会丢掉证据。故 fault() 在此锁存故障现场，
 * 且 ec_axis_driver_init() **刻意不清除**它 —— 于是可以在链路停下之后
 * （用新增的 `AXIS` 诊断命令）回读故障原因。 */
typedef struct {
    uint32_t fault_count;         /* 累计进入 fault() 的次数（init 不清零） */
    uint8_t  last_result;         /* ec_axis_result_t：TIMEOUT/ABORTED/PORT_FAIL/... */
    uint8_t  last_step_index;     /* 故障时执行到第几步（0-based） */
    uint8_t  last_program_length; /* 故障时程序总步数 */
    uint8_t  last_kind;           /* ec_axis_step_kind_t；0xFF=故障时已越过程序末尾 */
    uint8_t  last_axis;           /* ec_axis_t；0xFF=同上 */
    uint32_t last_steps;          /* 该步步数（MOVE 类才有意义） */
    uint32_t last_pulse_us;       /* 该步舵机脉宽（SERVO 类才有意义） */
    uint32_t last_elapsed_ms;     /* 该步 start → 故障的毫秒数 */
    uint32_t last_timeout_ms;     /* 该步的超时线（便于与 elapsed 对比） */
} ec_axis_driver_diag_t;

const ec_axis_driver_diag_t *ec_axis_driver_diag(void);

#endif
