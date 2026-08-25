#include "test_support.h"

unsigned int test_failures = 0U;
unsigned int test_cases = 0U;

void test_crc32(void);
void test_dedup(void);
void test_state_machine(void);
void test_protocol(void);
void test_protocol_gateway(void);

int main(void)
{
    test_crc32();
    test_dedup();
    test_state_machine();
    test_protocol();
    test_protocol_gateway();

    if (test_failures != 0U) {
        (void)fprintf(stderr, "%u OF %u STM32 LOGIC TESTS FAILED\n",
                      test_failures, test_cases);
        return 1;
    }

    (void)printf("ALL %u STM32 LOGIC TESTS PASSED\n", test_cases);
    return 0;
}
