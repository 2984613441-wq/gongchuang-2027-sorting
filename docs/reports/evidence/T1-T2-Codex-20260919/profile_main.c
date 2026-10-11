#include <stdio.h>
unsigned int test_failures, test_cases;
void test_step_profile(void);
int main(void) {
    test_step_profile();
    printf("PROFILE cases=%u failures=%u\n",test_cases,test_failures);
    return test_failures ? 1 : 0;
}
