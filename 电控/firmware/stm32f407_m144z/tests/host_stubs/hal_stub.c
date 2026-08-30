/* Host-side HAL_GetTick double for the firmware host-test target.
 *
 * The app tests drive time through ec_app_poll()/the board doubles, so a
 * fixed 0 tick keeps every time-based rule deterministic: the 15 s task
 * deadline starts at 0 and never expires within a test, and the startup
 * sequence (POST/HOMING/BARRIER) timeouts are measured from 0.
 */

#include "stm32f4xx_hal.h"

uint32_t HAL_GetTick(void)
{
    return 0U;
}
