#include "ec_group_test.h"
#include "ec_inputs.h"
#include "test_support.h"

typedef enum {
    FAIL_NONE = 0,
    FAIL_X_DIRECTION,
    FAIL_Y_DIRECTION,
    FAIL_ENABLE,
    FAIL_X_START,
    FAIL_Y_START,
    FAIL_SERVO_START
} fail_stage_t;

static uint32_t fake_group_now_ms;
static fail_stage_t fail_stage;
static unsigned direction_calls;
static unsigned enable_calls;
static unsigned step_start_calls;
static unsigned servo_start_calls;
static unsigned group_stop_calls;
static ec_direction_t recorded_x_direction;
static ec_direction_t recorded_y_direction;
static uint16_t recorded_servo_us;

bool ec_group_port_set_direction(ec_axis_t axis, ec_direction_t direction)
{
    direction_calls++;
    if (axis == EC_AXIS_X) {
        recorded_x_direction = direction;
        return fail_stage != FAIL_X_DIRECTION;
    }
    TEST_ASSERT(axis == EC_AXIS_Y);
    recorded_y_direction = direction;
    return fail_stage != FAIL_Y_DIRECTION;
}

bool ec_group_port_enable_xy(void)
{
    enable_calls++;
    return fail_stage != FAIL_ENABLE;
}

bool ec_group_port_start_step(ec_axis_t axis, uint32_t frequency_hz)
{
    TEST_ASSERT(frequency_hz == 100U);
    step_start_calls++;
    if (axis == EC_AXIS_X) return fail_stage != FAIL_X_START;
    TEST_ASSERT(axis == EC_AXIS_Y);
    return fail_stage != FAIL_Y_START;
}

bool ec_group_port_start_servo(uint16_t pulse_us)
{
    servo_start_calls++;
    recorded_servo_us = pulse_us;
    return fail_stage != FAIL_SERVO_START;
}

void ec_group_port_stop_all(void)
{
    group_stop_calls++;
}

uint32_t ec_group_port_now_ms(void)
{
    return fake_group_now_ms;
}

static void reset_group_fixture(void)
{
    fake_group_now_ms = 100U;
    fail_stage = FAIL_NONE;
    direction_calls = 0U;
    enable_calls = 0U;
    step_start_calls = 0U;
    servo_start_calls = 0U;
    group_stop_calls = 0U;
    recorded_x_direction = EC_DIRECTION_0;
    recorded_y_direction = EC_DIRECTION_0;
    recorded_servo_us = 0U;
    ec_group_test_init();
}

static void start_group(ec_direction_t x_direction,
                        ec_direction_t y_direction, uint16_t servo_us)
{
    TEST_ASSERT(ec_group_test_arm(0U, false, false));
    TEST_ASSERT(ec_group_test_start(x_direction, y_direction, servo_us,
                                    0U, false, false));
}

static void test_directions_and_servo_positions(void)
{
    unsigned x;
    unsigned y;
    const uint16_t pulses[] = { UINT16_C(1100), UINT16_C(1900) };
    unsigned p;

    for (x = 0U; x < 2U; ++x) {
        for (y = 0U; y < 2U; ++y) {
            for (p = 0U; p < 2U; ++p) {
                reset_group_fixture();
                start_group((ec_direction_t)x, (ec_direction_t)y, pulses[p]);
                TEST_ASSERT(ec_group_test_mode() == EC_GROUP_TEST_SETTLING);
                TEST_ASSERT(recorded_x_direction == (ec_direction_t)x);
                TEST_ASSERT(recorded_y_direction == (ec_direction_t)y);
                TEST_ASSERT(ec_group_test_servo_pulse_us() == pulses[p]);
                ec_group_test_poll(120U, 0U);
                TEST_ASSERT(ec_group_test_mode() == EC_GROUP_TEST_RUNNING);
                TEST_ASSERT(step_start_calls == 2U);
                TEST_ASSERT(servo_start_calls == 1U);
                TEST_ASSERT(recorded_servo_us == pulses[p]);
            }
        }
    }
}

static void test_partial_start_failures(void)
{
    fail_stage_t stage;

    for (stage = FAIL_X_DIRECTION; stage <= FAIL_SERVO_START;
         stage = (fail_stage_t)(stage + 1)) {
        reset_group_fixture();
        fail_stage = stage;
        TEST_ASSERT(ec_group_test_arm(0U, false, false));
        if (stage <= FAIL_ENABLE) {
            TEST_ASSERT(!ec_group_test_start(EC_DIRECTION_0,
                                             EC_DIRECTION_1,
                                             UINT16_C(1100), 0U,
                                             false, false));
        } else {
            TEST_ASSERT(ec_group_test_start(EC_DIRECTION_0,
                                            EC_DIRECTION_1,
                                            UINT16_C(1100), 0U,
                                            false, false));
            ec_group_test_poll(120U, 0U);
        }
        TEST_ASSERT(ec_group_test_mode() == EC_GROUP_TEST_IDLE);
        TEST_ASSERT(group_stop_calls >= 1U);
    }
}

