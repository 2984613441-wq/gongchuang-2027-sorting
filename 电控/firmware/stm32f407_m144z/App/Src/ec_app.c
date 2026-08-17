#include "ec_app.h"

#include "ec_board.h"
#include "ec_diag.h"
#include "ec_safety_adapter.h"
#include "ec_step_test.h"

#ifndef EC_DIAGNOSTIC_BUILD
#define EC_DIAGNOSTIC_BUILD 0
#endif

#define EC_INPUT_SAMPLE_PERIOD_MS UINT32_C(10)

static ec_dedup_entry_t diagnostic_dedup_storage[1];
static ec_dedup_t diagnostic_dedup;
static ec_state_machine_t machine;
static uint32_t last_input_sample_ms;

void ec_app_init(void)
{
    ec_board_enter_safe_state();
    ec_dedup_init(&diagnostic_dedup, diagnostic_dedup_storage, 1U);
    ec_sm_init(&machine, &diagnostic_dedup);
    ec_safety_apply(machine.actions);

    ec_step_test_init();
    ec_diag_init();
    last_input_sample_ms = 0U;
    ec_board_poll_inputs(0U);
    ec_board_uart_start_rx();

#if EC_DIAGNOSTIC_BUILD
    ec_diag_port_write("BOOT SAFE HSI=16000000 SAFE_LOCK=1 ENABLES=DISABLED\r\n");
#endif
}

void ec_app_poll(uint32_t now_ms)
{
    if ((uint32_t)(now_ms - last_input_sample_ms) >=
        EC_INPUT_SAMPLE_PERIOD_MS) {
        last_input_sample_ms = now_ms;
        ec_board_poll_inputs(now_ms);
    }

    ec_step_test_poll(now_ms);
    ec_diag_poll();
    ec_diag_tick(now_ms);
}

void ec_app_on_uart_rx_byte(uint8_t byte)
{
    ec_diag_on_rx_byte(byte);
}

ec_state_t ec_app_state(void)
{
    return machine.state;
}
