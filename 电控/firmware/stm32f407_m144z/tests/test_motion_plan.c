#include "ec_motion_plan.h"
#include "ec_axis_driver.h"
#include "ec_inputs.h"
#include "ec_servo_test.h"
#include "test_support.h"

/* Host-test doubles for the port layer. ec_motion_plan.c is pure logic that
 * only calls ec_axis_mm10_to_steps(); the port doubles here exist solely to
 * satisfy the linker for the rest of ec_axis_driver.c (compiled alongside to
 * provide ec_axis_mm10_to_steps). */
bool ec_step_port_set_direction(ec_axis_t axis, ec_direction_t direction)
{
    (void)axis;
    (void)direction;
    return true;
}
bool ec_step_port_enable_axis(ec_axis_t axis) { (void)axis; return true; }
bool ec_step_port_start_counted(ec_axis_t axis, uint32_t frequency_hz,
                                uint32_t steps)
{
    (void)axis;
    (void)frequency_hz;
    (void)steps;
    return true;
}
bool ec_step_port_enable_xy(void) { return true; }
bool ec_step_port_start_counted_xy(uint32_t x_steps, uint32_t x_frequency_hz,
                                   uint32_t y_steps, uint32_t y_frequency_hz)
{
    (void)x_steps;
    (void)x_frequency_hz;
    (void)y_steps;
    (void)y_frequency_hz;
    return true;
}
void ec_step_port_stop_all(void) { }
void ec_step_port_disable_all(void) { }
uint32_t ec_step_port_now_ms(void) { return 0U; }
uint32_t ec_step_port_counted_remaining(void) { return 0U; }
uint32_t ec_step_port_counted_target(void) { return 0U; }
bool ec_step_port_take_counted_completion(ec_axis_t *completed_axis)
{
    if (completed_axis != NULL) *completed_axis = EC_AXIS_NONE;
    return false;
}
bool ec_step_port_take_counted_abort(void) { return false; }
bool ec_servo_port_start_z(uint16_t pulse_us) { (void)pulse_us; return true; }
void ec_servo_port_stop_z(void) { }
/* ec_axis_driver.c also references the gripper channel (stop_all() and the
 * GRIPPER branch), so the port layer needs those doubles to link too. */
bool ec_servo_port_start(uint16_t pulse_us) { (void)pulse_us; return true; }
void ec_servo_port_stop(void) { }

/* Center-frame coordinates: HOME=(-950,-975), steps=abs(delta_mm10)*8.
 * 程序（2026-09-22 起 12 步，容量 13 留 1 备用槽）：
 *   [0] Z 待机 625（**固定值，起点高度逐件一致**）
 *   [1][2] XY 到取料点   [3] Z 降到**该件类别开度**   [4] WAIT 200ms
 *   [5] Z 闭合夹住
 *   [6][7] XY 到落点     [8] Z 张开释放（同类别开度）  [9] Z 待机 625
 *   [10][11] XY 回 HOME
 * Zero-displacement axis legs are omitted; used steps remain contiguous.
 * **五个 Z 舵机步（[0][3][5][8][9]，WAIT 除外）与 [4] WAIT 永远不被省略。 */
static void assert_move(const ec_axis_step_t *step, ec_axis_t axis,
                        uint32_t steps, ec_direction_t direction)
{
    /* 2026-09-22：原来是"只报 TEST_ASSERT 所在行"（即本函数内的行号），
     * 失败时看不出【哪一条腿、差多少】—— 上一轮就是因此把 7600/7800 抄错后
     * 只看到 ":68" 而无从下手。这里在失败前先把实际值打出来，判据不变。 */
    if (step->kind != EC_AXIS_STEP_MOVE || step->axis != axis ||
        step->steps != steps || step->direction != direction) {
        fprintf(stderr,
                "  MOVE mismatch: actual(kind=%d axis=%d steps=%u dir=%d) "
                "expected(axis=%d steps=%u dir=%d)\n",
                (int)step->kind, (int)step->axis, (unsigned)step->steps,
                (int)step->direction, (int)axis, (unsigned)steps,
                (int)direction);
    }
    TEST_ASSERT(step->kind == EC_AXIS_STEP_MOVE);
    TEST_ASSERT(step->axis == axis);
    TEST_ASSERT(step->steps == steps);
    TEST_ASSERT(step->direction == direction);
    TEST_ASSERT(step->y_steps == 0U);
    TEST_ASSERT(step->target_x_steps == 0);
    TEST_ASSERT(step->target_y_steps == 0);
}

