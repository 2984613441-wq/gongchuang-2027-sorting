#include "ec_motion_plan.h"

#include <stddef.h>
#include <string.h>

static ec_direction_t opposite_direction(ec_direction_t d)
{
    return (d == EC_DIRECTION_0) ? EC_DIRECTION_1 : EC_DIRECTION_0;
}

/* Convert one axis's waypoint-to-waypoint displacement (both mm10, device-
 * center frame) into a (positive steps, direction) pair. */
static void plan_axis_move(ec_axis_t axis, int16_t from_mm10, int16_t to_mm10,
                           ec_direction_t positive_dir,
                           uint32_t *steps, ec_direction_t *direction)
{
    int16_t delta_mm10 = (int16_t)(to_mm10 - from_mm10);

    *steps = ec_axis_mm10_to_steps(axis, delta_mm10);
    *direction = (delta_mm10 >= 0) ? positive_dir
                                   : opposite_direction(positive_dir);
}

/* Append one counted move for a single axis. A zero displacement is omitted:
 * the driver rejects zero-step EC_AXIS_STEP_MOVE commands, and omitting it
 * keeps every used step contiguous before the zero-filled tail. */
static bool append_axis_move(ec_axis_pick_place_t *out, uint8_t *next_step,
                             ec_axis_t axis, int16_t from_mm10,
                             int16_t to_mm10, ec_direction_t positive_dir)
{
    ec_axis_step_t *step;
    uint32_t steps;
    ec_direction_t direction;

    plan_axis_move(axis, from_mm10, to_mm10, positive_dir,
                   &steps, &direction);
    if (steps == 0U) {
        return true;
    }
    if (*next_step >= EC_AXIS_PICK_PLACE_STEP_COUNT) {
        return false;
    }

    step = &out->step[*next_step];
    step->kind = EC_AXIS_STEP_MOVE;
    step->axis = axis;
    step->direction = direction;
    step->steps = steps;
    ++(*next_step);
    return true;
}

/* Append one waypoint as two serial single-axis moves.
 *
 * 顺序策略（2026-09-21 用户裁决「带料腿 Y 优先」）：
 *   · force_y_first == false ⇒ 跟随编译期默认顺序 EC_MOTION_XY_ORDER_X_FIRST；
 *   · force_y_first == true  ⇒ 强制「先 Y 后 X」。
 * **只有 PICK→PLACE 那条带料腿传 true。**
 *
 * 2026-09-21 用户现场裁决：**三条腿全部「先 Y 后 X」**（EC_MOTION_XY_ORDER_X_FIRST = 0）。
 *   · HOME→PICK（空爪）：先竖着走到目标那一行，再横着过去。用户口径原文：
 *     「要先 Y 先走，Y 先走到那一行之后，然后再变脉宽，然后再去夹取；
 *       如果是 X 先走，他在变脉宽的过程当中很可能扫到其他物块。」
 *   · PICK→PLACE（夹着件）：先沿 +Y 退出托盘、横移留在盘外 —— 这条是硬要求
 *     （夹着件在托盘上方沿 X 横穿会把同排其他件刮飞）。
 *   · PLACE→HOME（空爪）：先竖着下来，再在最里那条线上横回去。
 *
 * ⚠️ **以现场为准**：静态分析曾倾向"两条空爪腿保持 X 先"（理由是 leg1 的 X 段走在
 *    y = HOME_Y = −97.5、落在件区之外的近壁带里），但用户人在机器旁、现场判定 X 先会碰到
 *    ⇒ 按现场裁决置 0。回退只需把该宏改回 1 重编。
 *
 * 刻意**不写 #if**：若用 #if 选臂，宏为 0 的那一支里 force_y_first 不会被读取，
 * 主机测试的 -Wall -Wextra -Werror 会以 unused-parameter 直接编译失败。 */
static bool append_ordered_xy(ec_axis_pick_place_t *out, uint8_t *next_step,
                              int16_t from_x, int16_t from_y,
                              int16_t to_x, int16_t to_y,
                              bool force_y_first)
{
    const bool y_then_x = force_y_first || (EC_MOTION_XY_ORDER_X_FIRST == 0);

    if (y_then_x) {
        if (!append_axis_move(out, next_step, EC_AXIS_Y, from_y, to_y,
                              EC_MOTION_POSITIVE_Y_DIR)) {
            return false;
        }
        return append_axis_move(out, next_step, EC_AXIS_X, from_x, to_x,
                                EC_MOTION_POSITIVE_X_DIR);
    }
    if (!append_axis_move(out, next_step, EC_AXIS_X, from_x, to_x,
                          EC_MOTION_POSITIVE_X_DIR)) {
        return false;
    }
    return append_axis_move(out, next_step, EC_AXIS_Y, from_y, to_y,
                            EC_MOTION_POSITIVE_Y_DIR);
}

