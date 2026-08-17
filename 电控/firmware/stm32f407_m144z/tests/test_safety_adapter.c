#include "ec_safety_adapter.h"
#include "ec_state_machine.h"
#include "test_support.h"
static unsigned safe_stop_calls, safe_disable_calls, safe_inhibit_calls;
void ec_safety_port_stop_all(void) { safe_stop_calls++; }
void ec_safety_port_disable_drivers(void) { safe_disable_calls++; }
void ec_safety_port_inhibit_power(void) { safe_inhibit_calls++; }
void test_safety_adapter(void) {
  ec_dedup_entry_t storage[2]; ec_dedup_t dedup; ec_state_machine_t machine;
  safe_stop_calls = safe_disable_calls = safe_inhibit_calls = 0U;
  ec_dedup_init(&dedup, storage, 2U); ec_sm_init(&machine, &dedup); ec_safety_apply(machine.actions);
  TEST_ASSERT(machine.actions == EC_ACTION_SAFE_LOCK); TEST_ASSERT(safe_stop_calls == 1U); TEST_ASSERT(safe_disable_calls == 1U); TEST_ASSERT(safe_inhibit_calls == 1U);
}