static void assert_z(const ec_axis_pick_place_t *prog, size_t index,
                     uint16_t pulse_us)
{
    TEST_ASSERT(prog->step[index].kind == EC_AXIS_STEP_Z_SERVO);
    TEST_ASSERT(prog->step[index].servo_pulse_us == pulse_us);
}

/* WAIT 步（2026-09-19 新增）：纯耗时步，不驱动任何硬件，
 * servo_pulse_us 在本步语义为**毫秒**而非微秒（见 ec_axis_driver.h）。 */
static void assert_wait(const ec_axis_pick_place_t *prog, size_t index,
                        uint16_t ms)
{
    TEST_ASSERT(prog->step[index].kind == EC_AXIS_STEP_WAIT);
    TEST_ASSERT(prog->step[index].servo_pulse_us == ms);
}

/* Explicit expected counts/directions, independent of production conversion. */
static void assert_xy(const ec_axis_pick_place_t *prog, size_t index,
                      uint32_t x_steps, ec_direction_t x_dir,
                      uint32_t y_steps, ec_direction_t y_dir)
{
#if EC_MOTION_XY_ORDER_X_FIRST
    assert_move(&prog->step[index], EC_AXIS_X, x_steps, x_dir);
    assert_move(&prog->step[index + 1U], EC_AXIS_Y, y_steps, y_dir);
#else
    assert_move(&prog->step[index], EC_AXIS_Y, y_steps, y_dir);
    assert_move(&prog->step[index + 1U], EC_AXIS_X, x_steps, x_dir);
#endif
}

/* 带料腿（PICK→PLACE，2026-09-22 起 step[6]/step[7]）：2026-09-21 裁决 A 起**恒为「先 Y 后 X」**，
 * 受 EC_MOTION_CARRY_LEG_Y_FIRST 控制（默认 1）。
 *
 * 故意独立成函数、**不复用 assert_xy** —— 后者的期望顺序也跟着 EC_MOTION_XY_ORDER_X_FIRST
 * 走，用它测这条腿会变成同义反复，永远抓不到"宏接线错了"。这里的期望顺序是**硬编码字面量**。 */
static void assert_carry_xy(const ec_axis_pick_place_t *prog, size_t index,
                            uint32_t x_steps, ec_direction_t x_dir,
                            uint32_t y_steps, ec_direction_t y_dir)
{
#if EC_MOTION_CARRY_LEG_Y_FIRST && EC_MOTION_XY_ORDER_X_FIRST
    /* 期望：Y 在前。 */
    assert_move(&prog->step[index], EC_AXIS_Y, y_steps, y_dir);
    assert_move(&prog->step[index + 1U], EC_AXIS_X, x_steps, x_dir);
#else
    /* CARRY=0 时这条腿跟随 ORDER；ORDER=0 时本来就恒 Y 先 ⇒ 交给 assert_xy。 */
    assert_xy(prog, index, x_steps, x_dir, y_steps, y_dir);
#endif
}

static void assert_tail(const ec_axis_pick_place_t *prog, size_t used)
{
    for (size_t i = used; i < EC_AXIS_PICK_PLACE_STEP_COUNT; ++i) {
        TEST_ASSERT(prog->step[i].kind == EC_AXIS_STEP_MOVE);
        TEST_ASSERT(prog->step[i].axis == EC_AXIS_NONE);
        TEST_ASSERT(prog->step[i].steps == 0U);
        TEST_ASSERT(prog->step[i].y_steps == 0U);
        TEST_ASSERT(prog->step[i].servo_pulse_us == 0U);
        TEST_ASSERT(prog->step[i].target_x_steps == 0);
        TEST_ASSERT(prog->step[i].target_y_steps == 0);
    }
}

