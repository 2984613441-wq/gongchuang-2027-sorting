#ifndef EC_DEMO_H
#define EC_DEMO_H

#include <stdbool.h>
#include <stdint.h>

/* Continuous XYZ demo loop for the "mechanical fault" demonstration. Runs an
 * endless sequence of counted X/Y moves and Z-lift servo pulses directly on
 * the port layer (ec_step_port_* / ec_servo_port_*), independent of the
 * diagnostic ec_step_test / ec_servo_test / ec_group_test machinery. The
 * caller (ec_diag) gates the diagnostic command set while the demo is active
 * and starts/stops the demo; this module only owns the loop itself.
 *
 * NOTE: move frequency / leg distance are PLACEHOLDERS, tuned for a
 * clearly-visible demo (800 Hz, 40 mm legs). Servo pulse widths use the
 * measured values 1100 us (open/lower) and 1900 us (close/raise). */

void ec_demo_init(void);
/* Begin the loop. Returns false (and stays inactive) if already active or if
 * any safety input is triggered. The caller is expected to have stopped the
 * diagnostic test state machines first. */
bool ec_demo_start(uint16_t active_inputs);
void ec_demo_stop(void);
void ec_demo_poll(uint32_t now_ms, uint16_t active_inputs);
bool ec_demo_is_active(void);

#endif
