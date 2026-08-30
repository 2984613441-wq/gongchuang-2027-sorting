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
bool ec_servo_port_start_z(uint16_t pulse_us) { (void)pulse_us; return true; }
void ec_servo_port_stop_z(void) { }

static void test_build_program_structure(void)
{
    ec_axis_pick_place_t prog;

    TEST_ASSERT(ec_motion_plan_build(&prog, 1000, 500)); /* +100.0mm, +50.0mm */

    /* 0: MOVE_XY HOME(-1450,-1450) -> PICK(0,0): delta +1450,+1450 = 11600. */
    TEST_ASSERT(prog.step[0].kind == EC_AXIS_STEP_MOVE_XY);
    TEST_ASSERT(prog.step[0].steps == 11600U);
    TEST_ASSERT(prog.step[0].y_steps == 11600U);
    TEST_ASSERT(prog.step[0].direction == EC_MOTION_POSITIVE_X_DIR);
    TEST_ASSERT(prog.step[0].y_direction == EC_MOTION_POSITIVE_Y_DIR);

    /* 1,2: Z down (open) then Z up (close = grab). */
    TEST_ASSERT(prog.step[1].kind == EC_AXIS_STEP_Z_SERVO);
    TEST_ASSERT(prog.step[1].servo_pulse_us == EC_AXIS_Z_DOWN_US);
    TEST_ASSERT(prog.step[2].kind == EC_AXIS_STEP_Z_SERVO);
    TEST_ASSERT(prog.step[2].servo_pulse_us == EC_AXIS_Z_UP_US);

    /* 3: MOVE_XY PICK(0,0) -> PLACE(1000,500): delta +1000,+500 = 8000,4000. */
    TEST_ASSERT(prog.step[3].kind == EC_AXIS_STEP_MOVE_XY);
    TEST_ASSERT(prog.step[3].steps == 8000U);
    TEST_ASSERT(prog.step[3].y_steps == 4000U);
    TEST_ASSERT(prog.step[3].direction == EC_MOTION_POSITIVE_X_DIR);
    TEST_ASSERT(prog.step[3].y_direction == EC_MOTION_POSITIVE_Y_DIR);

    /* 4,5: Z down (open = release) then Z up (close = ready). */
    TEST_ASSERT(prog.step[4].kind == EC_AXIS_STEP_Z_SERVO);
    TEST_ASSERT(prog.step[4].servo_pulse_us == EC_AXIS_Z_DOWN_US);
    TEST_ASSERT(prog.step[5].kind == EC_AXIS_STEP_Z_SERVO);
    TEST_ASSERT(prog.step[5].servo_pulse_us == EC_AXIS_Z_UP_US);

    /* 6: MOVE_XY PLACE(1000,500) -> HOME(-1450,-1450): delta -2450,-1950. */
    TEST_ASSERT(prog.step[6].kind == EC_AXIS_STEP_MOVE_XY);
    TEST_ASSERT(prog.step[6].steps == 19600U);
    TEST_ASSERT(prog.step[6].y_steps == 15600U);
    TEST_ASSERT(prog.step[6].direction != EC_MOTION_POSITIVE_X_DIR);
    TEST_ASSERT(prog.step[6].y_direction != EC_MOTION_POSITIVE_Y_DIR);
}

static void test_negative_target(void)
{
    ec_axis_pick_place_t prog;

    TEST_ASSERT(ec_motion_plan_build(&prog, -1000, -500)); /* -100.0mm, -50.0mm */

    /* 3: PICK(0,0) -> PLACE(-1000,-500): delta -1000,-500 -> 8000,4000 steps,
     * directions opposite of positive. */
    TEST_ASSERT(prog.step[3].kind == EC_AXIS_STEP_MOVE_XY);
    TEST_ASSERT(prog.step[3].steps == 8000U);
    TEST_ASSERT(prog.step[3].y_steps == 4000U);
    TEST_ASSERT(prog.step[3].direction != EC_MOTION_POSITIVE_X_DIR);
    TEST_ASSERT(prog.step[3].y_direction != EC_MOTION_POSITIVE_Y_DIR);

    /* 6: PLACE(-1000,-500) -> HOME(-1450,-1450): delta -450,-950 -> 3600,7600. */
    TEST_ASSERT(prog.step[6].steps == 3600U);
    TEST_ASSERT(prog.step[6].y_steps == 7600U);
    TEST_ASSERT(prog.step[6].direction != EC_MOTION_POSITIVE_X_DIR);
    TEST_ASSERT(prog.step[6].y_direction != EC_MOTION_POSITIVE_Y_DIR);
}

static void test_boundary(void)
{
    ec_axis_pick_place_t prog;

    /* +/-145.0mm is the frozen workspace edge; 145.1mm is out. */
    TEST_ASSERT(ec_motion_plan_build(&prog, 1450, 1450));
    TEST_ASSERT(ec_motion_plan_build(&prog, -1450, -1450));
    TEST_ASSERT(!ec_motion_plan_build(&prog, 1451, 0));
    TEST_ASSERT(!ec_motion_plan_build(&prog, 0, -1451));
    TEST_ASSERT(!ec_motion_plan_build(NULL, 0, 0));
}

static void test_driver_accepts_plan(void)
{
    ec_axis_pick_place_t prog;

    TEST_ASSERT(ec_motion_plan_build(&prog, 1000, 500));
    ec_axis_driver_init();
    /* The driver validates all 7 steps (incl. MOVE_XY) as well-formed. */
    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) == EC_AXIS_RESULT_OK);
}

void test_motion_plan(void)
{
    test_build_program_structure();
    test_negative_target();
    test_boundary();
    test_driver_accepts_plan();
}

int main(void)
{
    test_motion_plan();
    puts("ALL MOTION PLAN HOST TESTS PASSED");
    return EXIT_SUCCESS;
}
