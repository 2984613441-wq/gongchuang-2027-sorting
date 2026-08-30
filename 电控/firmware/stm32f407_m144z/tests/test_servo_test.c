#include "ec_inputs.h"
#include "ec_servo_test.h"
#include "test_support.h"

static uint32_t fake_now_ms;
static unsigned start_count;
static unsigned stop_count;
static uint16_t last_pulse_us;
static bool port_start_result;

bool ec_servo_port_start_z(uint16_t pulse_us)
{
    start_count++;
    last_pulse_us = pulse_us;
    return port_start_result;
}

void ec_servo_port_stop_z(void)
{
    stop_count++;
}

uint32_t ec_servo_port_now_ms(void)
{
    return fake_now_ms;
}

static void reset_fixture(void)
{
    fake_now_ms = 100U;
    start_count = 0U;
    stop_count = 0U;
    last_pulse_us = 0U;
    port_start_result = true;
    ec_servo_test_init();
}

static void assert_allowed_pulse(uint16_t pulse_us, uint32_t now_ms)
{
    fake_now_ms = now_ms;
    TEST_ASSERT(ec_servo_test_arm(0U, false));
    TEST_ASSERT(ec_servo_test_start(pulse_us, 0U, false));
    TEST_ASSERT(last_pulse_us == pulse_us);
    TEST_ASSERT(ec_servo_test_active_pulse_us() == pulse_us);
    ec_servo_test_stop();
}

void test_servo_test(void)
{
    reset_fixture();

    TEST_ASSERT(!ec_servo_test_start(1500U, 0U, false));
    TEST_ASSERT(start_count == 0U);

    TEST_ASSERT(!ec_servo_test_arm(EC_INPUT_X_HOME, false));
    TEST_ASSERT(!ec_servo_test_arm(EC_INPUT_ESTOP_FB, false));
    TEST_ASSERT(!ec_servo_test_arm(0U, true));
    TEST_ASSERT(!ec_servo_test_is_armed());

    assert_allowed_pulse(1000U, 200U);
    assert_allowed_pulse(1100U, 300U);
    assert_allowed_pulse(1200U, 400U);
    reset_fixture();

    fake_now_ms = 1000U;
    TEST_ASSERT(ec_servo_test_arm(0U, false));
    TEST_ASSERT(ec_servo_test_is_armed());
    TEST_ASSERT(ec_servo_test_blocks_step());
    fake_now_ms = 11001U;
    TEST_ASSERT(!ec_servo_test_start(1500U, 0U, false));
    TEST_ASSERT(!ec_servo_test_is_armed());

    fake_now_ms = 12000U;
    TEST_ASSERT(ec_servo_test_arm(0U, false));
    TEST_ASSERT(!ec_servo_test_start(1400U, 0U, false));
    TEST_ASSERT(!ec_servo_test_start(1500U, 0U, false));
    TEST_ASSERT(start_count == 0U);

    fake_now_ms = 13000U;
    TEST_ASSERT(ec_servo_test_arm(0U, false));
    TEST_ASSERT(!ec_servo_test_start(1500U, EC_INPUT_Z_DOWN, false));
    TEST_ASSERT(!ec_servo_test_is_armed());

    fake_now_ms = 14000U;
    TEST_ASSERT(ec_servo_test_arm(0U, false));
    TEST_ASSERT(!ec_servo_test_start(1500U, 0U, true));
    TEST_ASSERT(!ec_servo_test_is_armed());

    fake_now_ms = 15000U;
    TEST_ASSERT(ec_servo_test_arm(0U, false));
    TEST_ASSERT(ec_servo_test_start(1300U, 0U, false));
    TEST_ASSERT(start_count == 1U);
    TEST_ASSERT(last_pulse_us == 1300U);
    TEST_ASSERT(ec_servo_test_is_running());
    TEST_ASSERT(ec_servo_test_active_pulse_us() == 1300U);
    TEST_ASSERT(!ec_servo_test_start(1700U, 0U, false));
    TEST_ASSERT(start_count == 1U);

    fake_now_ms = 16000U;
    TEST_ASSERT(ec_servo_test_arm(0U, false));
    TEST_ASSERT(ec_servo_test_start(1500U, 0U, false));
    ec_servo_test_poll(17999U, 0U);
    TEST_ASSERT(ec_servo_test_is_running());
    ec_servo_test_poll(18000U, 0U);
    TEST_ASSERT(!ec_servo_test_is_running());

    fake_now_ms = 19000U;
    TEST_ASSERT(ec_servo_test_arm(0U, false));
    TEST_ASSERT(ec_servo_test_start(1700U, 0U, false));
    ec_servo_test_poll(19001U, EC_INPUT_Y_END);
    TEST_ASSERT(!ec_servo_test_is_running());

    fake_now_ms = 20000U;
    TEST_ASSERT(ec_servo_test_arm(0U, false));
    TEST_ASSERT(ec_servo_test_start(1900U, 0U, false));
    TEST_ASSERT(last_pulse_us == 1900U);
    ec_servo_test_stop();
    TEST_ASSERT(!ec_servo_test_is_running());

    fake_now_ms = 21000U;
    TEST_ASSERT(ec_servo_test_arm(0U, false));
    TEST_ASSERT(ec_servo_test_start(1500U, 0U, false));
    ec_servo_test_stop();
    TEST_ASSERT(ec_servo_test_mode() == EC_SERVO_TEST_IDLE);
    TEST_ASSERT(ec_servo_test_active_pulse_us() == 0U);
    TEST_ASSERT(stop_count >= 1U);

    fake_now_ms = 21000U;
    TEST_ASSERT(ec_servo_test_arm(0U, false));
    fake_now_ms = 31000U;
    TEST_ASSERT(ec_servo_test_start(1500U, 0U, false));
    TEST_ASSERT(ec_servo_test_is_running());
    ec_servo_test_stop();
}