static void test_build_program_structure(void)
{
    ec_axis_pick_place_t prog;
    TEST_ASSERT(EC_AXIS_PICK_PLACE_STEP_COUNT >= 12U);
    TEST_ASSERT(EC_MOTION_HOME_X_MM10 == -950);
    TEST_ASSERT(EC_MOTION_HOME_Y_MM10 == -975);
    TEST_ASSERT(ec_motion_plan_build(&prog, 0, 0, 800, 500));
    /* [0] 起点固定用待机 625（2026-09-22：起点高度必须逐件一致）。 */
    assert_z(&prog, 0U, EC_AXIS_GRIPPER_STANDBY_US);
    /* PARK -> PICK: X +950=7600；Y 0-475=-475 => 3800、反向（2026-09-22 停靠位改 PARK）。 */
    assert_xy(&prog, 1U, 7600U, EC_MOTION_POSITIVE_X_DIR,
                         3800U, (ec_direction_t)(1U - EC_MOTION_POSITIVE_Y_DIR));
    /* [3] 到取料点之后才降到张开端（旧入口 ec_motion_plan_build 传 EC_AXIS_Z_UP_US）。 */
    assert_z(&prog, 3U, EC_AXIS_Z_UP_US);
    /* [4] 到位后停留 EC_AXIS_PICK_DWELL_MS（2026-09-19 由 2000 压到 200）：
     * 原先给人眼确认停位用，实测确认停位准确后压缩，为 15s 失活窗口让出余量。
     * ⚠️ 2026-09-22 起本步**纯等待**，切开度的是它前面的 [3]。 */
    assert_wait(&prog, 4U, (uint16_t)EC_AXIS_PICK_DWELL_MS);
    TEST_ASSERT(EC_AXIS_PICK_DWELL_MS == 200U);
    assert_z(&prog, 5U, EC_AXIS_Z_DOWN_US);
    assert_carry_xy(&prog, 6U, 6400U, EC_MOTION_POSITIVE_X_DIR,
                               4000U, EC_MOTION_POSITIVE_Y_DIR);
    assert_z(&prog, 8U, EC_AXIS_Z_UP_US);
    assert_z(&prog, 9U, EC_AXIS_GRIPPER_STANDBY_US);
    /* PLACE -> PARK: X -1750=14000；Y 475-500=-25 => 200、反向（2026-09-22 停靠位改 PARK）。 */
    assert_xy(&prog, 10U, 14000U,
              (ec_direction_t)(1U - EC_MOTION_POSITIVE_X_DIR), 200U,
              (ec_direction_t)(1U - EC_MOTION_POSITIVE_Y_DIR));
    assert_tail(&prog, 12U);
    TEST_ASSERT(EC_AXIS_Z_DOWN_US == EC_AXIS_GRIPPER_CLOSE_US);
    TEST_ASSERT(EC_AXIS_Z_UP_US == EC_AXIS_GRIPPER_OPEN_US);
    TEST_ASSERT(EC_AXIS_GRIPPER_CLOSE_US == 1900U);
    /* 🔴 2026-09-21：张开端**不再钉死具体值**。
     * 原因：值已改为"按类别取 3 个"（正方体 650 / 三棱柱 750 / 圆柱 800），
     *       任何"OPEN == 某个数"的等值断言对另外两个类别必然是错的 ——
     *       上一版就是钉死 900 而头文件改到 800，导致这套测试自 09-21 起一直红着。
     * 改断两条**真正有约束力的不变量**：
     *   ① 张开 < 闭合 —— 机理约束（脉宽越小开度越大，见 ec_axis_driver.h:107-109），
     *      写反了爪子会朝机械端点顶死；
     *   ② 张开 ≥ 550 —— 台架已验证的最低档（ec_servo_test.c 的 is_allowed_pulse 白名单 +
     *      ec_diag.c 命令表，两处同步）；再往下就越过机械端点 ⇒ 持续堵转 ⇒ 烧舵机（不可逆）。
     *      这条顶替原 "==900" 的防笔误作用（例如把 800 打成 80：② 会拦住）。
     *   ③ 张开 ≤ 1100 —— 上界：1100 档已实测"并非最大开度"（同 header 注释），
     *      比它更闭合就没法罩住 40mm 的件。 */
    TEST_ASSERT(EC_AXIS_GRIPPER_OPEN_US < EC_AXIS_GRIPPER_CLOSE_US);
    TEST_ASSERT(EC_AXIS_GRIPPER_OPEN_US >= 550U);
    TEST_ASSERT(EC_AXIS_GRIPPER_OPEN_US <= 1100U);
    /* 按类别取值也必须落在同一区间（表里任何一个越界都在这里被拦住）。 */
    for (uint16_t c = 0U; c <= 6U; ++c) {
        uint16_t v = ec_motion_plan_open_us_for_class((uint8_t)c);
        TEST_ASSERT(v >= 550U);
        TEST_ASSERT(v <= 1100U);
        TEST_ASSERT(v < EC_AXIS_GRIPPER_CLOSE_US);
    }
    /* 未知/未受理类别的回落值必须 = 默认张开脉宽（= 改动前的行为）。 */
    TEST_ASSERT(ec_motion_plan_open_us_for_class(0U) == EC_AXIS_GRIPPER_OPEN_US);
    TEST_ASSERT(ec_motion_plan_open_us_for_class(7U) == EC_AXIS_GRIPPER_OPEN_US);
    TEST_ASSERT(ec_motion_plan_open_us_for_class(255U) == EC_AXIS_GRIPPER_OPEN_US);

    /* 🔴 2026-09-22 开度时序契约（用户现场裁决，**取代** 09-21 的"识别到就切"）：
     *   用户原话「先移动到那个位置之后，先降到那个脉宽，然后再降一次」
     *   ⇒ [0] 固定待机 625（起点高度逐件一致）→ [3] 到取料点后才降到类别开度。
     * ⚠️ 传 class=2（绿正方体）⇒ ec_motion_plan_open_us_for_class(2) == 650，
     *    它与 625 不相等 ⇒ 这条能真正区分"[0] 用了固定 625"与"[0] 用了类别值"。
     * ⚠️ 反过来说：谁把 [0] 改回类别值、或删掉 [3]，这条断言必须变红。 */
    {
        uint16_t cat = ec_motion_plan_open_us_for_class(2U);
        TEST_ASSERT(cat == EC_MOTION_OPEN_US_CUBE);
        TEST_ASSERT(cat != EC_AXIS_GRIPPER_OPEN_US);
        TEST_ASSERT(cat != EC_AXIS_GRIPPER_STANDBY_US);
        TEST_ASSERT(ec_motion_plan_build_with_open(&prog, 0, 0, 800, 500, cat));
        assert_z(&prog, 0U, EC_AXIS_GRIPPER_STANDBY_US);          /* [0] 起点：固定待机 625 */
        assert_z(&prog, 3U, cat);                                 /* [3] 到位后才降到类别开度 */
        assert_wait(&prog, 4U, (uint16_t)EC_AXIS_PICK_DWELL_MS);  /* [4] 仍是纯等待 */
        assert_z(&prog, 5U, EC_AXIS_Z_DOWN_US);                   /* [5] 闭合端不变 */
        assert_z(&prog, 8U, cat);                                 /* [8] 落料释放：同类别开度 */
        assert_z(&prog, 9U, EC_AXIS_GRIPPER_STANDBY_US);          /* [9] 回程前切回待机 625 */
        assert_tail(&prog, 12U);                                  /* 规范满编 12 步 */
    }
}