/* True when one waypoint (both axes, 0.1mm) sits inside its axis bounds.
 * 四个边界显式传入（2026-09-19「甲′」）：可达域已非对称 —— 负端是 HOME 压线的
 * 机械最里角，正端另让 5mm，二者不再是同一个数，故不能再用 ±limit 的对称写法。
 * 协议合法域仍是 ±1450 对称，调用处传 -1450/+1450 即可。 */
static bool within_limits(int16_t x_mm10, int16_t y_mm10,
                          int16_t x_min, int16_t x_max,
                          int16_t y_min, int16_t y_max)
{
    return (x_mm10 >= x_min) && (x_mm10 <= x_max) &&
           (y_mm10 >= y_min) && (y_mm10 <= y_max);
}

/* ────────────────────────────────────────────────────────────────────────────
 * 2026-10-23 新增：XY 插补腿（两轴同时起步，取代 append_ordered_xy 的两步序列）
 *
 * 与 append_ordered_xy 的区别：
 *   append_ordered_xy  → 生成 2 个 EC_AXIS_STEP_MOVE（先一个轴走完，再另一个）
 *   append_xy_interp   → 生成 1 个 EC_AXIS_STEP_XY_INTERP（两轴同时启动、各自计数）
 *
 * 收益：① 真·同时动（不再是 X 走完 Y 才走）
 *       ② 耗时由 t_x + t_y 降为 max(t_x, t_y)
 *       ③ 步数从 2 步降为 1 步 ⇒ 整个计划从 12 步降到 9 步，容量更宽裕
 *
 * ⚠️ 轨迹形状的诚实说明（2026-10-23 读驱动确认）：
 *   ec_axis_driver.c 的 XY_INTERP 分支会调 interp_axis_hz() 按【步数比】给两轴
 *   不同频率，看上去像要合成直线；但那条频率最终只作为
 *   ec_step_port_start_counted_xy() 的 frequency_hz 传入，而
 *   ec_board_stm32.c:start_axis_counted() 里它**只在曲线规划失败时兜底**，
 *   规划成功时两轴都用全局 cruise（现 8000Hz）。
 *   ⇒ **实际效果 = 两轴同时起步、各自按步数走完、短腿先停**（折线，不是几何直线）。
 *   ⇒ 若要真·直线，需给两轴分别指定 cruise（后续工作，见 T8 报告"未验证"节）。
 *   ⇒ 但本函数的收益①②③与"一起动"的要求**不受影响**。
 *
 * 符号约定：target_x_steps / target_y_steps 是**有符号增量**，
 *   正值 → EC_AXIS_INTERP_POSITIVE_DIR（当前 = DIR0，与 EC_MOTION_POSITIVE_*_DIR 一致）。
 *   两处宏必须保持同向，否则插补腿方向会整体翻转。
 * ──────────────────────────────────────────────────────────────────────────── */
static bool append_xy_interp(ec_axis_pick_place_t *out, uint8_t *next_step,
                             int16_t from_x, int16_t from_y,
                             int16_t to_x, int16_t to_y)
{
    ec_axis_step_t *step;
    int32_t delta_x;
    int32_t delta_y;

    if (*next_step >= EC_AXIS_PICK_PLACE_STEP_COUNT) {
        return false;
    }

    delta_x = (int32_t)to_x - (int32_t)from_x;
    delta_y = (int32_t)to_y - (int32_t)from_y;

    /* 两轴增量为零 ⇒ 空移动，驱动会拒绝（ec_axis_driver.c 检查 x==0 && y==0）。
     * 计划里不该出现，直接 fail-closed，避免把非法步交给驱动。 */
    if ((delta_x == 0) && (delta_y == 0)) {
        return false;
    }

    step = &out->step[*next_step];
    (void)memset(step, 0, sizeof(*step));
    step->kind = EC_AXIS_STEP_XY_INTERP;
    step->axis = EC_AXIS_NONE;
    step->steps = 0U;
    step->direction = EC_DIRECTION_0;
    step->servo_pulse_us = 0U;
    step->target_x_steps = (delta_x * (int32_t)EC_AXIS_STEPS_PER_MM_X) / 10;
    step->target_y_steps = (delta_y * (int32_t)EC_AXIS_STEPS_PER_MM_Y) / 10;

    *next_step += 1U;
    return true;
}

static void set_z_servo(ec_axis_step_t *step, uint16_t pulse_us)
{
    step->kind = EC_AXIS_STEP_Z_SERVO;
    step->servo_pulse_us = pulse_us;
}

static bool append_z_servo(ec_axis_pick_place_t *out, uint8_t *next_step,
                           uint16_t pulse_us)
{
    if (*next_step >= EC_AXIS_PICK_PLACE_STEP_COUNT) {
        return false;
    }
    set_z_servo(&out->step[*next_step], pulse_us);
    ++(*next_step);
    return true;
}

