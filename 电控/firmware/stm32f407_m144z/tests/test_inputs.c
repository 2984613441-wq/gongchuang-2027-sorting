#include "ec_inputs.h"
#include "test_support.h"
void test_inputs(void) {
  ec_input_filter_t filter;
  ec_inputs_init(&filter, EC_INPUT_ALL_MASK, 0U);
  TEST_ASSERT(ec_inputs_stable_mask(&filter) == EC_INPUT_ALL_MASK);
  ec_inputs_update(&filter, EC_INPUT_ALL_MASK & ~EC_INPUT_X_HOME, 10U);
  TEST_ASSERT(ec_inputs_stable_mask(&filter) == EC_INPUT_ALL_MASK);
  ec_inputs_update(&filter, EC_INPUT_ALL_MASK & ~EC_INPUT_X_HOME, 29U);
  TEST_ASSERT(ec_inputs_stable_mask(&filter) == EC_INPUT_ALL_MASK);
  ec_inputs_update(&filter, EC_INPUT_ALL_MASK & ~EC_INPUT_X_HOME, 30U);
  TEST_ASSERT(ec_inputs_stable_mask(&filter) == (EC_INPUT_ALL_MASK & ~EC_INPUT_X_HOME));
  TEST_ASSERT(ec_inputs_active_mask(&filter) == EC_INPUT_X_HOME);

  ec_inputs_init(&filter, EC_INPUT_ALL_MASK, 0U);
  ec_inputs_update(&filter, EC_INPUT_ALL_MASK & ~EC_INPUT_X_HOME, 10U);
  ec_inputs_update(&filter,
                   EC_INPUT_ALL_MASK & ~EC_INPUT_X_HOME & ~EC_INPUT_Y_HOME,
                   20U);
  ec_inputs_update(&filter,
                   EC_INPUT_ALL_MASK & ~EC_INPUT_X_HOME & ~EC_INPUT_Y_END,
                   30U);
  TEST_ASSERT((ec_inputs_active_mask(&filter) & EC_INPUT_X_HOME) != 0U);
  TEST_ASSERT((ec_inputs_active_mask(&filter) & EC_INPUT_Y_HOME) == 0U);
  TEST_ASSERT((ec_inputs_active_mask(&filter) & EC_INPUT_Y_END) == 0U);
}