static void test_negative_target(void)
{
    ec_axis_pick_place_t prog;
    TEST_ASSERT(ec_motion_plan_build(&prog, 0, 0, -600, -500));
    assert_z(&prog, 0U, EC_AXIS_GRIPPER_STANDBY_US);
    assert_xy(&prog, 1U, 7600U, EC_MOTION_POSITIVE_X_DIR,
                         3800U, (ec_direction_t)(1U - EC_MOTION_POSITIVE_Y_DIR));
    assert_z(&prog, 3U, EC_AXIS_Z_UP_US);
    assert_wait(&prog, 4U, (uint16_t)EC_AXIS_PICK_DWELL_MS);
    assert_z(&prog, 5U, EC_AXIS_Z_DOWN_US);
    assert_carry_xy(&prog, 6U, 4800U,
              (ec_direction_t)(1U - EC_MOTION_POSITIVE_X_DIR), 4000U,
              (ec_direction_t)(1U - EC_MOTION_POSITIVE_Y_DIR));
    assert_z(&prog, 8U, EC_AXIS_Z_UP_US);
    assert_z(&prog, 9U, EC_AXIS_GRIPPER_STANDBY_US);
    /* Negative PLACE is still below PARK: return Y = 475-(-500) = +975 => 7800、正向。
     * 🔴 2026-09-22 修正：此处原写 7600，是把 place_y 误当成 -475 算的 ——
     *   本用例的 place_y 是 **-500**（:221），故 |Δ| = 975 而非 950 ⇒ 7800。
     *   行号 :233-236 与 §三 期望值表一致，只是上一轮抄错了数。 */
    assert_xy(&prog, 10U, 2800U,
              (ec_direction_t)(1U - EC_MOTION_POSITIVE_X_DIR), 7800U,
              EC_MOTION_POSITIVE_Y_DIR);
    assert_tail(&prog, 12U);
}