/* Append a PURE WAIT step: drives no hardware, only consumes time.
 * The duration rides in servo_pulse_us as **milliseconds** (see
 * EC_AXIS_STEP_WAIT in ec_axis_driver.h -- GRIPPER/Z_SERVO keep us there).
 * Used to pause at the pick point so a human can confirm the carriage really
 * stopped on the target object before the gripper closes. */
static bool append_wait(ec_axis_pick_place_t *out, uint8_t *next_step,
                        uint16_t dwell_ms)
{
    if (*next_step >= EC_AXIS_PICK_PLACE_STEP_COUNT) {
        return false;
    }
    out->step[*next_step].kind = EC_AXIS_STEP_WAIT;
    out->step[*next_step].servo_pulse_us = dwell_ms;
    ++(*next_step);
    return true;
}

/* ── 按类别选张开脉宽（2026-09-21 现场实测，用户裁决）──────────────────────
 * 索引 = class_id（1..6）；0 / 未知 / 越界一律退回 EC_AXIS_GRIPPER_OPEN_US。
 * 表值来源见 ec_motion_plan.h 的 EC_MOTION_OPEN_US_* 与
 * docs/交付/2026-09-21/现场脉宽标定记录-2026-09-21.md。 */
uint16_t ec_motion_plan_open_us_for_class(uint8_t class_id)
{
    uint16_t open_us;

    switch (class_id) {
    case 1U:  /* 青-正方体 */
    case 2U:  /* 绿-正方体 */
        open_us = EC_MOTION_OPEN_US_CUBE;
        break;
    case 3U:  /* 红-三棱柱 */
    case 4U:  /* 蓝-三棱柱 */
        open_us = EC_MOTION_OPEN_US_PRISM;
        break;
    case 5U:  /* 黑-圆柱 */
    case 6U:  /* 橙-圆柱 */
        open_us = EC_MOTION_OPEN_US_CYLINDER;
        break;
    default:
        return EC_AXIS_GRIPPER_OPEN_US;  /* 未知/未受理 ⇒ 退回默认，绝不猜类别 */
    }
    /* 防误改：0 或 ≥闭合端的值绝不下发到舵机通道。 */
    if ((open_us == 0U) || (open_us >= EC_AXIS_GRIPPER_CLOSE_US)) {
        return EC_AXIS_GRIPPER_OPEN_US;
    }
    return open_us;
}

/* 带张开脉宽的规划入口。除 open_pulse_us 外与老入口逐字节相同；
 * 老入口在文件末尾保留为 1 行包装（见 ec_motion_plan.h 的说明）。 */
