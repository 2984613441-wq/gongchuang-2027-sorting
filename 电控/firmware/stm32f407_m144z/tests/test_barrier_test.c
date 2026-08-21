#include "ec_barrier_test.h"
#include "ec_inputs.h"
#include "test_support.h"

static uint32_t fake_barrier_now_ms;
static unsigned barrier_start_calls;
static unsigned barrier_stop_calls;
static uint8_t recorded_mask;
static uint16_t recorded_pulse_us;
static bool port_start_result;

bool ec_barrier_port_start_mask(uint8_t channel_mask, uint16_t pulse_us)
{
    barrier_start_calls++;
    recorded_mask = channel_mask;
    recorded_pulse_us = pulse_us;
    return port_start_result;
}

void ec_barrier_port_stop(void)
{
    barrier_stop_calls++;
}

uint32_t ec_barrier_port_now_ms(void)
{
    return fake_barrier_now_ms;
}

static void reset_barrier_fixture(void)
{
    fake_barrier_now_ms = 100U;
    barrier_start_calls = 0U;
    barrier_stop_calls = 0U;
    recorded_mask = 0U;
    recorded_pulse_us = 0U;
    port_start_result = true;
    ec_barrier_test_init();
}

static void start_barrier(uint8_t mask, uint16_t pulse_us)
{
    TEST_ASSERT(ec_barrier_test_arm(0U, false));
    TEST_ASSERT(ec_barrier_test_start(mask, pulse_us, 0U, false));
}

void test_barrier_test(void)
{
    uint16_t input_bit;

    reset_barrier_fixture();
    ec_barrier_test_stop();
    TEST_ASSERT(barrier_stop_calls == 0U);

    TEST_ASSERT(!ec_barrier_test_arm(EC_INPUT_ESTOP_FB, false));
    TEST_ASSERT(!ec_barrier_test_arm(0U, true));
    TEST_ASSERT(ec_barrier_test_arm(0U, false));
    TEST_ASSERT(ec_barrier_test_is_armed());
    TEST_ASSERT(!ec_barrier_test_arm(0U, false));
    ec_barrier_test_stop();
    TEST_ASSERT(barrier_stop_calls == 0U);

    reset_barrier_fixture();
    TEST_ASSERT(!ec_barrier_test_start(UINT8_C(0x0F), 1000U, 0U, false));
    TEST_ASSERT(barrier_start_calls == 0U);

    reset_barrier_fixture();
    TEST_ASSERT(ec_barrier_test_arm(0U, false));
    TEST_ASSERT(!ec_barrier_test_start(0U, 1000U, 0U, false));
    TEST_ASSERT(!ec_barrier_test_start(UINT8_C(0x10), 1000U, 0U, false));
    TEST_ASSERT(!ec_barrier_test_start(UINT8_C(0x0F), 400U, 0U, false));
    TEST_ASSERT(!ec_barrier_test_start(UINT8_C(0x0F), 2600U, 0U, false));
    TEST_ASSERT(!ec_barrier_test_start(UINT8_C(0x0F), 1000U,
                                       EC_INPUT_X_END, false));
    TEST_ASSERT(!ec_barrier_test_start(UINT8_C(0x0F), 1000U, 0U, true));
    TEST_ASSERT(barrier_start_calls == 0U);
    TEST_ASSERT(!ec_barrier_test_is_armed());

    reset_barrier_fixture();
    start_barrier(UINT8_C(0x0F), 1500U);
    TEST_ASSERT(ec_barrier_test_is_active());
    TEST_ASSERT(ec_barrier_test_blocks_other());
    TEST_ASSERT(recorded_mask == UINT8_C(0x0F));
    TEST_ASSERT(recorded_pulse_us == 1500U);
    TEST_ASSERT(ec_barrier_test_active_mask() == UINT8_C(0x0F));
    TEST_ASSERT(ec_barrier_test_pulse_us() == 1500U);
    TEST_ASSERT(!ec_barrier_test_start(UINT8_C(0x01), 1000U, 0U, false));
    ec_barrier_test_poll(1199U, 0U);
    TEST_ASSERT(ec_barrier_test_is_active());
    ec_barrier_test_poll(3100U, 0U);
    TEST_ASSERT(!ec_barrier_test_is_active());
    TEST_ASSERT(barrier_stop_calls >= 1U);

    reset_barrier_fixture();
    start_barrier(UINT8_C(0x01), 1000U);
    TEST_ASSERT(recorded_mask == UINT8_C(0x01));
    ec_barrier_test_poll(101U, EC_INPUT_START);
    TEST_ASSERT(!ec_barrier_test_is_active());
    TEST_ASSERT(barrier_stop_calls >= 1U);

    reset_barrier_fixture();
    fake_barrier_now_ms = 1000U;
    TEST_ASSERT(ec_barrier_test_arm(0U, false));
    fake_barrier_now_ms = 11001U;
    TEST_ASSERT(!ec_barrier_test_start(UINT8_C(0x02), 1200U, 0U, false));
    TEST_ASSERT(!ec_barrier_test_is_armed());

    reset_barrier_fixture();
    port_start_result = false;
    TEST_ASSERT(ec_barrier_test_arm(0U, false));
    TEST_ASSERT(!ec_barrier_test_start(UINT8_C(0x04), 1300U, 0U, false));
    TEST_ASSERT(!ec_barrier_test_is_active());
    TEST_ASSERT(barrier_stop_calls >= 1U);

    reset_barrier_fixture();
    start_barrier(UINT8_C(0x08), 1900U);
    ec_barrier_test_stop();
    TEST_ASSERT(!ec_barrier_test_is_active());
    TEST_ASSERT(barrier_stop_calls >= 1U);

    for (input_bit = UINT16_C(1); input_bit <= EC_INPUT_MANUAL_RESET;
         input_bit = (uint16_t)(input_bit << 1U)) {
        reset_barrier_fixture();
        TEST_ASSERT(ec_barrier_test_arm(0U, false));
        ec_barrier_test_poll(101U, input_bit);
        TEST_ASSERT(!ec_barrier_test_is_armed());
        TEST_ASSERT(barrier_stop_calls == 0U);

        reset_barrier_fixture();
        start_barrier(UINT8_C(0x03), 1000U);
        ec_barrier_test_poll(101U, input_bit);
        TEST_ASSERT(!ec_barrier_test_is_active());
        TEST_ASSERT(barrier_stop_calls >= 1U);
    }
}
