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
static bool g_counted_aborted;
static bool g_counted_completed;

static bool g_set_direction_ok = true;
static bool g_enable_axis_ok = true;
static bool g_start_counted_ok = true;
static bool g_servo_start_ok = true;

/* --- event log --- */
static ec_axis_t g_last_dir_axis;
static ec_direction_t g_last_direction;
static ec_direction_t g_x_direction;
static ec_direction_t g_y_direction;
static ec_axis_t g_last_enable_axis;
static ec_axis_t g_last_start_axis;
static uint32_t g_last_start_hz;
static uint32_t g_last_start_steps;
static uint32_t g_last_xy_x_steps;
static uint32_t g_last_xy_y_steps;
static uint32_t g_last_xy_x_hz;
static uint32_t g_last_xy_y_hz;
static int g_xy_start_count;
static int g_enable_xy_count;
static uint16_t g_last_z_servo_pulse;
static int g_z_servo_start_count;
static int g_step_stop_count;
static int g_disable_count;
static int g_z_servo_stop_count;

static void reset_log(void)
{
    g_set_direction_ok = true;
    g_enable_axis_ok = true;
    g_start_counted_ok = true;
    g_servo_start_ok = true;
    g_counted_remaining = 0U;
    g_counted_target = 0U;
    g_counted_aborted = false;
    g_counted_completed = false;
    g_last_dir_axis = EC_AXIS_NONE;
    g_last_direction = EC_DIRECTION_0;
    g_x_direction = EC_DIRECTION_0;
    g_y_direction = EC_DIRECTION_0;
    g_last_enable_axis = EC_AXIS_NONE;
    g_last_start_axis = EC_AXIS_NONE;
    g_last_start_hz = 0U;
    g_last_start_steps = 0U;
    g_last_xy_x_steps = 0U;
    g_last_xy_y_steps = 0U;
    g_last_xy_x_hz = 0U;
    g_last_xy_y_hz = 0U;
    g_xy_start_count = 0;
    g_enable_xy_count = 0;
    g_last_z_servo_pulse = 0U;
    g_z_servo_start_count = 0;
    g_step_stop_count = 0;
    g_disable_count = 0;
    g_z_servo_stop_count = 0;
}

/* --- port doubles --- */
bool ec_step_port_set_direction(ec_axis_t axis, ec_direction_t direction)
{
    if (!g_set_direction_ok) return false;
    g_last_dir_axis = axis;
    g_last_direction = direction;
    if (axis == EC_AXIS_X) {
        g_x_direction = direction;
    } else if (axis == EC_AXIS_Y) {
        g_y_direction = direction;
    }
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
    g_counted_aborted = false;
    g_counted_completed = false;
    return true;
}

bool ec_step_port_enable_xy(void)
{
    ++g_enable_xy_count;
    return true;
}

bool ec_step_port_start_counted_xy(uint32_t x_steps, uint32_t x_frequency_hz,
                                   uint32_t y_steps, uint32_t y_frequency_hz)
{
    if (!g_start_counted_ok) return false;
    g_last_xy_x_steps = x_steps;
    g_last_xy_y_steps = y_steps;
    g_last_xy_x_hz = x_frequency_hz;
    g_last_xy_y_hz = y_frequency_hz;
    ++g_xy_start_count;
    g_counted_remaining = x_steps + y_steps;
    g_counted_target = x_steps + y_steps;
    g_counted_aborted = false;
    g_counted_completed = false;
    return true;
}

void ec_step_port_stop_all(void) { ++g_step_stop_count; }
void ec_step_port_disable_all(void) { ++g_disable_count; }
uint32_t ec_step_port_now_ms(void) { return g_now_ms; }
uint32_t ec_step_port_counted_remaining(void) { return g_counted_remaining; }
uint32_t ec_step_port_counted_target(void) { return g_counted_target; }

bool ec_step_port_take_counted_completion(ec_axis_t *completed_axis)
{
    if (!g_counted_completed) {
        return false;
    }
    g_counted_completed = false;
    if (completed_axis != NULL) {
        *completed_axis = EC_AXIS_NONE;
    }
    return true;
}

