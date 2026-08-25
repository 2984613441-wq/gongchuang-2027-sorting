#include "test_support.h"
int main(void) { test_inputs(); test_step_test(); test_servo_test(); test_group_test(); test_barrier_test(); test_diag(); test_safety_adapter(); test_app(); test_protocol(); puts("ALL FIRMWARE HOST TESTS PASSED"); return EXIT_SUCCESS; }