bool ec_motion_plan_build_with_open(ec_axis_pick_place_t *out,
                                    int16_t pick_x_mm10, int16_t pick_y_mm10,
                                    int16_t place_x_mm10, int16_t place_y_mm10,
                                    uint16_t open_pulse_us)
{
    uint8_t next_step = 0U;

    if (out == NULL) {
        return false;
    }
    /* 双重域检查（2026-09-18）：协议合法域 ±1450 ∩ 机械可达域
     * X[-950,+900]/Y[-975,+925]（2026-09-19「甲′」改非对称）。见 ec_motion_plan.h 说明：
     * X/Y 已不装限位开关，越界无硬件可发现，必须在此拦住。
     * 2026-09-16（P2）：**两组坐标都要查** —— 抓取点改成参数后，它和落料点
     * 一样会被下成脉冲；只查落料点等于给抓取点留了一条越界通道。 */
    if (!within_limits(pick_x_mm10, pick_y_mm10,
                       -EC_MOTION_WORKSPACE_LIMIT_MM10,
                       EC_MOTION_WORKSPACE_LIMIT_MM10,
                       -EC_MOTION_WORKSPACE_LIMIT_MM10,
                       EC_MOTION_WORKSPACE_LIMIT_MM10) ||
        !within_limits(place_x_mm10, place_y_mm10,
                       -EC_MOTION_WORKSPACE_LIMIT_MM10,
                       EC_MOTION_WORKSPACE_LIMIT_MM10,
                       -EC_MOTION_WORKSPACE_LIMIT_MM10,
                       EC_MOTION_WORKSPACE_LIMIT_MM10) ||
        !within_limits(pick_x_mm10, pick_y_mm10,
                       -EC_MOTION_REACH_LIMIT_X_MM10,
                       EC_MOTION_REACH_FAR_X_MM10,
                       -EC_MOTION_REACH_LIMIT_Y_MM10,
                       EC_MOTION_REACH_FAR_Y_MM10) ||
        !within_limits(place_x_mm10, place_y_mm10,
                       -EC_MOTION_REACH_LIMIT_X_MM10,
                       EC_MOTION_REACH_FAR_X_MM10,
                       -EC_MOTION_REACH_LIMIT_Y_MM10,
                       EC_MOTION_REACH_FAR_Y_MM10)) {
        return false;
    }

    /* HOME 也要查（2026-09-18 新增）：它同样是**会被下成脉冲的坐标**
     * （HOME→PICK 与 PLACE→HOME 两段都从它出发），但它是编译期常量、不来自视觉，
     * 所以上面那组「取料点 + 落料点」的双域检查管不到它。
     * 不查的后果与 X 那次超程事故完全一样：常量被改到可达域之外照样发脉冲，
     * 机构顶到限位 → 堵转 → 可能带挂主控；而 X/Y 无限位开关，无硬件能发现。
     * 常量不合法时整条计划直接不成立（fail-closed），不静默降级。 */
    if (!within_limits(EC_MOTION_HOME_X_MM10, EC_MOTION_HOME_Y_MM10,
                       -EC_MOTION_REACH_LIMIT_X_MM10,
                       EC_MOTION_REACH_FAR_X_MM10,
                       -EC_MOTION_REACH_LIMIT_Y_MM10,
                       EC_MOTION_REACH_FAR_Y_MM10)) {
        return false;
    }

    /* 🔴 2026-09-22：PARK 同理由也必须查（实施规格 §2.3）。
     * PARK 与 HOME 一样是**会被下成脉冲的编译期常量** —— 它现在是 leg1 的起点
     * 与 leg3 的终点（见下方两处 append_ordered_xy），而上面那组「取料点 + 落料点」
     * 的双域检查管不到常量。漏查的后果与 X 那次超程事故同一成因：
     *   常量被改到可达域之外照样发脉冲 ⇒ 顶死限位 ⇒ 堵转 ⇒ 可能带挂主控；
     *   而 X/Y 不装限位开关，没有任何硬件能发现。
     * 与 HOME 同样 fail-closed：常量不合法 ⇒ 整条计划不成立，不静默降级。
     * ⚠️ 已知当前值 PARK=(-950,+475)：X 正好压在负端边界上、Y 在域内 ⇒ 本校验通过。
     * ⚠️ ec_motion_plan_interp.c 里有一份同样的校验，**两处必须同步改**。 */
    if (!within_limits(EC_MOTION_PARK_X_MM10, EC_MOTION_PARK_Y_MM10,
                       -EC_MOTION_REACH_LIMIT_X_MM10,
                       EC_MOTION_REACH_FAR_X_MM10,
                       -EC_MOTION_REACH_LIMIT_Y_MM10,
                       EC_MOTION_REACH_FAR_Y_MM10)) {
        return false;
    }

    (void)memset(out, 0, sizeof(*out));

    /* 2026-09-18 修正：Z 动作从「每位置一对降-升」改为「取料点只闭合、落料点只张开」。
     * 原因：夹爪为单自由度机构（张开=抬起、闭合=下压），且实测闭合后能稳定夹持并保持，
     * XY 移动期间舵机无需动作。原实现在取料点闭合后又张开 —— 等于当场把已夹住的物体放掉。
     * 流程（2026-09-22 起）：
     *   **待机 625** → HOME→PICK → **降到该件类别开度** → WAIT → 闭合(夹住)
     *   → PICK→PLACE → 张开(释放) → **待机 625** → PLACE→HOME。 */

    /* 🔴 2026-09-19 新增第 0 步：**在 HOME 先张开**（用户实机要求）。
     *
     * 原因：上电或复位之后舵机【已不再输出脉宽】，夹爪停在哪个位置是不可知的 ——
     * 完全可能是闭合态。若带着闭合的爪直接执行 HOME→PICK，就会在取料点把物块撞飞。
     * 上一件结束时虽在落料点张开过，但那覆盖不了"首次上电"这一情形，
     * 故必须在**每件程序的开头**显式张开一次。
     *
     * 位置：放在最前面（第 0 步），先动舵机再走 XY；舵机 settle 200ms 后开始移动，
     * 而到取料点还需 1.7s 以上，到达时夹爪早已完全张开。
     *
     * 容量：加此步（+ 后面的 WAIT 步 + 2026-09-22 的"到取料点再降"步）后
     *       共 **12 步 = EC_AXIS_PICK_PLACE_STEP_COUNT(12)**（恰好用满、零余量；
     *       再加任何一步都会让 append_* 返回 false ⇒ 整条计划不成立）。
     *       代价：每件多 200ms（EC_AXIS_GRIPPER_SETTLE_MS）。 */
    /* [0] 起点（HOME）：**固定用待机开度 EC_AXIS_GRIPPER_STANDBY_US(625)**。
     * 🔴 2026-09-22 现场裁决，**推翻 2026-09-21 的"识别到件那一刻就切类别开度"**。
     * 用户原话：「他要先移动到那个位置之后，它先降到那个脉宽，然后再降一次」。
     * 为什么必须改成固定值：本舵机是**单轴联动**，同一脉宽同时决定升降与开合
     *   （ec_axis_driver.h:99-101）；脉宽越小 = 抬起越高 + 张开越大
     *   ⇒ 起点写类别值时，起点高度**逐件不同**（650 最高、800 最低），
     *     现场表现为"刚开始的高度不一样、不对"。
     * 625 同时满足两条：比三类开度都宽（穿行/回程不刮走托盘上其他件）
     *   + 三类里抬起最高（起点高度对所有件统一）。
     * ⚠️ 本步**不可删**（2026-09-19 的原始理由仍然成立）：上电/复位后舵机不输出
     *   脉宽、爪子可能停在闭合态；必须在每件开头先张开一次，否则会带着闭合爪
     *   走到取料点把物块撞飞。 */
    if (!append_z_servo(out, &next_step, EC_AXIS_GRIPPER_STANDBY_US)) {
        return false;
    }

    /* HOME -> PICK（空爪腿）：顺序保持现状，**不强制 Y 优先** —— 见 append_ordered_xy
     * 上方的顺序策略注释（这条腿的横移线本来就落在托盘近壁带里）。 */
    if (!append_ordered_xy(out, &next_step,
                           EC_MOTION_PARK_X_MM10, EC_MOTION_PARK_Y_MM10,
                           pick_x_mm10, pick_y_mm10,
                           false)) {
        return false;
    }

    /* 🔴 2026-09-22 新增：**到达取料点之后**才把开度降到该件类别的值。
     * 与 [0] 的 625 合起来 = "穿行统一高度 → 到件上方再降到位"两步，
     * 对应现场原话「先移动到那个位置之后，先降到那个脉宽，然后再降一次」。
     * ⚠️ 位置必须在 WAIT **之前**：先降到位，再让操作员目视确认停位，最后闭合。
     * ⚠️ 它是第 5 个舵机步 ⇒ 整轮多一个 EC_AXIS_GRIPPER_SETTLE_MS(600ms)，
     *    必须与 15s 失活窗口对账（见 ec_axis_driver.h 的 settle 说明）。 */
    if (!append_z_servo(out, &next_step, open_pulse_us)) {
        return false;
    }

    /* 🔴 2026-09-19 用户实机要求：**到位后先停一段，再夹取**。
     * 位置很关键 —— 必须在 XY 到达取料点**之后**、Z_DOWN(闭合)**之前**：
     * 让人肉眼确认滑台确实停在了目标物块的位置上，确认无误才闭合夹取。
     * 时长取 EC_AXIS_PICK_DWELL_MS（默认 2000ms，见 ec_axis_driver.h）。
     * ⚠️ 它计入整链时长，须与 ec_app.c:553 的 15000ms 失活窗口对账。
     * ⚠️ 迭代史：本处曾在 2026-09-21 被换成"在这里切类别开度"并被否掉；
     *    2026-09-22 按用户现场裁决**正式改成**"上一步 [3] 降到类别开度、本步纯等待"，
     *    理由见本函数开头 [0] 的注释（起点高度必须逐件一致）。 */
    if (!append_wait(out, &next_step, (uint16_t)EC_AXIS_PICK_DWELL_MS) ||
        !append_z_servo(out, &next_step, EC_AXIS_Z_DOWN_US)) {
        return false;
    }

    /* PICK -> PLACE：**带料腿**，强制「先 Y 后 X」—— 先沿 +Y 退出托盘，横移留在盘外。
     * 受 EC_MOTION_CARRY_LEG_Y_FIRST 单点控制（默认 1；改 0 可一键回退到 X 优先）。 */
    if (!append_ordered_xy(out, &next_step,
                           pick_x_mm10, pick_y_mm10,
                           place_x_mm10, place_y_mm10,
                           (EC_MOTION_CARRY_LEG_Y_FIRST != 0)) ||
        !append_z_servo(out, &next_step, open_pulse_us)) {
        return false;
    }

    /* 🔴 2026-09-21 现场裁决（用户口述）：落料之后、**回程之前**，把开度切回「待机 625µs」。
     * 此前 PLACE→HOME 整段回程停在"该件类别的落料开度"（正方体只有 650、最窄），
     * 回程时爪片会拦住/刮走托盘上其他物块 —— 这就是用户提这条诉求的现场原因。
     * ⚠️ 顺序不能颠倒：[落料=类别开度] → [切回待机 625] → [PLACE→HOME]，两步都要有。 */
    if (!append_z_servo(out, &next_step, EC_AXIS_GRIPPER_STANDBY_US)) {
        return false;
    }

    /* PLACE -> HOME（空爪腿）：顺序保持现状，**不强制 Y 优先**（见顺序策略注释）。 */
    return append_ordered_xy(out, &next_step,
                             place_x_mm10, place_y_mm10,
                             EC_MOTION_PARK_X_MM10, EC_MOTION_PARK_Y_MM10,
                             false);
}

