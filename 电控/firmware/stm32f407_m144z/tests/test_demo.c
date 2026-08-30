#include "test_support.h"

#include "ec_demo.h"
#include "ec_inputs.h"
#include "ec_servo_test.h"
#include "ec_step_test.h"

#include <stdlib.h>

/* Host-test doubles for the ec_step_port_* / ec_servo_port_* port layer.
 * ec_demo.c depends only on the port layer (never on the diagnostic
 * ec_step_test / ec_servo_test / ec_group_test machinery), so this translation
 * unit compiles it in isolation with its own controllable doubles. */

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
    g_now_ms = 0U;
    g_counted_remaining = 0U;
    g_counted_target = 0U;
    g_last_dir_axis = EC_AXIS_NONE;
    g_last_direction = EC_DIRECTION_0;
    g_last_enable_axis = EC_AXIS_NONE;
    g_last_start_axis = EC_AXIS_NONE;
    g_last_start_hz = 0U;
    g_last_start_steps = 0U;
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

bool ec_servo_port_start_z(uint16_t pulse_us)
{
    if (!g_servo_start_ok) return false;
    g_last_z_servo_pulse = pulse_us;
    ++g_z_servo_start_count;
    return true;
}

void ec_servo_port_stop_z(void) { ++g_z_servo_stop_count; }

/* --- tests --- */
static void test_init_idle(void)
{
    reset_log();
    ec_demo_init();
    TEST_ASSERT(!ec_demo_is_active());
}

static void test_start_moves_x_first(void)
{
    reset_log();
    ec_demo_init();

    TEST_ASSERT(ec_demo_start(0U));
    TEST_ASSERT(ec_demo_is_active());
    TEST_ASSERT(g_last_start_axis == EC_AXIS_X);
    TEST_ASSERT(g_last_direction == EC_DIRECTION_0);
    TEST_ASSERT(g_last_start_hz == 800U);
    TEST_ASSERT(g_last_start_steps == 13200U);
}

static void test_full_loop_wraps(void)
{
    uint32_t now;

    reset_log();
    ec_demo_init();
    TEST_ASSERT(ec_demo_start(0U));
    now = 0U;

    /* phase 0 (X out) done -> phase 1 (X back) */
    g_counted_remaining = 0U;
    ec_demo_poll(now += 1U, 0U);
    TEST_ASSERT(ec_demo_is_active());
    TEST_ASSERT(g_last_start_axis == EC_AXIS_X);
    TEST_ASSERT(g_last_direction == EC_DIRECTION_1);

    /* phase 1 done -> phase 2 (Y out) */
    g_counted_remaining = 0U;
    ec_demo_poll(now += 1U, 0U);
    TEST_ASSERT(g_last_start_axis == EC_AXIS_Y);
    TEST_ASSERT(g_last_direction == EC_DIRECTION_0);

    /* phase 2 done -> phase 3 (Y back) */
    g_counted_remaining = 0U;
    ec_demo_poll(now += 1U, 0U);
    TEST_ASSERT(g_last_start_axis == EC_AXIS_Y);
    TEST_ASSERT(g_last_direction == EC_DIRECTION_1);

    /* phase 3 done -> phase 4 (Z open) */
    g_counted_remaining = 0U;
    ec_demo_poll(now += 1U, 0U);
    TEST_ASSERT(g_last_z_servo_pulse == 1000U);
    TEST_ASSERT(g_z_servo_start_count == 1);

    /* phase 4 settle -> phase 5 (Z close) */
    ec_demo_poll(now += 200U, 0U);
    TEST_ASSERT(g_last_z_servo_pulse == 1900U);
    TEST_ASSERT(g_z_servo_start_count == 2);

    /* phase 5 settle -> wraps to phase 0 (X out) again */
    ec_demo_poll(now += 200U, 0U);
    TEST_ASSERT(ec_demo_is_active());
    TEST_ASSERT(g_last_start_axis == EC_AXIS_X);
    TEST_ASSERT(g_last_direction == EC_DIRECTION_0);
    TEST_ASSERT(g_last_start_steps == 13200U);
}

static void test_stop(void)
{
    reset_log();
    ec_demo_init();
    TEST_ASSERT(ec_demo_start(0U));

    ec_demo_stop();
    TEST_ASSERT(!ec_demo_is_active());
    TEST_ASSERT(g_step_stop_count >= 1);
    TEST_ASSERT(g_disable_count >= 1);
    TEST_ASSERT(g_z_servo_stop_count >= 1);
}

static void test_inhibit_aborts(void)
{
    reset_log();
    ec_demo_init();
    TEST_ASSERT(ec_demo_start(0U));

    ec_demo_poll(1U, EC_INPUT_X_HOME);
    TEST_ASSERT(!ec_demo_is_active());
    TEST_ASSERT(g_step_stop_count >= 1);
}

static void test_start_inhibited(void)
{
    reset_log();
    ec_demo_init();

    TEST_ASSERT(!ec_demo_start(EC_INPUT_ESTOP_FB));
    TEST_ASSERT(!ec_demo_is_active());
}

static void test_start_busy(void)
{
    reset_log();
    ec_demo_init();
    TEST_ASSERT(ec_demo_start(0U));

    TEST_ASSERT(!ec_demo_start(0U));
    TEST_ASSERT(ec_demo_is_active());
}

static void test_move_timeout(void)
{
    reset_log();
    ec_demo_init();
    TEST_ASSERT(ec_demo_start(0U));

    /* phase 0 move: timeout = 13200*1000/800 + 1000 = 17500 ms. Stall it. */
    g_counted_remaining = 13200U;
    ec_demo_poll(17499U, 0U);
    TEST_ASSERT(ec_demo_is_active());

    ec_demo_poll(17500U, 0U);
    TEST_ASSERT(!ec_demo_is_active());
}

static void test_port_fail_deactivates(void)
{
    reset_log();
    ec_demo_init();

    g_start_counted_ok = false;
    TEST_ASSERT(!ec_demo_start(0U));
    TEST_ASSERT(!ec_demo_is_active());
}

void test_demo(void)
{
    test_init_idle();
    test_start_moves_x_first();
    test_full_loop_wraps();
    test_stop();
    test_inhibit_aborts();
    test_start_inhibited();
    test_start_busy();
    test_move_timeout();
    test_port_fail_deactivates();
}

int main(void)
{
    test_demo();
    puts("ALL DEMO HOST TESTS PASSED");
    return EXIT_SUCCESS;
}
