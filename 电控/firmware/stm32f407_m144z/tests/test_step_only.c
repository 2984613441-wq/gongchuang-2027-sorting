#include "test_support.h"
extern void test_step_test(void);
int main(void) {
    test_step_test();
    printf("test_step_test PASSED\n");
    return 0;
}