static void test_zero_displacement_is_omitted(void)
{
    ec_axis_pick_place_t prog;
    TEST_ASSERT(ec_motion_plan_build(&prog, 0, 0, 800, 0));
    assert_z(&prog, 0U, EC_AXIS_GRIPPER_STANDBY_US);
    assert_xy(&prog, 1U, 7600U, EC_MOTION_POSITIVE_X_DIR,
                         3800U, (ec_direction_t)(1U - EC_MOTION_POSITIVE_Y_DIR));
    assert_z(&prog, 3U, EC_AXIS_Z_UP_US);
    assert_wait(&prog, 4U, (uint16_t)EC_AXIS_PICK_DWELL_MS);
    assert_z(&prog, 5U, EC_AXIS_Z_DOWN_US);
    /* Only PICK -> PLACE Y is omitted; return Y is PARK=+475（2026-09-22 停靠位改 PARK）。 */
    assert_move(&prog.step[6], EC_AXIS_X, 6400U, EC_MOTION_POSITIVE_X_DIR);
    assert_z(&prog, 7U, EC_AXIS_Z_UP_US);
    assert_z(&prog, 8U, EC_AXIS_GRIPPER_STANDBY_US);
    assert_xy(&prog, 9U, 14000U,
              (ec_direction_t)(1U - EC_MOTION_POSITIVE_X_DIR), 3800U,
              EC_MOTION_POSITIVE_Y_DIR);
    assert_tail(&prog, 11U);

    /* PICK=PARK: omit both initial legs and both Y legs.
     * WAIT 落到 [2]，且**零位移时也必须在** —— 它是纯时间步，不随轴腿一起消失。
     * 🔴 2026-09-22：参数由 PICK=HOME(-950,-975) 改为 PICK=PARK(-950,+475) ——
     *   停靠位改成 PARK 后，"起点=PICK"才是零位移；沿用旧参数会让 Y 腿各多 11600 步。 */
    TEST_ASSERT(ec_motion_plan_build(&prog, -950, 475, -150, 475));
    assert_z(&prog, 0U, EC_AXIS_GRIPPER_STANDBY_US);
    assert_z(&prog, 1U, EC_AXIS_Z_UP_US);
    assert_wait(&prog, 2U, (uint16_t)EC_AXIS_PICK_DWELL_MS);
    assert_z(&prog, 3U, EC_AXIS_Z_DOWN_US);
    assert_move(&prog.step[4], EC_AXIS_X, 6400U, EC_MOTION_POSITIVE_X_DIR);
    assert_z(&prog, 5U, EC_AXIS_Z_UP_US);
    assert_z(&prog, 6U, EC_AXIS_GRIPPER_STANDBY_US);
    assert_move(&prog.step[7], EC_AXIS_X, 6400U,
                (ec_direction_t)(1U - EC_MOTION_POSITIVE_X_DIR));
    assert_tail(&prog, 8U);

    /* All waypoints coincide (at PARK): all six XY legs vanish, WAIT 与五个 Z 都留下。 */
    TEST_ASSERT(ec_motion_plan_build(&prog, -950, 475, -950, 475));
    assert_z(&prog, 0U, EC_AXIS_GRIPPER_STANDBY_US);
    assert_z(&prog, 1U, EC_AXIS_Z_UP_US);
    assert_wait(&prog, 2U, (uint16_t)EC_AXIS_PICK_DWELL_MS);
    assert_z(&prog, 3U, EC_AXIS_Z_DOWN_US);
    assert_z(&prog, 4U, EC_AXIS_Z_UP_US);
    assert_z(&prog, 5U, EC_AXIS_GRIPPER_STANDBY_US);
    assert_tail(&prog, 6U);
}