bool ec_step_port_take_counted_abort(void)
{
    bool pending = g_counted_aborted;
    g_counted_aborted = false;
    return pending;
}

static void simulate_counted_completion(void)
{
    g_counted_remaining = 0U;
    g_counted_completed = true;
}

static void simulate_counted_abort(void)
{
    g_counted_aborted = true;
    g_counted_remaining = 0U;
    g_counted_target = 0U;
    g_counted_completed = false;
}

bool ec_servo_port_start_z(uint16_t pulse_us)
{
    if (!g_servo_start_ok) return false;
    g_last_z_servo_pulse = pulse_us;
    ++g_z_servo_start_count;
    return true;
}

void ec_servo_port_stop_z(void) { ++g_z_servo_stop_count; }

/* 2026-09-16：ec_axis_driver.c 把 Z（EC_AXIS_STEP_Z_SERVO）和 GRIPPER 两条
 * 分支都收敛到 ec_servo_port_start() —— 实机是单舵机联动，接在 PB10/TIM2_CH3，
 * 即原 GRIPPER 通道（理由见 ec_axis_driver.c 该分支的注释）。
 * 本 fixture 原先只在 ec_servo_port_start_z() 上记脉冲，驱动改走 start() 之后
 * g_last_z_servo_pulse 永远是 0，Z 相关断言全部假红。驱动哪条通道就记在哪条通道上。 */
bool ec_servo_port_start(uint16_t pulse_us)
{
    if (!g_servo_start_ok) return false;
    g_last_z_servo_pulse = pulse_us;
    ++g_z_servo_start_count;
    return true;
}

void ec_servo_port_stop(void) { }

/* --- fixture --- */
/* Fixed 7-step pick-place program, single-servo linkage (lower = claw open,
 * raise = claw close):
 *   MOVE -> Z down (open) -> Z up (close) -> MOVE -> Z down (open)
 *   -> Z up (close) -> MOVE. */
