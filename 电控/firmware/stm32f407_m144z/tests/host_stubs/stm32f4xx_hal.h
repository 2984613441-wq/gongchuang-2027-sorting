#ifndef EC_FIRMWARE_HOST_STUBS_STM32F4XX_HAL_H
#define EC_FIRMWARE_HOST_STUBS_STM32F4XX_HAL_H

/* Minimal host-side stub of the STM32 HAL header (tests/host_stubs).
 *
 * Only the declarations the host-test target actually needs from the
 * production sources it compiles. Of those, only App/Src/ec_app.c includes
 * this header, and it uses just HAL_GetTick(). All other HAL usage lives in
 * App/Src/ec_board_stm32.c and Core/, which are NOT part of the host tests
 * (their port layer is replaced by the per-suite test doubles).
 *
 * Add further macros/declarations here only if a host-target production
 * source starts referencing them; do NOT mirror the full HAL.
 */

#include <stdint.h>

uint32_t HAL_GetTick(void);

#endif /* EC_FIRMWARE_HOST_STUBS_STM32F4XX_HAL_H */