static void test_boundary(void)
{
    ec_axis_pick_place_t prog;

    /* 2026-09-19「甲′」：实际生效的机械可达域是**非对称**的
     *   X ∈ [-950, +900]、Y ∈ [-975, +925]
     * 负端 = EC_MOTION_REACH_LIMIT_*（HOME 正好压线，不能收紧），
     * 正端 = EC_MOTION_REACH_FAR_*（各让 5mm 机械余量，防实际行程略短时顶死）。
     * 而不是协议合法域 ±1450（两者取交集）。越界会向物理上够不到的坐标发
     * 脉冲，而 X/Y 已不装限位开关，没有任何硬件能发现越界。 */

    /* 正端边界值恰好通过（含 Y 端）。 */
    TEST_ASSERT(ec_motion_plan_build(&prog, 0, 0,
                                     EC_MOTION_REACH_FAR_X_MM10,
                                     EC_MOTION_REACH_FAR_Y_MM10));
    /* 负端边界值恰好通过 —— HOME 就落在这一侧。 */
    TEST_ASSERT(ec_motion_plan_build(&prog, 0, 0,
                                     -EC_MOTION_REACH_LIMIT_X_MM10,
                                     -EC_MOTION_REACH_LIMIT_Y_MM10));
    /* 正端再越 1（0.1mm）即拒绝，X/Y 各一条。 */
    TEST_ASSERT(!ec_motion_plan_build(&prog, 0, 0,
                                      EC_MOTION_REACH_FAR_X_MM10 + 1, 0));
    TEST_ASSERT(!ec_motion_plan_build(&prog, 0, 0, 0,
                                      EC_MOTION_REACH_FAR_Y_MM10 + 1));
    /* 负端再越 1 即拒绝，X/Y 各一条。 */
    TEST_ASSERT(!ec_motion_plan_build(&prog, 0, 0,
                                      -EC_MOTION_REACH_LIMIT_X_MM10 - 1, 0));
    TEST_ASSERT(!ec_motion_plan_build(&prog, 0, 0, 0,
                                      -EC_MOTION_REACH_LIMIT_Y_MM10 - 1));
    /* The pick point is independently commanded and must be checked too. */
    TEST_ASSERT(!ec_motion_plan_build(&prog,
                                      EC_MOTION_REACH_FAR_X_MM10 + 1, 0,
                                      0, 0));
    TEST_ASSERT(!ec_motion_plan_build(&prog, 0,
                                      EC_MOTION_REACH_FAR_Y_MM10 + 1,
                                      0, 0));
    /* X 在界内而 Y 超界时也必须拒绝，防止双轴限值拆分后漏查 Y。 */
    TEST_ASSERT(!ec_motion_plan_build(&prog, 0, 0,
                                      EC_MOTION_REACH_FAR_X_MM10,
                                      EC_MOTION_REACH_FAR_Y_MM10 + 1));
    /* 协议域 ±1450 内的坐标，只要超出可达域同样拒绝。 */
    TEST_ASSERT(!ec_motion_plan_build(&prog, 0, 0,
                                      EC_MOTION_WORKSPACE_LIMIT_MM10, 0));
    TEST_ASSERT(!ec_motion_plan_build(&prog, 0, 0, 0,
                                      -EC_MOTION_WORKSPACE_LIMIT_MM10));
    /* 协议域之外（±1450 以外）也拒绝。 */
    TEST_ASSERT(!ec_motion_plan_build(&prog, 0, 0, 1451, 0));
    TEST_ASSERT(!ec_motion_plan_build(&prog, 0, 0, 0, -1451));
    TEST_ASSERT(!ec_motion_plan_build(&prog, 1451, 0, 0, 0));
    TEST_ASSERT(!ec_motion_plan_build(&prog, 0, -1451, 0, 0));
    TEST_ASSERT(!ec_motion_plan_build(NULL, 0, 0, 0, 0));
}