static void fill_program(ec_axis_pick_place_t *p)
{
    memset(p, 0, sizeof(*p));

    p->step[0].kind = EC_AXIS_STEP_MOVE;
    p->step[0].axis = EC_AXIS_X;
    p->step[0].direction = EC_DIRECTION_0;
    p->step[0].steps = 100;

    p->step[1].kind = EC_AXIS_STEP_Z_SERVO;
    p->step[1].servo_pulse_us = EC_AXIS_Z_DOWN_US;   /* lower = claw open */

    p->step[2].kind = EC_AXIS_STEP_Z_SERVO;
    p->step[2].servo_pulse_us = EC_AXIS_Z_UP_US;     /* raise = claw close */

    p->step[3].kind = EC_AXIS_STEP_MOVE;
    p->step[3].axis = EC_AXIS_Y;
    p->step[3].direction = EC_DIRECTION_0;
    p->step[3].steps = 80;

    p->step[4].kind = EC_AXIS_STEP_Z_SERVO;
    p->step[4].servo_pulse_us = EC_AXIS_Z_DOWN_US;   /* lower = claw open */

    p->step[5].kind = EC_AXIS_STEP_Z_SERVO;
    p->step[5].servo_pulse_us = EC_AXIS_Z_UP_US;     /* raise = claw close */

    p->step[6].kind = EC_AXIS_STEP_MOVE;
    p->step[6].axis = EC_AXIS_Y;
    p->step[6].direction = EC_DIRECTION_1;
    p->step[6].steps = 80;
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
    TEST_ASSERT(g_last_start_axis == EC_AXIS_X);
    TEST_ASSERT(g_last_start_steps == 100U);

    now = 0U;

    /* step 0 done -> step 1 (Z down = claw open) */
    simulate_counted_completion();
    r = ec_axis_driver_poll(now += 1U, 0U);
    TEST_ASSERT(r == EC_AXIS_RESULT_OK);
    TEST_ASSERT(ec_axis_driver_progress() == 1U);
    TEST_ASSERT(ec_axis_driver_completed_move_count() == 1U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_GRIPPING);
    TEST_ASSERT(g_last_z_servo_pulse == EC_AXIS_Z_DOWN_US);
    TEST_ASSERT(g_z_servo_start_count == 1);

    /* step 1 settle -> step 2 (Z up = claw close) */
    now += EC_AXIS_SERVO_SETTLE_MS;
    r = ec_axis_driver_poll(now, 0U);
    TEST_ASSERT(ec_axis_driver_progress() == 2U);
    TEST_ASSERT(ec_axis_driver_completed_move_count() == 1U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_GRIPPING);
    TEST_ASSERT(g_last_z_servo_pulse == EC_AXIS_Z_UP_US);
    TEST_ASSERT(g_z_servo_start_count == 2);

    /* step 2 settle -> step 3 (Y move) */
    now += EC_AXIS_SERVO_SETTLE_MS;
    r = ec_axis_driver_poll(now, 0U);
    TEST_ASSERT(ec_axis_driver_progress() == 3U);
    TEST_ASSERT(ec_axis_driver_completed_move_count() == 1U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_MOVING);
    TEST_ASSERT(g_last_start_axis == EC_AXIS_Y);
    TEST_ASSERT(g_last_start_steps == 80U);

    /* step 3 done -> step 4 (Z down = claw open) */
    simulate_counted_completion();
    r = ec_axis_driver_poll(now += 1U, 0U);
    TEST_ASSERT(ec_axis_driver_progress() == 4U);
    TEST_ASSERT(ec_axis_driver_completed_move_count() == 2U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_GRIPPING);
    TEST_ASSERT(g_last_z_servo_pulse == EC_AXIS_Z_DOWN_US);
    TEST_ASSERT(g_z_servo_start_count == 3);

    /* step 4 settle -> step 5 (Z up = claw close) */
    now += EC_AXIS_SERVO_SETTLE_MS;
    r = ec_axis_driver_poll(now, 0U);
    TEST_ASSERT(ec_axis_driver_progress() == 5U);
    TEST_ASSERT(ec_axis_driver_completed_move_count() == 2U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_GRIPPING);
    TEST_ASSERT(g_last_z_servo_pulse == EC_AXIS_Z_UP_US);
    TEST_ASSERT(g_z_servo_start_count == 4);

    /* step 5 settle -> step 6 (Y move home) */
    now += EC_AXIS_SERVO_SETTLE_MS;
    r = ec_axis_driver_poll(now, 0U);
    TEST_ASSERT(ec_axis_driver_progress() == 6U);
    TEST_ASSERT(ec_axis_driver_completed_move_count() == 2U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_MOVING);
    TEST_ASSERT(g_last_start_axis == EC_AXIS_Y);
    TEST_ASSERT(g_last_direction == EC_DIRECTION_1);

    /* step 6 done -> DONE */
    simulate_counted_completion();
    r = ec_axis_driver_poll(now += 1U, 0U);
    TEST_ASSERT(r == EC_AXIS_RESULT_OK);
    TEST_ASSERT(ec_axis_driver_progress() == 7U);
    TEST_ASSERT(ec_axis_driver_completed_move_count() == 3U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_DONE);
    TEST_ASSERT(ec_axis_driver_result() == EC_AXIS_RESULT_OK);
    TEST_ASSERT(g_step_stop_count >= 1);
    TEST_ASSERT(g_disable_count >= 1);
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
    prog.step[2].servo_pulse_us = 0U; /* Z servo with zero pulse */
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
    /* 2026-09-15：安全遮罩已收敛为仅 EC_INPUT_ESTOP_FB（X/Y 不装限位开关），
     * 因此必须用 ESTOP 才能触发 inhibit；原先用 EC_INPUT_X_HOME 不再生效。 */
    ec_axis_driver_poll(1U, EC_INPUT_ESTOP_FB);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_FAULT);
    TEST_ASSERT(ec_axis_driver_result() == EC_AXIS_RESULT_ABORTED);
    TEST_ASSERT(g_step_stop_count >= 1);
}

/* A timer/ESTOP abort clears the port counters just like a normal finish. The
 * driver must not mistake that zero for a completed move and advance the
 * watchdog token source. */
