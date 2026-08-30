/* Host-side HAL_GetTick double for the firmware host-test target.
 *
 * The default tick is 0, which keeps every existing time-based rule
 * deterministic (the startup sequence's POST/HOMING/BARRIER timeouts are all
 * measured from 0). The rolling no-motion watchdog tests advance time with
 * test_set_tick() before motion start and before each progress-token call,
 * and pass matching now_ms values to ec_app_poll().
 */

#include "stm32f4xx_hal.h"

static uint32_t fake_hal_tick;

void test_set_tick(uint32_t tick)
{
    fake_hal_tick = tick;
}

uint32_t HAL_GetTick(void)
{
    return fake_hal_tick;
}
