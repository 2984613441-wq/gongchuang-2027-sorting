#include "ec_app.h"
#include "test_support.h"

static unsigned safe_state_calls;
static unsigned input_poll_calls;
static unsigned uart_start_calls;

void ec_board_enter_safe_state(void) { safe_state_calls++; }
void ec_board_poll_inputs(uint32_t now_ms) { (void)now_ms; input_poll_calls++; }
void ec_board_uart_start_rx(void) { uart_start_calls++; }

void test_app(void)
{
    safe_state_calls = input_poll_calls = uart_start_calls = 0U;
    ec_app_init();
    TEST_ASSERT(safe_state_calls == 1U);
    TEST_ASSERT(uart_start_calls == 1U);
    TEST_ASSERT(input_poll_calls == 1U);
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);

    ec_app_poll(9U);
    TEST_ASSERT(input_poll_calls == 1U);
    ec_app_poll(10U);
    TEST_ASSERT(input_poll_calls == 2U);
    ec_app_poll(19U);
    TEST_ASSERT(input_poll_calls == 2U);
    ec_app_poll(20U);
    TEST_ASSERT(input_poll_calls == 3U);
}
