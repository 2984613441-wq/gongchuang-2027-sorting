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

/* —— 2026-09-18 生产路径期望 ————————————————————————————————
 * X/Y 可达域为 X±950 / Y±975 (0.1mm)，原点 = 装置中心，
 * HOME = (-900, -920)，PICK = (0, 0)，80 步/mm（steps = |Δmm10| × 8）。
 * 每个原 MOVE_XY 都应拆成连续的单轴 MOVE；默认先 X 后 Y。
 * ⚠️ HOME 一改（本次 -800 → -900/-920），HOME→PICK 与 PLACE→HOME 两段步数全变；
 *    只有 PICK→PLACE 那一段与 HOME 无关、保持原值。 */
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

static void test_build_program_structure(void)
{
    ec_axis_pick_place_t prog;

    TEST_ASSERT(EC_AXIS_PICK_PLACE_STEP_COUNT >= 11U);

    /* P3：抓取点已是参数；(0,0) 正是旧常量 EC_MOTION_PICK_X/Y_MM10 的值，
     * 所以下面所有数值期望一个都不用改（常量→参数是行为等价的改写）。 */
    TEST_ASSERT(ec_motion_plan_build(&prog, 0, 0, 800, 500)); /* 落点 +80.0mm, +50.0mm */

    /* HOME -> PICK: X and Y are separate moves, followed by 闭合(夹住)。
     * delta = (0,0) - (-900,-920) = +900,+920 -> 7200,7360 steps。
     * 2026-09-18：Z 动作由「每位置一对降-升」改为「取料点只闭合、落料点只张开」 ——
     * 夹爪是单自由度机构（张开=抬起、闭合=下压），闭合后能稳定夹持并保持，
     * XY 移动期间舵机无需动作；原实现在取料点闭合后又张开，等于当场放掉物体。 */
#if EC_MOTION_XY_ORDER_X_FIRST
    assert_move(&prog.step[0], EC_AXIS_X, 7200U, EC_MOTION_POSITIVE_X_DIR);
    assert_move(&prog.step[1], EC_AXIS_Y, 7360U, EC_MOTION_POSITIVE_Y_DIR);
#else
    assert_move(&prog.step[0], EC_AXIS_Y, 7360U, EC_MOTION_POSITIVE_Y_DIR);
    assert_move(&prog.step[1], EC_AXIS_X, 7200U, EC_MOTION_POSITIVE_X_DIR);
#endif
    TEST_ASSERT(prog.step[2].kind == EC_AXIS_STEP_Z_SERVO);
    TEST_ASSERT(prog.step[2].servo_pulse_us == EC_AXIS_Z_DOWN_US);   /* 闭合：夹住 */

    /* PICK -> PLACE: delta +800,+500 = 6400,4000 steps, 随后张开(释放)。 */
#if EC_MOTION_XY_ORDER_X_FIRST
    assert_move(&prog.step[3], EC_AXIS_X, 6400U, EC_MOTION_POSITIVE_X_DIR);
    assert_move(&prog.step[4], EC_AXIS_Y, 4000U, EC_MOTION_POSITIVE_Y_DIR);
#else
    assert_move(&prog.step[3], EC_AXIS_Y, 4000U, EC_MOTION_POSITIVE_Y_DIR);
    assert_move(&prog.step[4], EC_AXIS_X, 6400U, EC_MOTION_POSITIVE_X_DIR);
#endif
    TEST_ASSERT(prog.step[5].kind == EC_AXIS_STEP_Z_SERVO);
    TEST_ASSERT(prog.step[5].servo_pulse_us == EC_AXIS_Z_UP_US);     /* 张开：释放 */

    /* PLACE -> HOME: delta = (-900,-920) - (800,500) = -1700,-1420 -> 13600,11360 steps. */
#if EC_MOTION_XY_ORDER_X_FIRST
    assert_move(&prog.step[6], EC_AXIS_X, 13600U,
                (ec_direction_t)(1U - EC_MOTION_POSITIVE_X_DIR));
    assert_move(&prog.step[7], EC_AXIS_Y, 11360U,
                (ec_direction_t)(1U - EC_MOTION_POSITIVE_Y_DIR));
#else
    assert_move(&prog.step[6], EC_AXIS_Y, 11360U,
                (ec_direction_t)(1U - EC_MOTION_POSITIVE_Y_DIR));
    assert_move(&prog.step[7], EC_AXIS_X, 13600U,
                (ec_direction_t)(1U - EC_MOTION_POSITIVE_X_DIR));
#endif

    /* 八个已用步（6 个 XY 位移 + 2 个舵机动作），其后只有全零尾槽。 */
    TEST_ASSERT(prog.step[8].kind == EC_AXIS_STEP_MOVE);
    TEST_ASSERT(prog.step[8].axis == EC_AXIS_NONE);
    TEST_ASSERT(prog.step[8].steps == 0U);
    TEST_ASSERT(prog.step[8].y_steps == 0U);
    TEST_ASSERT(prog.step[8].servo_pulse_us == 0U);

    /* 回归保护：锁死 Z 宏语义（2026-09-18 曾因取值与实际机构相反导致计划反向动作）。 */
    TEST_ASSERT(EC_AXIS_Z_DOWN_US == EC_AXIS_GRIPPER_CLOSE_US); /* 取料点=闭合 */
    TEST_ASSERT(EC_AXIS_Z_UP_US == EC_AXIS_GRIPPER_OPEN_US);    /* 落料点=张开 */
    TEST_ASSERT(EC_AXIS_GRIPPER_CLOSE_US == 1900U);
    TEST_ASSERT(EC_AXIS_GRIPPER_OPEN_US == 1100U);
}

