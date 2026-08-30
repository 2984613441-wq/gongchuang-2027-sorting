#ifndef EC_APP_H
#define EC_APP_H

#include "ec_state_machine.h"

#include <stdbool.h>
#include <stdint.h>

/* Progress-source adapter switch (docs/design/2026-08-30-motion-time-budget.md
 * §3.3.2): the firmware must NOT treat program-step completion counts as
 * observable motion feedback - a stalled axis still advances its pulse
 * counter, so only bench-validated progress may extend the rolling no-motion
 * watchdog window. Production keeps this 0 (fail-closed): with the source not
 * compiled in, ec_app_note_observable_progress() is a hard no-op and the
 * runtime adapter switch is locked off. A bench-validated source is enabled
 * by recompiling with this macro set to 1 (and then, at runtime, via
 * ec_app_progress_source_set_enabled(), which boots OFF). */
#ifndef EC_APP_PROGRESS_SOURCE_ENABLED
#define EC_APP_PROGRESS_SOURCE_ENABLED 0U
#endif

void ec_app_init(void);
void ec_app_poll(uint32_t now_ms);
void ec_app_on_uart_rx_byte(uint8_t byte);
ec_state_t ec_app_state(void);

/* Rolling no-motion watchdog (design §3.3): feed a bench-validated observable
 * progress token to re-base the 15 s window. No-op while the progress source
 * is disabled (the production default). Duplicate or stale tokens never
 * re-extend; tokens delivered outside an open window are ignored. */
void ec_app_note_observable_progress(uint32_t token);

/* Runtime progress-source adapter switch. When
 * EC_APP_PROGRESS_SOURCE_ENABLED is 0 this is a locked no-op (fail-closed);
 * when 1, it toggles the source that ec_app_note_observable_progress() feeds
 * on. Always boots OFF. */
void ec_app_progress_source_set_enabled(bool enabled);

/* Host-test seam (compiled out of production builds - the Keil target never
 * defines EC_APP_TEST_HOOKS). The app boot chain cannot reach WAIT_TASK on
 * the host because no barrier-feedback input is mapped; the test target uses
 * ec_app_test_force_barrier_verified() to stand in for the startup
 * sequence's BARRIER_AVOIDANCE_VERIFIED, and the two read-only probes to
 * assert the watchdog state exactly. */
#ifndef EC_APP_TEST_HOOKS
#define EC_APP_TEST_HOOKS 0
#endif
#if EC_APP_TEST_HOOKS
void ec_app_test_force_barrier_verified(void);
bool ec_app_test_watchdog_active(void);
uint32_t ec_app_test_last_observable_ms(void);
#endif

#endif
