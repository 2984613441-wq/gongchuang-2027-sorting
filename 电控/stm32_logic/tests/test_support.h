#ifndef TEST_SUPPORT_H
#define TEST_SUPPORT_H

#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

extern unsigned int test_failures;
extern unsigned int test_cases;

#define TEST_CASE_BEGIN(id)                                                     \
    do {                                                                        \
        ++test_cases;                                                           \
        (void)printf("RUN %s\n", (id));                                         \
    } while (0)

#define EXPECT_EQ_U32(expected, actual)                                         \
    do {                                                                        \
        const uint32_t test_expected_ = (uint32_t)(expected);                   \
        const uint32_t test_actual_ = (uint32_t)(actual);                       \
        if (test_expected_ != test_actual_) {                                   \
            ++test_failures;                                                    \
            (void)fprintf(stderr,                                               \
                          "%s:%d expected 0x%08" PRIX32                        \
                          ", actual 0x%08" PRIX32 "\n",                        \
                          __FILE__, __LINE__, test_expected_, test_actual_);     \
        }                                                                       \
    } while (0)

#define EXPECT_EQ_U8(expected, actual)                                          \
    EXPECT_EQ_U32((uint8_t)(expected), (uint8_t)(actual))

#define EXPECT_TRUE(actual)                                                     \
    EXPECT_EQ_U32(1U, (actual) ? 1U : 0U)

#define EXPECT_FALSE(actual)                                                    \
    EXPECT_EQ_U32(0U, (actual) ? 1U : 0U)

#endif