/* 老入口：1 行包装。保证 tests/test_motion_plan.c 的 22 处调用一个字都不用改，
 * 且行为与 2026-09-21 之前**逐字节相同**（张开端 = EC_AXIS_Z_UP_US）。 */
bool ec_motion_plan_build(ec_axis_pick_place_t *out,
                          int16_t pick_x_mm10, int16_t pick_y_mm10,
                          int16_t place_x_mm10, int16_t place_y_mm10)
{
    return ec_motion_plan_build_with_open(out, pick_x_mm10, pick_y_mm10,
                                          place_x_mm10, place_y_mm10,
                                          EC_AXIS_Z_UP_US);
}

/* ────────────────────────────────────────────────────────────────────────────
 * 2026-10-23 新增：XY 插补版计划（与 ec_motion_plan_build_with_open 的**唯一区别**
 * 是把三段 XY 移动从「先一个轴、再另一个轴」改成「两轴同时起步」）
 *
 * 逐条对照 ec_motion_plan_build_with_open（12 步 → 9 步）：
 *
 *   #  串行版（12 步）                        插补版（9 步）
 *   -- --------------------------------------  ----------------------------------
 *   0  舵机 625（起点先张开）                 舵机 625（**相同，不可省**）
 *   1  PARK→PICK   2 步（先 Y 后 X）          PARK→PICK   1 步 XY_INTERP
 *   2  舵机 = 类别开度                        舵机 = 类别开度（**相同**）
 *   3  WAIT(PICK_DWELL_MS)                    WAIT(PICK_DWELL_MS)（**相同**）
 *   4  舵机 = 闭合                            舵机 = 闭合（**相同**）
 *   5  PICK→PLACE  2 步（强制先 Y）           PICK→PLACE  1 步 XY_INTERP
 *   6  舵机 = 类别开度（释放）                舵机 = 类别开度（**相同**）
 *   7  舵机 625（回程前切回待机）             舵机 625（**相同，不可省**）
 *   8  PLACE→PARK  2 步                       PLACE→PARK  1 步 XY_INTERP
 *
 * 🔴 刻意【不】采用 ec_motion_plan_interp.c 的 6 步版：
 *    那个版本丢了 [0] 起点先张开、[2] 到点降开度、[3] dwell、[7] 回程前切待机
 *    这 4 个关键步。缺 [0] 会让上电后可能带着闭合爪走到取料点把物块撞飞
 *    （2026-09-19 的原始事故原因，见 build_with_open 里的说明）。
 *
 * 前面那三组「双域 + HOME + PARK」坐标校验与串行版**完全一致**（照抄，改任何一处
 * 都会让两个版本对同一输入给出不同结论）。这里调用串行版来做校验是**不可行**的
 * （它会生成 12 步的串行计划），所以只能复制校验逻辑 —— 两处必须同步改。
 * ──────────────────────────────────────────────────────────────────────────── */