static void test_negative_target(void)
{
    ec_axis_pick_place_t prog;

    TEST_ASSERT(ec_motion_plan_build(&prog, 0, 0, -600, -500)); /* 落点 -60.0mm, -50.0mm */

    /* PICK -> PLACE(-600,-500): delta -600,-500 -> 4800,4000 steps. */
#if EC_MOTION_XY_ORDER_X_FIRST
    assert_move(&prog.step[3], EC_AXIS_X, 4800U,
                (ec_direction_t)(1U - EC_MOTION_POSITIVE_X_DIR));
    assert_move(&prog.step[4], EC_AXIS_Y, 4000U,
                (ec_direction_t)(1U - EC_MOTION_POSITIVE_Y_DIR));
#else
    assert_move(&prog.step[3], EC_AXIS_Y, 4000U,
                (ec_direction_t)(1U - EC_MOTION_POSITIVE_Y_DIR));
    assert_move(&prog.step[4], EC_AXIS_X, 4800U,
                (ec_direction_t)(1U - EC_MOTION_POSITIVE_X_DIR));
#endif

    /* PLACE -> HOME: delta = (-900,-920) - (-600,-500) = -300,-420 -> 2400,3360 steps. */
#if EC_MOTION_XY_ORDER_X_FIRST
    assert_move(&prog.step[6], EC_AXIS_X, 2400U,
                (ec_direction_t)(1U - EC_MOTION_POSITIVE_X_DIR));
    assert_move(&prog.step[7], EC_AXIS_Y, 3360U,
                (ec_direction_t)(1U - EC_MOTION_POSITIVE_Y_DIR));
#else
    assert_move(&prog.step[6], EC_AXIS_Y, 3360U,
                (ec_direction_t)(1U - EC_MOTION_POSITIVE_Y_DIR));
    assert_move(&prog.step[7], EC_AXIS_X, 2400U,
                (ec_direction_t)(1U - EC_MOTION_POSITIVE_X_DIR));
#endif
}

static void test_zero_displacement_is_omitted(void)
{
    ec_axis_pick_place_t prog;

    /* Y does not change during PICK -> PLACE. That leg is omitted rather than
     * represented by a zero-step command, so no unused slot appears before
     * the following Z command.
     * 2026-09-18：Z 已改为「取料点只闭合、落料点只张开」，故此处只有两个 Z 动作。 */
    TEST_ASSERT(ec_motion_plan_build(&prog, 0, 0, 800, 0));

#if EC_MOTION_XY_ORDER_X_FIRST
    assert_move(&prog.step[0], EC_AXIS_X, 7200U, EC_MOTION_POSITIVE_X_DIR);
    assert_move(&prog.step[1], EC_AXIS_Y, 7360U, EC_MOTION_POSITIVE_Y_DIR);
#else
    assert_move(&prog.step[0], EC_AXIS_Y, 7360U, EC_MOTION_POSITIVE_Y_DIR);
    assert_move(&prog.step[1], EC_AXIS_X, 7200U, EC_MOTION_POSITIVE_X_DIR);
#endif
    TEST_ASSERT(prog.step[2].kind == EC_AXIS_STEP_Z_SERVO);      /* 闭合：夹住 */

#if EC_MOTION_XY_ORDER_X_FIRST
    assert_move(&prog.step[3], EC_AXIS_X, 6400U, EC_MOTION_POSITIVE_X_DIR);
    /* PICK -> PLACE 的 Y 位移为零被省略，故 Z 紧随其后落在 4。 */
    TEST_ASSERT(prog.step[4].kind == EC_AXIS_STEP_Z_SERVO);      /* 张开：释放 */
    assert_move(&prog.step[5], EC_AXIS_X, 13600U,
                (ec_direction_t)(1U - EC_MOTION_POSITIVE_X_DIR));
    assert_move(&prog.step[6], EC_AXIS_Y, 7360U,
                (ec_direction_t)(1U - EC_MOTION_POSITIVE_Y_DIR));
#else
    /* Y-first：被省略的是 Y 腿，非零的 X 腿照常发出。 */
    assert_move(&prog.step[3], EC_AXIS_X, 6400U, EC_MOTION_POSITIVE_X_DIR);
    TEST_ASSERT(prog.step[4].kind == EC_AXIS_STEP_Z_SERVO);      /* 张开：释放 */
    assert_move(&prog.step[5], EC_AXIS_Y, 7360U,
                (ec_direction_t)(1U - EC_MOTION_POSITIVE_Y_DIR));
    assert_move(&prog.step[6], EC_AXIS_X, 13600U,
                (ec_direction_t)(1U - EC_MOTION_POSITIVE_X_DIR));
#endif

    /* 七个已用步（5 个 XY 位移 + 2 个舵机动作），其后只有全零尾槽。 */
    TEST_ASSERT(prog.step[7].kind == EC_AXIS_STEP_MOVE);
    TEST_ASSERT(prog.step[7].axis == EC_AXIS_NONE);
    TEST_ASSERT(prog.step[7].steps == 0U);
    TEST_ASSERT(prog.step[8].kind == EC_AXIS_STEP_MOVE);
    TEST_ASSERT(prog.step[8].axis == EC_AXIS_NONE);
    TEST_ASSERT(prog.step[8].steps == 0U);
}