static void test_counter_zero_without_normal_completion_is_fault(void)
{
    ec_axis_pick_place_t prog;

    reset_log();
    fill_program(&prog);
    ec_axis_driver_init();
    g_now_ms = 0U;

    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) == EC_AXIS_RESULT_OK);
    simulate_counted_abort();
    TEST_ASSERT(ec_axis_driver_poll(1U, 0U) == EC_AXIS_RESULT_ABORTED);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_FAULT);
    TEST_ASSERT(ec_axis_driver_progress() == 0U);
    TEST_ASSERT(ec_axis_driver_completed_move_count() == 0U);
}

/* If the ISR completed the move before the poll but the main loop is serviced
 * exactly at the timeout boundary, the latched normal completion wins. The
 * watchdog must see the real completed move rather than a spurious timeout. */
static void test_completion_wins_at_timeout_boundary(void)
{
    ec_axis_pick_place_t prog;

    reset_log();
    fill_program(&prog);
    ec_axis_driver_init();
    g_now_ms = 0U;

    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) == EC_AXIS_RESULT_OK);
    simulate_counted_completion();
    TEST_ASSERT(ec_axis_driver_poll(1200U, 0U) == EC_AXIS_RESULT_OK);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_GRIPPING);
    TEST_ASSERT(ec_axis_driver_progress() == 1U);
    TEST_ASSERT(ec_axis_driver_completed_move_count() == 1U);
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
    TEST_ASSERT(ec_axis_driver_completed_move_count() == 0U);
}

static void test_mm10_to_steps(void)
{
    /* X/Y share 80 steps/mm, so 0.1mm (mm10) -> 8 steps. */
    TEST_ASSERT(ec_axis_mm10_to_steps(EC_AXIS_X, 1450) == 11600U); /* +145.0mm */
    TEST_ASSERT(ec_axis_mm10_to_steps(EC_AXIS_X, -1450) == 11600U);
    TEST_ASSERT(ec_axis_mm10_to_steps(EC_AXIS_X, 10) == 80U);      /* +1.0mm */
    TEST_ASSERT(ec_axis_mm10_to_steps(EC_AXIS_X, 1) == 8U);        /* +0.1mm */
    TEST_ASSERT(ec_axis_mm10_to_steps(EC_AXIS_X, 0) == 0U);
    TEST_ASSERT(ec_axis_mm10_to_steps(EC_AXIS_X, -10) == 80U);
    TEST_ASSERT(ec_axis_mm10_to_steps(EC_AXIS_Y, 1000) == 8000U);  /* +100.0mm */
    TEST_ASSERT(ec_axis_mm10_to_steps(EC_AXIS_Z, 100) == 0U);
    TEST_ASSERT(ec_axis_mm10_to_steps(EC_AXIS_NONE, 100) == 0U);
}

/* Build a 7-step program whose three waypoint moves are all MOVE_XY. */
static void fill_xy_program(ec_axis_pick_place_t *p)
{
    memset(p, 0, sizeof(*p));

    p->step[0].kind = EC_AXIS_STEP_MOVE_XY;
    p->step[0].direction = EC_DIRECTION_0;
    p->step[0].steps = 100U;
    p->step[0].y_direction = EC_DIRECTION_1;
    p->step[0].y_steps = 40U;

    p->step[1].kind = EC_AXIS_STEP_Z_SERVO;
    p->step[1].servo_pulse_us = EC_AXIS_Z_DOWN_US;

    p->step[2].kind = EC_AXIS_STEP_Z_SERVO;
    p->step[2].servo_pulse_us = EC_AXIS_Z_UP_US;

    p->step[3].kind = EC_AXIS_STEP_MOVE_XY;
    p->step[3].direction = EC_DIRECTION_1;
    p->step[3].steps = 50U;
    p->step[3].y_direction = EC_DIRECTION_0;
    p->step[3].y_steps = 60U;

    p->step[4].kind = EC_AXIS_STEP_Z_SERVO;
    p->step[4].servo_pulse_us = EC_AXIS_Z_DOWN_US;

    p->step[5].kind = EC_AXIS_STEP_Z_SERVO;
    p->step[5].servo_pulse_us = EC_AXIS_Z_UP_US;

    p->step[6].kind = EC_AXIS_STEP_MOVE_XY;
    p->step[6].direction = EC_DIRECTION_0;
    p->step[6].steps = 100U;
    p->step[6].y_direction = EC_DIRECTION_0;
    p->step[6].y_steps = 40U;
}