bool ec_motion_plan_build_with_open_interp(ec_axis_pick_place_t *out,
                                           int16_t pick_x_mm10, int16_t pick_y_mm10,
                                           int16_t place_x_mm10, int16_t place_y_mm10,
                                           uint16_t open_pulse_us)
{
    uint8_t next_step = 0U;

    if (out == NULL) {
        return false;
    }

    /* ── 坐标校验：与 ec_motion_plan_build_with_open 逐字一致 ── */
    if (!within_limits(pick_x_mm10, pick_y_mm10,
                       -EC_MOTION_WORKSPACE_LIMIT_MM10,
                       EC_MOTION_WORKSPACE_LIMIT_MM10,
                       -EC_MOTION_WORKSPACE_LIMIT_MM10,
                       EC_MOTION_WORKSPACE_LIMIT_MM10) ||
        !within_limits(place_x_mm10, place_y_mm10,
                       -EC_MOTION_WORKSPACE_LIMIT_MM10,
                       EC_MOTION_WORKSPACE_LIMIT_MM10,
                       -EC_MOTION_WORKSPACE_LIMIT_MM10,
                       EC_MOTION_WORKSPACE_LIMIT_MM10) ||
        !within_limits(pick_x_mm10, pick_y_mm10,
                       -EC_MOTION_REACH_LIMIT_X_MM10,
                       EC_MOTION_REACH_FAR_X_MM10,
                       -EC_MOTION_REACH_LIMIT_Y_MM10,
                       EC_MOTION_REACH_FAR_Y_MM10) ||
        !within_limits(place_x_mm10, place_y_mm10,
                       -EC_MOTION_REACH_LIMIT_X_MM10,
                       EC_MOTION_REACH_FAR_X_MM10,
                       -EC_MOTION_REACH_LIMIT_Y_MM10,
                       EC_MOTION_REACH_FAR_Y_MM10)) {
        return false;
    }
    if (!within_limits(EC_MOTION_HOME_X_MM10, EC_MOTION_HOME_Y_MM10,
                       -EC_MOTION_REACH_LIMIT_X_MM10,
                       EC_MOTION_REACH_FAR_X_MM10,
                       -EC_MOTION_REACH_LIMIT_Y_MM10,
                       EC_MOTION_REACH_FAR_Y_MM10)) {
        return false;
    }
    if (!within_limits(EC_MOTION_PARK_X_MM10, EC_MOTION_PARK_Y_MM10,
                       -EC_MOTION_REACH_LIMIT_X_MM10,
                       EC_MOTION_REACH_FAR_X_MM10,
                       -EC_MOTION_REACH_LIMIT_Y_MM10,
                       EC_MOTION_REACH_FAR_Y_MM10)) {
        return false;
    }

    (void)memset(out, 0, sizeof(*out));

    /* [0] 起点先张开（待机 625）—— 不可省，理由同串行版 */
    if (!append_z_servo(out, &next_step, EC_AXIS_GRIPPER_STANDBY_US)) {
        return false;
    }

    /* [1] PARK -> PICK：两轴同时起步 */
    if (!append_xy_interp(out, &next_step,
                          EC_MOTION_PARK_X_MM10, EC_MOTION_PARK_Y_MM10,
                          pick_x_mm10, pick_y_mm10)) {
        return false;
    }

    /* [2] 到达取料点后降到该件类别开度（必须在 WAIT 之前）*/
    if (!append_z_servo(out, &next_step, open_pulse_us)) {
        return false;
    }

    /* [3] 到位先停一段让操作员目视确认，[4] 再闭合夹住 */
    if (!append_wait(out, &next_step, (uint16_t)EC_AXIS_PICK_DWELL_MS) ||
        !append_z_servo(out, &next_step, EC_AXIS_Z_DOWN_US)) {
        return false;
    }

    /* [5] PICK -> PLACE：两轴同时起步 */
    if (!append_xy_interp(out, &next_step,
                          pick_x_mm10, pick_y_mm10,
                          place_x_mm10, place_y_mm10)) {
        return false;
    }

    /* [6] 落料：张开释放 */
    if (!append_z_servo(out, &next_step, open_pulse_us)) {
        return false;
    }

    /* [7] 回程前切回待机 625（否则回程爪片会刮走托盘上其他物块）*/
    if (!append_z_servo(out, &next_step, EC_AXIS_GRIPPER_STANDBY_US)) {
        return false;
    }

    /* [8] PLACE -> PARK：两轴同时起步 */
    return append_xy_interp(out, &next_step,
                            place_x_mm10, place_y_mm10,
                            EC_MOTION_PARK_X_MM10, EC_MOTION_PARK_Y_MM10);
}

