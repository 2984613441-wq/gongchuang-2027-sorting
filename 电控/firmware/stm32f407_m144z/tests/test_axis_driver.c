#include "test_support.h"

#include "ec_axis_driver.h"
#include "ec_inputs.h"
#include "ec_servo_test.h"

#include <string.h>

/* Host-test doubles for the ec_step_port_* / ec_servo_port_* port layer.
 * ec_axis_driver.c depends only on the port layer (never on the diagnostic
 * ec_step_test / ec_motion_test_* machinery), so this translation unit can
 * compile it in isolation with its own controllable doubles. */

/* --- controllable state --- */
static uint32_t g_now_ms;
static uint32_t g_counted_remaining;
static uint32_t g_counted_target;

static bool g_set_direction_ok = true;
static bool g_enable_axis_ok = true;
static bool g_start_counted_ok = true;
static bool g_servo_start_ok = true;

/* --- event log --- */
static ec_axis_t g_last_dir_axis;
static ec_direction_t g_last_direction;
static ec_axis_t g_last_enable_axis;
static ec_axis_t g_last_start_axis;
static uint32_t g_last_start_hz;
static uint32_t g_last_start_steps;
static uint16_t g_last_servo_pulse;
static int g_servo_start_count;
static uint16_t g_last_z_servo_pulse;
static int g_z_servo_start_count;
static int g_step_stop_count;
static int g_disable_count;
static int g_servo_stop_count;
static int g_z_servo_stop_count;

static void reset_log(void)
{
    g_set_direction_ok = true;
    g_enable_axis_ok = true;
    g_start_counted_ok = true;
    g_servo_start_ok = true;
    g_counted_remaining = 0U;
    g_counted_target = 0U;
    g_last_dir_axis = EC_AXIS_NONE;
    g_last_direction = EC_DIRECTION_0;
    g_last_enable_axis = EC_AXIS_NONE;
    g_last_start_axis = EC_AXIS_NONE;
    g_last_start_hz = 0U;
    g_last_start_steps = 0U;
    g_last_servo_pulse = 0U;
    g_servo_start_count = 0;
    g_last_z_servo_pulse = 0U;
    g_z_servo_start_count = 0;
    g_step_stop_count = 0;
    g_disable_count = 0;
    g_servo_stop_count = 0;
    g_z_servo_stop_count = 0;
}

/* --- port doubles --- */
bool ec_step_port_set_direction(ec_axis_t axis, ec_direction_t direction)
{
    if (!g_set_direction_ok) return false;
    g_last_dir_axis = axis;
    g_last_direction = direction;
    return true;
}

bool ec_step_port_enable_axis(ec_axis_t axis)
{
    if (!g_enable_axis_ok) return false;
    g_last_enable_axis = axis;
    return true;
}

bool ec_step_port_start_counted(ec_axis_t axis, uint32_t frequency_hz,
                                uint32_t steps)
{
    if (!g_start_counted_ok) return false;
    g_last_start_axis = axis;
    g_last_start_hz = frequency_hz;
    g_last_start_steps = steps;
    g_counted_remaining = steps;
    g_counted_target = steps;
    return true;
}

void ec_step_port_stop_all(void) { ++g_step_stop_count; }
void ec_step_port_disable_all(void) { ++g_disable_count; }
uint32_t ec_step_port_now_ms(void) { return g_now_ms; }
uint32_t ec_step_port_counted_remaining(void) { return g_counted_remaining; }
uint32_t ec_step_port_counted_target(void) { return g_counted_target; }

bool ec_servo_port_start(uint16_t pulse_us)
{
    if (!g_servo_start_ok) return false;
    g_last_servo_pulse = pulse_us;
    ++g_servo_start_count;
    return true;
}

void ec_servo_port_stop(void) { ++g_servo_stop_count; }

bool ec_servo_port_start_z(uint16_t pulse_us)
{
    if (!g_servo_start_ok) return false;
    g_last_z_servo_pulse = pulse_us;
    ++g_z_servo_start_count;
    return true;
}

void ec_servo_port_stop_z(void) { ++g_z_servo_stop_count; }

/* --- fixture --- */
/* Fixed 8-step pick-place program (sec. 6 EXECUTE_PICK_PLACE):
 *   approach -> pick -> grip.close -> safeTransfer -> placeApproach -> place
 *   -> grip.open -> home. */