static void test_move_xy(void)
{
    ec_axis_pick_place_t prog;
    ec_axis_result_t r;

    reset_log();
    ec_axis_driver_init();
    fill_xy_program(&prog);

    /* P0-FIX (2026-08-28): single-axis MOVE_XY moves are now legal. A move
     * with x_steps=100 / y_steps=0 (X-only) or x_steps=0 / y_steps=40 (Y-only)
     * starts OK; only a move with BOTH step counts zero is rejected. */
    prog.step[0].y_steps = 0U;   /* X-only move */
    ec_axis_driver_init();
    reset_log();
    g_now_ms = 0U;
    r = ec_axis_driver_start_pick_place(&prog);
    TEST_ASSERT(r == EC_AXIS_RESULT_OK);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_MOVING);
    TEST_ASSERT(g_last_xy_x_steps == 100U);
    TEST_ASSERT(g_last_xy_y_steps == 0U);

    /* The X-only move also completes: timeout tracks the non-zero axis
     * (100 steps @ 500 Hz = 200 ms + 1000 ms margin = 1200 ms), and a finished
     * counter advances to the next program step. */
    simulate_counted_completion();
    r = ec_axis_driver_poll(1U, 0U);
    TEST_ASSERT(r == EC_AXIS_RESULT_OK);
    TEST_ASSERT(ec_axis_driver_progress() == 1U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_GRIPPING);

    prog.step[0].steps = 0U;   /* Y-only move */
    prog.step[0].y_steps = 40U;
    ec_axis_driver_init();
    reset_log();
    g_now_ms = 0U;
    r = ec_axis_driver_start_pick_place(&prog);
    TEST_ASSERT(r == EC_AXIS_RESULT_OK);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_MOVING);
    TEST_ASSERT(g_last_xy_x_steps == 0U);
    TEST_ASSERT(g_last_xy_y_steps == 40U);

    prog.step[0].steps = 0U;   /* both zero -> still invalid */
    prog.step[0].y_steps = 0U;
    ec_axis_driver_init();
    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) ==
                EC_AXIS_RESULT_INVALID_PARAM);

    /* restore the full XY fixture for the remaining checks */
    prog.step[0].steps = 100U;
    prog.step[0].y_steps = 40U;

    /* invalid y_direction -> invalid */
    prog.step[0].y_direction = (ec_direction_t)2;
    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) ==
                EC_AXIS_RESULT_INVALID_PARAM);
    prog.step[0].y_direction = EC_DIRECTION_1;

    /* Valid start: the first MOVE_XY drives the XY port, not the single-axis
     * port. (reset_log clears the counters from the single-axis attempts
     * above.) */
    reset_log();
    g_now_ms = 0U;
    r = ec_axis_driver_start_pick_place(&prog);
    TEST_ASSERT(r == EC_AXIS_RESULT_OK);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_MOVING);
    TEST_ASSERT(g_xy_start_count == 1);
    TEST_ASSERT(g_enable_xy_count == 1);
    TEST_ASSERT(g_last_xy_x_steps == 100U);
    TEST_ASSERT(g_last_xy_y_steps == 40U);
    TEST_ASSERT(g_x_direction == EC_DIRECTION_0);
    TEST_ASSERT(g_y_direction == EC_DIRECTION_1);
    TEST_ASSERT(g_counted_remaining == 140U); /* x + y both counting */
}

static void test_move_xy_timeout(void)
{
    ec_axis_pick_place_t prog;

    reset_log();
    ec_axis_driver_init();
    fill_xy_program(&prog);
    g_now_ms = 0U;

    /* step 0 is MOVE_XY X=100 (200ms) + Y=40 (80ms) @500Hz; timeout tracks the
     * slower X axis: 200ms + 1000ms margin = 1200ms. */
    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) == EC_AXIS_RESULT_OK);
    g_counted_remaining = 140U; /* stall both axes */

    ec_axis_driver_poll(1199U, 0U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_MOVING);

    ec_axis_driver_poll(1200U, 0U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_FAULT);
    TEST_ASSERT(ec_axis_driver_result() == EC_AXIS_RESULT_TIMEOUT);
}