/* ============================================================================
 * 2026-11-01 新增：新硬件（Z 独立舵机 + 夹爪独立 + 托盘落料槽舵机）15 步程序
 *
 * 与 ec_motion_plan_build_with_open_interp（9 步，Z/夹爪共用一路）的区别：
 *   · Z 升降走 EC_AXIS_STEP_Z_SERVO（PB0/TIM3_CH3）
 *   · 夹爪开合走 EC_AXIS_STEP_GRIPPER（PB10/TIM2_CH3）
 *   · 槽门开合走 EC_AXIS_STEP_SLOT（PE5/TIM9_CH1）
 *   · 放件时**先降到放件高度、再开槽门、再松夹爪、再关槽门**（用户 2026-11-01 定：
 *     开得太早会掉错位置，晚开有"兜底"作用）
 *
 * 步序（15 步，容量 16 留 1 个零填充尾槽）：
 *   [0] Z→z_travel   [1] GRIP→grip_open   [2] XY PARK→PICK
 *   [3] Z→z_pick     [4] WAIT 200ms       [5] GRIP→grip_close
 *   [6] Z→z_travel   [7] XY PICK→PLACE
 *   [8] Z→z_place    [9] SLOT→slot_open   [10] GRIP→grip_open
 *   [11] SLOT→slot_close  [12] Z→z_travel  [13] XY PLACE→PARK  [14] Z→z_travel
 * ========================================================================== */

static void set_gripper(ec_axis_step_t *step, uint16_t pulse_us)
{
    step->kind = EC_AXIS_STEP_GRIPPER;
    step->servo_pulse_us = pulse_us;
}

static bool append_gripper(ec_axis_pick_place_t *out, uint8_t *next_step,
                           uint16_t pulse_us)
{
    if (*next_step >= EC_AXIS_PICK_PLACE_STEP_COUNT) {
        return false;
    }
    set_gripper(&out->step[*next_step], pulse_us);
    ++(*next_step);
    return true;
}

static void set_slot(ec_axis_step_t *step, uint16_t pulse_us)
{
    step->kind = EC_AXIS_STEP_SLOT;
    step->servo_pulse_us = pulse_us;
}