void test_group_test(void)
{
    uint16_t input_bit;

    reset_group_fixture();
    ec_group_test_stop();
    TEST_ASSERT(group_stop_calls == 0U);
    TEST_ASSERT(ec_group_test_arm(0U, false, false));
    TEST_ASSERT(!ec_group_test_arm(0U, false, false));
    ec_group_test_stop();
    TEST_ASSERT(group_stop_calls == 0U);

    reset_group_fixture();
    TEST_ASSERT(!ec_group_test_start(EC_DIRECTION_0, EC_DIRECTION_0,
                                     UINT16_C(1100), 0U, false, false));
    TEST_ASSERT(!ec_group_test_arm(EC_INPUT_START, false, false));
    TEST_ASSERT(!ec_group_test_arm(0U, true, false));
    TEST_ASSERT(!ec_group_test_arm(0U, false, true));

    fake_group_now_ms = 1000U;
    TEST_ASSERT(ec_group_test_arm(0U, false, false));
    fake_group_now_ms = 11000U;
    TEST_ASSERT(ec_group_test_start(EC_DIRECTION_0, EC_DIRECTION_0,
                                    UINT16_C(1100), 0U, false, false));
    ec_group_test_stop();

    fake_group_now_ms = 12000U;
    TEST_ASSERT(ec_group_test_arm(0U, false, false));
    fake_group_now_ms = 22001U;
    TEST_ASSERT(!ec_group_test_start(EC_DIRECTION_0, EC_DIRECTION_0,
                                     UINT16_C(1100), 0U, false, false));
    TEST_ASSERT(!ec_group_test_is_armed());

    fake_group_now_ms = 23000U;
    TEST_ASSERT(ec_group_test_arm(0U, false, false));
    ec_group_test_poll(33000U, 0U);
    TEST_ASSERT(ec_group_test_is_armed());
    ec_group_test_poll(33001U, 0U);
    TEST_ASSERT(!ec_group_test_is_armed());

    fake_group_now_ms = 34000U;
    TEST_ASSERT(ec_group_test_arm(0U, false, false));
    TEST_ASSERT(!ec_group_test_start((ec_direction_t)7, EC_DIRECTION_0,
                                     UINT16_C(1100), 0U, false, false));
    TEST_ASSERT(!ec_group_test_start(EC_DIRECTION_0, EC_DIRECTION_0,
                                     UINT16_C(1100), 0U, false, false));

    fake_group_now_ms = 35000U;
    TEST_ASSERT(ec_group_test_arm(0U, false, false));
    TEST_ASSERT(!ec_group_test_start(EC_DIRECTION_0, EC_DIRECTION_0,
                                     UINT16_C(1500), 0U, false, false));

    fake_group_now_ms = 36000U;
    TEST_ASSERT(ec_group_test_arm(0U, false, false));
    TEST_ASSERT(!ec_group_test_start(EC_DIRECTION_0, EC_DIRECTION_0,
                                     UINT16_C(1100), 0U, true, false));

    fake_group_now_ms = 37000U;
    TEST_ASSERT(ec_group_test_arm(0U, false, false));
    TEST_ASSERT(!ec_group_test_start(EC_DIRECTION_0, EC_DIRECTION_0,
                                     UINT16_C(1100), 0U, false, true));

    reset_group_fixture();
    start_group(EC_DIRECTION_1, EC_DIRECTION_0, UINT16_C(1900));
    ec_group_test_poll(119U, 0U);
    TEST_ASSERT(ec_group_test_mode() == EC_GROUP_TEST_SETTLING);
    ec_group_test_poll(120U, 0U);
    TEST_ASSERT(ec_group_test_mode() == EC_GROUP_TEST_RUNNING);
    ec_group_test_poll(2119U, 0U);
    TEST_ASSERT(ec_group_test_mode() == EC_GROUP_TEST_RUNNING);
    ec_group_test_poll(10120U, 0U);
    TEST_ASSERT(ec_group_test_mode() == EC_GROUP_TEST_IDLE);

    for (input_bit = UINT16_C(1); input_bit <= EC_INPUT_MANUAL_RESET;
         input_bit = (uint16_t)(input_bit << 1U)) {
        reset_group_fixture();
        TEST_ASSERT(ec_group_test_arm(0U, false, false));
        ec_group_test_poll(101U, input_bit);
        TEST_ASSERT(ec_group_test_mode() == EC_GROUP_TEST_IDLE);
        TEST_ASSERT(group_stop_calls == 0U);

        reset_group_fixture();
        start_group(EC_DIRECTION_0, EC_DIRECTION_1, UINT16_C(1100));
        ec_group_test_poll(101U, input_bit);
        TEST_ASSERT(ec_group_test_mode() == EC_GROUP_TEST_IDLE);
        TEST_ASSERT(group_stop_calls == 1U);

        reset_group_fixture();
        start_group(EC_DIRECTION_0, EC_DIRECTION_1, UINT16_C(1100));
        ec_group_test_poll(120U, 0U);
        TEST_ASSERT(ec_group_test_mode() == EC_GROUP_TEST_RUNNING);
        ec_group_test_poll(121U, input_bit);
        TEST_ASSERT(ec_group_test_mode() == EC_GROUP_TEST_IDLE);
        TEST_ASSERT(group_stop_calls == 1U);
    }

    test_directions_and_servo_positions();
    test_partial_start_failures();

    reset_group_fixture();
    start_group(EC_DIRECTION_0, EC_DIRECTION_0, UINT16_C(1100));
    ec_group_test_stop();
    TEST_ASSERT(ec_group_test_mode() == EC_GROUP_TEST_IDLE);
    TEST_ASSERT(!ec_group_test_blocks_single());
}