/* One-step program holding a single interpolated dual-axis move. The remaining
 * array slots stay zeroed (unused), which the driver tolerates. */
static void fill_interp_program(ec_axis_pick_place_t *p, int32_t x_steps,
                                int32_t y_steps)
{
    memset(p, 0, sizeof(*p));
    p->step[0].kind = EC_AXIS_STEP_XY_INTERP;
    p->step[0].target_x_steps = x_steps;
    p->step[0].target_y_steps = y_steps;
}

static void test_xy_interp(void)
{
    ec_axis_pick_place_t prog;

    /* Signed targets map to per-axis (steps, direction); the shorter leg is
     * slowed down proportionally so both legs finish together, which is the
     * straight line between the waypoints. */
    reset_log();
    fill_interp_program(&prog, 300, -200);
    ec_axis_driver_init();
    g_now_ms = 0U;
    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) == EC_AXIS_RESULT_OK);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_MOVING);
    TEST_ASSERT(g_xy_start_count == 1);
    TEST_ASSERT(g_enable_xy_count == 1);
    TEST_ASSERT(g_last_xy_x_steps == 300U);
    TEST_ASSERT(g_last_xy_y_steps == 200U);
    TEST_ASSERT(g_x_direction == EC_DIRECTION_0);
    TEST_ASSERT(g_y_direction == EC_DIRECTION_1);   /* negative Y target */
    TEST_ASSERT(g_last_xy_x_hz == 500U);
    TEST_ASSERT(g_last_xy_y_hz == 333U);            /* 500 * 200 / 300 */
    TEST_ASSERT(g_counted_remaining == 500U);

    /* Timeout tracks the major axis: 300 steps @ 500 Hz = 600 ms + 1000 ms. */
    g_counted_remaining = 500U;
    ec_axis_driver_poll(1599U, 0U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_MOVING);
    ec_axis_driver_poll(1600U, 0U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_FAULT);
    TEST_ASSERT(ec_axis_driver_result() == EC_AXIS_RESULT_TIMEOUT);

    /* Completion advances the program; a one-step program is then DONE. */
    reset_log();
    ec_axis_driver_init();
    g_now_ms = 0U;
    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) == EC_AXIS_RESULT_OK);
    simulate_counted_completion();
    TEST_ASSERT(ec_axis_driver_poll(1U, 0U) == EC_AXIS_RESULT_OK);
    TEST_ASSERT(ec_axis_driver_progress() == 1U);
    TEST_ASSERT(ec_axis_driver_state() == EC_AXIS_STATE_DONE);

    /* Axis-aligned interp: the zero-length leg keeps the minimum step rate. */
    reset_log();
    fill_interp_program(&prog, 0, 400);
    ec_axis_driver_init();
    g_now_ms = 0U;
    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) == EC_AXIS_RESULT_OK);
    TEST_ASSERT(g_last_xy_x_steps == 0U);
    TEST_ASSERT(g_last_xy_y_steps == 400U);
    TEST_ASSERT(g_last_xy_x_hz == EC_STEP_MIN_HZ);
    TEST_ASSERT(g_last_xy_y_hz == 500U);

    /* A step with both targets zero is not a move. */
    fill_interp_program(&prog, 0, 0);
    ec_axis_driver_init();
    TEST_ASSERT(ec_axis_driver_start_pick_place(&prog) ==
                EC_AXIS_RESULT_INVALID_PARAM);
}

void test_axis_driver(void)
{
    test_init_idle();
    test_full_sequence();
    test_invalid_param();
    test_busy();
    test_abort_inhibit();
    test_counter_zero_without_normal_completion_is_fault();
    test_completion_wins_at_timeout_boundary();
    test_timeout();
    test_port_fail();
    test_stop();
    test_mm10_to_steps();
    test_move_xy();
    test_move_xy_timeout();
    test_xy_interp();
}

int main(void)
{
    test_axis_driver();
    puts("ALL AXIS DRIVER HOST TESTS PASSED");
    return EXIT_SUCCESS;
}
