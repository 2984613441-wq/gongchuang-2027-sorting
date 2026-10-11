#ifndef EC_CONFIG_HANDLER_H
#define EC_CONFIG_HANDLER_H

/* Runtime configuration handler for field parameter adjustment.
 *
 * Allows tuning motion parameters (speed multipliers, acceleration) via UART
 * commands from Raspberry Pi without recompiling firmware. Parameters are
 * volatile (not persisted to EEPROM) to prevent field misconfiguration.
 *
 * Safety constraints:
 * - Only accepts updates when system is in IDLE state
 * - Validates all parameter ranges before applying
 * - Enforces max_speed_limit as hard ceiling
 *
 * Usage:
 *   1. Call config_handler_init() during system initialization
 *   2. When CONFIG_UPDATE frame (0x20) is received:
 *      config_handler_process_update(payload, len)
 *   3. Use config_apply_speed_limit() when setting motor speeds:
 *      uint32_t actual_speed = config_apply_speed_limit(
 *          EC_AXIS_MOVE_FREQUENCY_HZ,
 *          config_get_x_speed_multiplier()
 *      );
 */

#include <stdbool.h>
#include <stdint.h>

/* Initialize config handler with default parameters (1.0x multipliers). */
void config_handler_init(void);

/* Process a CONFIG_UPDATE command payload.
 *
 * Payload format (10 bytes, big-endian):
 *   x_speed_multiplier(2B, 0-2000 representing 0.0-2.0)
 *   y_speed_multiplier(2B)
 *   accel_factor(2B)
 *   max_speed_limit(4B, Hz)
 *
 * Sends ACK (0x21) on success or NACK (0x22) with error code on failure.
 * Error codes:
 *   0x01 - Invalid payload size
 *   0x10 - System not in IDLE state
 *   0x11 - Parameter out of valid range
 */
void config_handler_process_update(const uint8_t *payload, uint16_t len);

/* Get current X-axis speed multiplier (0.5 - 2.0, default 1.0). */
float config_get_x_speed_multiplier(void);

/* Get current Y-axis speed multiplier (0.5 - 2.0, default 1.0). */
float config_get_y_speed_multiplier(void);

/* Get current acceleration factor (0.5 - 2.0, default 1.0). */
float config_get_accel_factor(void);

/* Get current maximum speed limit in Hz (hard ceiling, default 5000). */
uint32_t config_get_max_speed_limit(void);

/* Apply speed multiplier and enforce max limit.
 *
 * Example:
 *   uint32_t x_freq = config_apply_speed_limit(
 *       EC_AXIS_MOVE_FREQUENCY_HZ,
 *       config_get_x_speed_multiplier()
 *   );
 *
 * Returns: min(requested_speed * multiplier, max_speed_limit)
 */
uint32_t config_apply_speed_limit(uint32_t requested_speed, float multiplier);

#endif
