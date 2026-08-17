#ifndef EC_FIRMWARE_TEST_SUPPORT_H
#define EC_FIRMWARE_TEST_SUPPORT_H
#include <stdio.h>
#include <stdlib.h>
#define TEST_ASSERT(condition) do { if (!(condition)) { fprintf(stderr, "%s:%d assertion failed: %s\n", __FILE__, __LINE__, #condition); exit(EXIT_FAILURE); } } while (0)
void test_inputs(void);
void test_step_test(void);
void test_diag(void);
void test_safety_adapter(void);
void test_app(void);
#endif