static void test_boundary(void)
{
    ec_axis_pick_place_t prog;

    /* 2026-09-18：实际生效的边界是机械可达域 X±1050/Y±950，
     * 而不是协议合法域 ±1450（两者取交集）。越界会向物理上够不到的坐标发
     * 脉冲，而 X/Y 已不装限位开关，没有任何硬件能发现越界。 */
    TEST_ASSERT(ec_motion_plan_build(&prog, 0, 0,
                                     EC_MOTION_REACH_LIMIT_X_MM10,
                                     EC_MOTION_REACH_LIMIT_Y_MM10));
    TEST_ASSERT(ec_motion_plan_build(&prog, 0, 0,
                                     -EC_MOTION_REACH_LIMIT_X_MM10,
                                     -EC_MOTION_REACH_LIMIT_Y_MM10));
    TEST_ASSERT(!ec_motion_plan_build(&prog, 0, 0,
                                       EC_MOTION_REACH_LIMIT_X_MM10 + 1, 0));
    TEST_ASSERT(!ec_motion_plan_build(&prog, 0, 0, 0,
                                       -EC_MOTION_REACH_LIMIT_Y_MM10 - 1));
    /* The pick point is independently commanded and must be checked too. */
    TEST_ASSERT(!ec_motion_plan_build(&prog,
                                      EC_MOTION_REACH_LIMIT_X_MM10 + 1, 0,
                                      0, 0));
    TEST_ASSERT(!ec_motion_plan_build(&prog, 0,
                                      EC_MOTION_REACH_LIMIT_Y_MM10 + 1,
                                      0, 0));
    /* X 在界内而 Y 超界时也必须拒绝，防止双轴限值拆分后漏查 Y。 */
    TEST_ASSERT(!ec_motion_plan_build(&prog, 0, 0,
                                      EC_MOTION_REACH_LIMIT_X_MM10,
                                      EC_MOTION_REACH_LIMIT_Y_MM10 + 1));
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

static void test_home_is_strictly_inside_the_reach_limits(void)
{
    /* HOME 是编译期常量，但每个循环都从它出发（HOME→PICK、PLACE→HOME 两段）。
     * 改了它却忘了同步可达域，就会向物理上够不到的坐标发脉冲 → 顶限位 → 堵转；
     * 而 X/Y 已不装限位开关，没有任何硬件能发现。此处用严格不等号 = 必须留余量，
     * 贴边等于原点稍有摆位偏差就直接顶死（方案 A 的原点靠人工摆中心建立）。 */
    TEST_ASSERT(EC_MOTION_HOME_X_MM10 < EC_MOTION_REACH_LIMIT_X_MM10);
    TEST_ASSERT(EC_MOTION_HOME_X_MM10 > -EC_MOTION_REACH_LIMIT_X_MM10);
    TEST_ASSERT(EC_MOTION_HOME_Y_MM10 < EC_MOTION_REACH_LIMIT_Y_MM10);
    TEST_ASSERT(EC_MOTION_HOME_Y_MM10 > -EC_MOTION_REACH_LIMIT_Y_MM10);

    /* 运行期的第二道闸：即便上面被改成取等，build 也必须拒绝而不是照发脉冲。 */
    TEST_ASSERT(ec_motion_plan_build(NULL, 0, 0, 0, 0) == false);
}

void test_motion_plan(void)
{
    test_build_program_structure();
    test_negative_target();
    test_zero_displacement_is_omitted();
    test_boundary();
    test_home_is_strictly_inside_the_reach_limits();
    test_driver_accepts_plan();
}

int main(void)
{
    test_motion_plan();
    puts("ALL MOTION PLAN HOST TESTS PASSED");
    return EXIT_SUCCESS;
}