static void fill_program(ec_axis_pick_place_t *p)
{
    memset(p, 0, sizeof(*p));

    p->step[0].kind = EC_AXIS_STEP_MOVE;
    p->step[0].axis = EC_AXIS_X;
    p->step[0].direction = EC_DIRECTION_0;
    p->step[0].steps = 100;

    p->step[1].kind = EC_AXIS_STEP_Z_SERVO;
    p->step[1].servo_pulse_us = EC_AXIS_Z_DOWN_US;

    p->step[2].kind = EC_AXIS_STEP_GRIPPER;
    p->step[2].servo_pulse_us = EC_AXIS_GRIPPER_CLOSE_US;

    p->step[3].kind = EC_AXIS_STEP_Z_SERVO;
    p->step[3].servo_pulse_us = EC_AXIS_Z_UP_US;

    p->step[4].kind = EC_AXIS_STEP_MOVE;
    p->step[4].axis = EC_AXIS_Y;
    p->step[4].direction = EC_DIRECTION_0;
    p->step[4].steps = 80;

    p->step[5].kind = EC_AXIS_STEP_Z_SERVO;
    p->step[5].servo_pulse_us = EC_AXIS_Z_DOWN_US;

    p->step[6].kind = EC_AXIS_STEP_GRIPPER;
    p->step[6].servo_pulse_us = EC_AXIS_GRIPPER_OPEN_US;

    p->step[7].kind = EC_AXIS_STEP_MOVE;
    p->step[7].axis = EC_AXIS_X;
    p->step[7].direction = EC_DIRECTION_1;
    p->step[7].steps = 100;
}

/* --- tests --- */
static void test_init_idle(void)
{
    reset_log();
    ec_axis_driver_init();
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_IDLE);
    TEST_ASSERT(ec_axis_driver_result() == EC_AXIS_RESULT_OK);
    TEST_ASSERT(ec_axis_driver_progress() == 0U);
}

static void test_full_sequence(void)
{
    ec_axis_pick_place_t prog;
    ec_axis_result_t r;
    uint32_t now;

    reset_log();
    fill_program(&prog);
    ec_axis_driver_init();
    g_now_ms = 0U;

    r = ec_axis_driver_start_pick_place(&prog);
    TEST_ASSERT(r == EC_AXIS_RESULT_OK);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_MOVING);
    TEST_ASSERT(ec_axis_driver_progress() == 0U);
    TEST_ASSERT(g_last_dir_axis == EC_AXIS_X);
    TEST_ASSERT(g_last_direction == EC_DIRECTION_0);
    TEST_ASSERT(g_last_enable_axis == EC_AXIS_X);
    TEST_ASSERT(g_last_start_axis == EC_AXIS_X);
    TEST_ASSERT(g_last_start_hz == EC_AXIS_MOVE_FREQUENCY_HZ);
    TEST_ASSERT(g_last_start_steps == 100U);
    TEST_ASSERT(g_counted_target == 100U);

    now = 0U;

    /* step 0 done -> start step 1 (Z servo down) */
    g_counted_remaining = 0U;
    r = ec_axis_driver_poll(now += 1U, 0U);
    TEST_ASSERT(r == EC_AXIS_RESULT_OK);
    TEST_ASSERT(ec_axis_driver_progress() == 1U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_GRIPPING);
    TEST_ASSERT(g_last_z_servo_pulse == EC_AXIS_Z_DOWN_US);
    TEST_ASSERT(g_z_servo_start_count == 1);

    /* step 1 settle -> start step 2 (gripper close) */
    now += EC_AXIS_GRIPPER_SETTLE_MS;
    r = ec_axis_driver_poll(now, 0U);
    TEST_ASSERT(ec_axis_driver_progress() == 2U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_GRIPPING);
    TEST_ASSERT(g_last_servo_pulse == EC_AXIS_GRIPPER_CLOSE_US);
    TEST_ASSERT(g_servo_start_count == 1);

    /* step 2 settle -> start step 3 (Z servo up) */
    now += EC_AXIS_GRIPPER_SETTLE_MS;
    r = ec_axis_driver_poll(now, 0U);
    TEST_ASSERT(ec_axis_driver_progress() == 3U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_GRIPPING);
    TEST_ASSERT(g_last_z_servo_pulse == EC_AXIS_Z_UP_US);
    TEST_ASSERT(g_z_servo_start_count == 2);

    /* step 3 settle -> start step 4 (Y move) */
    now += EC_AXIS_GRIPPER_SETTLE_MS;
    r = ec_axis_driver_poll(now, 0U);
    TEST_ASSERT(ec_axis_driver_progress() == 4U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_MOVING);
    TEST_ASSERT(g_last_start_axis == EC_AXIS_Y);
    TEST_ASSERT(g_last_start_steps == 80U);

    /* step 4 done -> start step 5 (Z servo down) */
    g_counted_remaining = 0U;
    r = ec_axis_driver_poll(now += 1U, 0U);
    TEST_ASSERT(ec_axis_driver_progress() == 5U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_GRIPPING);
    TEST_ASSERT(g_last_z_servo_pulse == EC_AXIS_Z_DOWN_US);
    TEST_ASSERT(g_z_servo_start_count == 3);

    /* step 5 settle -> start step 6 (gripper open) */
    now += EC_AXIS_GRIPPER_SETTLE_MS;
    r = ec_axis_driver_poll(now, 0U);
    TEST_ASSERT(ec_axis_driver_progress() == 6U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_GRIPPING);
    TEST_ASSERT(g_last_servo_pulse == EC_AXIS_GRIPPER_OPEN_US);
    TEST_ASSERT(g_servo_start_count == 2);

    /* step 6 settle -> start step 7 (X home) */
    now += EC_AXIS_GRIPPER_SETTLE_MS;
    r = ec_axis_driver_poll(now, 0U);
    TEST_ASSERT(ec_axis_driver_progress() == 7U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_MOVING);
    TEST_ASSERT(g_last_start_axis == EC_AXIS_X);

    /* step 7 done -> DONE */
    g_counted_remaining = 0U;
    r = ec_axis_driver_poll(now += 1U, 0U);
    TEST_ASSERT(r == EC_AXIS_RESULT_OK);
    TEST_ASSERT(ec_axis_driver_progress() == 8U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_DONE);
    TEST_ASSERT(ec_axis_driver_result() == EC_AXIS_RESULT_OK);
    TEST_ASSERT(g_step_stop_count >= 1);
    TEST_ASSERT(g_disable_count >= 1);
    TEST_ASSERT(g_servo_stop_count >= 1);
    TEST_ASSERT(g_z_servo_stop_count >= 1);
}