static bool append_slot(ec_axis_pick_place_t *out, uint8_t *next_step,
                        uint16_t pulse_us)
{
    if (*next_step >= EC_AXIS_PICK_PLACE_STEP_COUNT) {
        return false;
    }
    set_slot(&out->step[*next_step], pulse_us);
    ++(*next_step);
    return true;
}

bool ec_motion_plan_build_v2(ec_axis_pick_place_t *out,
                             int16_t pick_x_mm10, int16_t pick_y_mm10,
                             int16_t place_x_mm10, int16_t place_y_mm10,
                             const ec_pick_params_t *p)
{
    uint8_t next_step = 0U;

    if ((out == NULL) || (p == NULL)) {
        return false;
    }
    if (!within_limits(pick_x_mm10, pick_y_mm10,
                       -EC_MOTION_WORKSPACE_LIMIT_MM10,
                       EC_MOTION_WORKSPACE_LIMIT_MM10,
                       -EC_MOTION_WORKSPACE_LIMIT_MM10,
                       EC_MOTION_WORKSPACE_LIMIT_MM10) ||
        !within_limits(place_x_mm10, place_y_mm10,
                       -EC_MOTION_WORKSPACE_LIMIT_MM10,
                       EC_MOTION_WORKSPACE_LIMIT_MM10,
                       -EC_MOTION_WORKSPACE_LIMIT_MM10,
                       EC_MOTION_WORKSPACE_LIMIT_MM10) ||
        !within_limits(pick_x_mm10, pick_y_mm10,
                       -EC_MOTION_REACH_LIMIT_X_MM10,
                       EC_MOTION_REACH_FAR_X_MM10,
                       -EC_MOTION_REACH_LIMIT_Y_MM10,
                       EC_MOTION_REACH_FAR_Y_MM10) ||
        !within_limits(place_x_mm10, place_y_mm10,
                       -EC_MOTION_REACH_LIMIT_X_MM10,
                       EC_MOTION_REACH_FAR_X_MM10,
                       -EC_MOTION_REACH_LIMIT_Y_MM10,
                       EC_MOTION_REACH_FAR_Y_MM10)) {
        return false;
    }
    if (p->grip_open_us == 0U || p->grip_close_us == 0U ||
        p->z_travel_us == 0U || p->z_pick_us == 0U || p->z_place_us == 0U ||
        p->slot_open_us == 0U || p->slot_close_us == 0U) {
        return false;
    }

    (void)memset(out, 0, sizeof(*out));

    /* [0] Z 先到行进位（保证移动时不撞件） */
    if (!append_z_servo(out, &next_step, p->z_travel_us)) return false;
    /* [1] 夹爪张开待命 */
    if (!append_gripper(out, &next_step, p->grip_open_us)) return false;
    /* [2] PARK -> PICK：两轴同时起步 */
    if (!append_xy_interp(out, &next_step,
                          EC_MOTION_PARK_X_MM10, EC_MOTION_PARK_Y_MM10,
                          pick_x_mm10, pick_y_mm10)) return false;
    /* [3] Z 降到取件高度 */
    if (!append_z_servo(out, &next_step, p->z_pick_us)) return false;
    /* [4] 停一下再夹（视觉/机械稳定） */
    if (!append_wait(out, &next_step, (uint16_t)EC_AXIS_PICK_DWELL_MS)) return false;
    /* [5] 夹爪闭合夹住 */
    if (!append_gripper(out, &next_step, p->grip_close_us)) return false;
    /* [6] Z 抬到行进位 */
    if (!append_z_servo(out, &next_step, p->z_travel_us)) return false;
    /* [7] PICK -> PLACE：两轴同时起步 */
    if (!append_xy_interp(out, &next_step,
                          pick_x_mm10, pick_y_mm10,
                          place_x_mm10, place_y_mm10)) return false;
    /* [8] Z 降到放件高度（先降，不开门） */
    if (!append_z_servo(out, &next_step, p->z_place_us)) return false;
    /* [9] 开槽门放行 */
    if (!append_slot(out, &next_step, p->slot_open_us)) return false;
    /* [10] 夹爪张开释放 */
    if (!append_gripper(out, &next_step, p->grip_open_us)) return false;
    /* [11] 关槽门（兜底：防未落下的件卡住/误掉） */
    if (!append_slot(out, &next_step, p->slot_close_us)) return false;
    /* [12] Z 抬到行进位 */
    if (!append_z_servo(out, &next_step, p->z_travel_us)) return false;
    /* [13] PLACE -> PARK：两轴同时起步 */
    if (!append_xy_interp(out, &next_step,
                          place_x_mm10, place_y_mm10,
                          EC_MOTION_PARK_X_MM10, EC_MOTION_PARK_Y_MM10)) return false;
    /* [14] Z 回安全位，为下一轮复位（用户 2026-11-01 明确要这一步） */
    return append_z_servo(out, &next_step, p->z_travel_us);
}
