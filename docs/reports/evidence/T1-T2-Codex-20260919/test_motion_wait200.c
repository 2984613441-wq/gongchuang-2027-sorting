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
 * Open at HOME, move to PICK, [WAIT], close, move to PLACE, open, return HOME.
 * Zero-displacement axis legs are omitted; used steps remain contiguous.
 * The WAIT step (index 3 in the full program, 2026-09-19) is NEVER omitted --
 * it only consumes time and drives no axis. */
static void assert_move(const ec_axis_step_t *step, ec_axis_t axis,
                        uint32_t steps, ec_direction_t direction)
{
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
    TEST_ASSERT(EC_AXIS_PICK_PLACE_STEP_COUNT >= 10U);
    TEST_ASSERT(EC_MOTION_HOME_X_MM10 == -950);
    TEST_ASSERT(EC_MOTION_HOME_Y_MM10 == -975);
    TEST_ASSERT(ec_motion_plan_build(&prog, 0, 0, 800, 500));
    assert_z(&prog, 0U, EC_AXIS_Z_UP_US);
    /* HOME -> PICK: +950,+975 => 7600,7800. */
    assert_xy(&prog, 1U, 7600U, EC_MOTION_POSITIVE_X_DIR,
                         7800U, EC_MOTION_POSITIVE_Y_DIR);
    /* [3] 到位后停留 2000ms（2026-09-19）：夹取前给操作者肉眼确认的时间。 */
    assert_wait(&prog, 3U, 200U);
    TEST_ASSERT(EC_AXIS_PICK_DWELL_MS == 200U);
    assert_z(&prog, 4U, EC_AXIS_Z_DOWN_US);
    assert_xy(&prog, 5U, 6400U, EC_MOTION_POSITIVE_X_DIR,
                         4000U, EC_MOTION_POSITIVE_Y_DIR);
    assert_z(&prog, 7U, EC_AXIS_Z_UP_US);
    /* PLACE -> HOME: -1750,-1475 => 14000,11800. */
    assert_xy(&prog, 8U, 14000U,
              (ec_direction_t)(1U - EC_MOTION_POSITIVE_X_DIR), 11800U,
              (ec_direction_t)(1U - EC_MOTION_POSITIVE_Y_DIR));
    assert_tail(&prog, 10U);
    TEST_ASSERT(EC_AXIS_Z_DOWN_US == EC_AXIS_GRIPPER_CLOSE_US);
    TEST_ASSERT(EC_AXIS_Z_UP_US == EC_AXIS_GRIPPER_OPEN_US);
    TEST_ASSERT(EC_AXIS_GRIPPER_CLOSE_US == 1900U);
    TEST_ASSERT(EC_AXIS_GRIPPER_OPEN_US == 900U);
}

static void test_negative_target(void)
{
    ec_axis_pick_place_t prog;
    TEST_ASSERT(ec_motion_plan_build(&prog, 0, 0, -600, -500));
    assert_z(&prog, 0U, EC_AXIS_Z_UP_US);
    assert_xy(&prog, 1U, 7600U, EC_MOTION_POSITIVE_X_DIR,
                         7800U, EC_MOTION_POSITIVE_Y_DIR);
    assert_wait(&prog, 3U, 200U);
    assert_z(&prog, 4U, EC_AXIS_Z_DOWN_US);
    assert_xy(&prog, 5U, 4800U,
              (ec_direction_t)(1U - EC_MOTION_POSITIVE_X_DIR), 4000U,
              (ec_direction_t)(1U - EC_MOTION_POSITIVE_Y_DIR));
    assert_z(&prog, 7U, EC_AXIS_Z_UP_US);
    /* Negative PLACE is still above HOME: return is -350,-475. */
    assert_xy(&prog, 8U, 2800U,
              (ec_direction_t)(1U - EC_MOTION_POSITIVE_X_DIR), 3800U,
              (ec_direction_t)(1U - EC_MOTION_POSITIVE_Y_DIR));
    assert_tail(&prog, 10U);
}

static void test_zero_displacement_is_omitted(void)
{
    ec_axis_pick_place_t prog;
    TEST_ASSERT(ec_motion_plan_build(&prog, 0, 0, 800, 0));
    assert_z(&prog, 0U, EC_AXIS_Z_UP_US);
    assert_xy(&prog, 1U, 7600U, EC_MOTION_POSITIVE_X_DIR,
                         7800U, EC_MOTION_POSITIVE_Y_DIR);
    assert_wait(&prog, 3U, 200U);
    assert_z(&prog, 4U, EC_AXIS_Z_DOWN_US);
    /* Only PICK -> PLACE Y is omitted; return Y is -975. */
    assert_move(&prog.step[5], EC_AXIS_X, 6400U, EC_MOTION_POSITIVE_X_DIR);
    assert_z(&prog, 6U, EC_AXIS_Z_UP_US);
    assert_xy(&prog, 7U, 14000U,
              (ec_direction_t)(1U - EC_MOTION_POSITIVE_X_DIR), 7800U,
              (ec_direction_t)(1U - EC_MOTION_POSITIVE_Y_DIR));
    assert_tail(&prog, 9U);

    /* PICK=HOME: omit both initial legs and both Y legs.
     * WAIT 落到 [1]，且**零位移时也必须在** —— 它是纯时间步，不随轴腿一起消失。 */
    TEST_ASSERT(ec_motion_plan_build(&prog, -950, -975, -150, -975));
    assert_z(&prog, 0U, EC_AXIS_Z_UP_US);
    assert_wait(&prog, 1U, 200U);
    assert_z(&prog, 2U, EC_AXIS_Z_DOWN_US);
    assert_move(&prog.step[3], EC_AXIS_X, 6400U, EC_MOTION_POSITIVE_X_DIR);
    assert_z(&prog, 4U, EC_AXIS_Z_UP_US);
    assert_move(&prog.step[5], EC_AXIS_X, 6400U,
                (ec_direction_t)(1U - EC_MOTION_POSITIVE_X_DIR));
    assert_tail(&prog, 6U);

    /* All waypoints coincide: all six XY legs vanish, WAIT 与三个 Z 都留下。 */
    TEST_ASSERT(ec_motion_plan_build(&prog, -950, -975, -950, -975));
    assert_z(&prog, 0U, EC_AXIS_Z_UP_US);
    assert_wait(&prog, 1U, 200U);
    assert_z(&prog, 2U, EC_AXIS_Z_DOWN_US);
    assert_z(&prog, 3U, EC_AXIS_Z_UP_US);
    assert_tail(&prog, 4U);
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