static void test_invalid_param(void)
{
    ec_axis_pick_place_t prog;

    reset_log();
    ec_axis_driver_init();

    TEST_ASSERT(ec_axis_driver_start_pick_place(NULL) ==
                EC_AXIS_RESULT_INVALID_PARAM);

    fill_program(&prog);
    prog.step[0].steps = 0U; /* zero-step move */
    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) ==
                EC_AXIS_RESULT_INVALID_PARAM);

    fill_program(&prog);
    prog.step[0].axis = EC_AXIS_NONE; /* invalid move axis */
    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) ==
                EC_AXIS_RESULT_INVALID_PARAM);

    fill_program(&prog);
    prog.step[0].direction = (ec_direction_t)2; /* invalid direction */
    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) ==
                EC_AXIS_RESULT_INVALID_PARAM);

    fill_program(&prog);
    prog.step[2].servo_pulse_us = 0U; /* gripper with zero pulse */
    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) ==
                EC_AXIS_RESULT_INVALID_PARAM);

    fill_program(&prog);
    prog.step[1].servo_pulse_us = 0U; /* Z servo with zero pulse */
    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) ==
                EC_AXIS_RESULT_INVALID_PARAM);
}

static void test_busy(void)
{
    ec_axis_pick_place_t prog;

    reset_log();
    fill_program(&prog);
    ec_axis_driver_init();
    g_now_ms = 0U;

    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) == EC_AXIS_RESULT_OK);
    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) ==
                EC_AXIS_RESULT_BUSY);
}

static void test_abort_inhibit(void)
{
    ec_axis_pick_place_t prog;

    reset_log();
    fill_program(&prog);
    ec_axis_driver_init();
    g_now_ms = 0U;

    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) == EC_AXIS_RESULT_OK);
    ec_axis_driver_poll(1U, EC_INPUT_X_HOME);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_FAULT);
    TEST_ASSERT(ec_axis_driver_result() == EC_AXIS_RESULT_ABORTED);
    TEST_ASSERT(g_step_stop_count >= 1);
}

static void test_timeout(void)
{
    ec_axis_pick_place_t prog;

    reset_log();
    fill_program(&prog);
    ec_axis_driver_init();
    g_now_ms = 0U;

    /* step 0 is an X move of 100 steps: timeout = 100*1000/500 + 1000 = 1200. */
    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) == EC_AXIS_RESULT_OK);
    g_counted_remaining = 100U; /* stall the counted move */

    ec_axis_driver_poll(1199U, 0U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_MOVING);

    ec_axis_driver_poll(1200U, 0U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_FAULT);
    TEST_ASSERT(ec_axis_driver_result() == EC_AXIS_RESULT_TIMEOUT);
}

static void test_port_fail(void)
{
    ec_axis_pick_place_t prog;

    reset_log();
    fill_program(&prog);
    ec_axis_driver_init();
    g_now_ms = 0U;

    g_start_counted_ok = false;
    ec_axis_driver_start_pick_place(&prog);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_FAULT);
    TEST_ASSERT(ec_axis_driver_result() == EC_AXIS_RESULT_PORT_FAIL);
}

static void test_stop(void)
{
    ec_axis_pick_place_t prog;

    reset_log();
    fill_program(&prog);
    ec_axis_driver_init();
    g_now_ms = 0U;

    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) == EC_AXIS_RESULT_OK);
    ec_axis_driver_stop();
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_IDLE);
    TEST_ASSERT(ec_axis_driver_result() == EC_AXIS_RESULT_OK);
    TEST_ASSERT(ec_axis_driver_progress() == 0U);
}

void test_axis_driver(void)
{
    test_init_idle();
    test_full_sequence();
    test_invalid_param();
    test_busy();
    test_abort_inhibit();
    test_timeout();
    test_port_fail();
    test_stop();
}

int main(void)
{
    test_axis_driver();
    puts("ALL AXIS DRIVER HOST TESTS PASSED");
    return EXIT_SUCCESS;
}