static void test_driver_accepts_plan(void)
{
    ec_axis_pick_place_t prog;

    TEST_ASSERT(ec_motion_plan_build(&prog, 0, 0, 800, 500));
    ec_axis_driver_init();
    /* The driver validates all used steps (incl. single-axis MOVE) as well-formed and
     * tolerates the unused tail slot of the fixed-size array. */
    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) == EC_AXIS_RESULT_OK);
}

static void test_home_is_inside_the_reach_limits(void)
{
    /* HOME is on the inclusive **negative** reach boundary in the current plan
     * (2026-09-19「甲′」：负端 = EC_MOTION_REACH_LIMIT_*，正端 = _FAR_*）。
     * This checks coordinate validity only: no hardware switch, physical
     * clearance or repeatability of manual positioning is verified here. */
    TEST_ASSERT(EC_MOTION_HOME_X_MM10 >= -EC_MOTION_REACH_LIMIT_X_MM10);
    TEST_ASSERT(EC_MOTION_HOME_X_MM10 <= EC_MOTION_REACH_FAR_X_MM10);
    TEST_ASSERT(EC_MOTION_HOME_Y_MM10 >= -EC_MOTION_REACH_LIMIT_Y_MM10);
    TEST_ASSERT(EC_MOTION_HOME_Y_MM10 <= EC_MOTION_REACH_FAR_Y_MM10);

    /* 2026-09-22：PARK（leg1 起点 / leg3 终点）现在也有同一条区间校验
     * （ec_motion_plan.c 的实施规格 §2.3 那条）⇒ 它的前置条件在这里钉住：
     * 一旦有人把 PARK 挪出可达域，规划会整体 fail-closed（每次 build 都返回 false），
     * 而这条断言会在主机侧先把原因指出来，不至于现场只看到"链一件都不派"。 */
    TEST_ASSERT(EC_MOTION_PARK_X_MM10 >= -EC_MOTION_REACH_LIMIT_X_MM10);
    TEST_ASSERT(EC_MOTION_PARK_X_MM10 <= EC_MOTION_REACH_FAR_X_MM10);
    TEST_ASSERT(EC_MOTION_PARK_Y_MM10 >= -EC_MOTION_REACH_LIMIT_Y_MM10);
    TEST_ASSERT(EC_MOTION_PARK_Y_MM10 <= EC_MOTION_REACH_FAR_Y_MM10);

    /* NULL output must be rejected independently of coordinate validity. */
    TEST_ASSERT(ec_motion_plan_build(NULL, 0, 0, 0, 0) == false);
}

void test_motion_plan(void)
{
    test_build_program_structure();
    test_negative_target();
    test_zero_displacement_is_omitted();
    test_boundary();
    test_home_is_inside_the_reach_limits();
    test_driver_accepts_plan();
}

int main(void)
{
    test_motion_plan();
    puts("ALL MOTION PLAN HOST TESTS PASSED");
    return EXIT_SUCCESS;
}
