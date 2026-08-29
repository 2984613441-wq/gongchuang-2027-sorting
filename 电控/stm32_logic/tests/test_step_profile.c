#include "ec_step_profile.h"
#include "test_support.h"

#include <math.h>

/* Float reference for one step's frequency, mirroring the integer model:
 *   accel  f = sqrt(start^2 + 2*a*i)
 *   cruise f = cruise_hz
 *   decel  f = sqrt(end^2   + 2*d*steps_from_end)   (anchored to end_hz)  */
static uint32_t ref_frequency(const ec_step_profile_t *p, uint32_t i)
{
    double f;

    if (i < p->accel_steps) {
        f = sqrt((double)p->start_hz * (double)p->start_hz +
                 2.0 * (double)p->accel_hz_per_s * (double)i);
    } else if (i < (p->accel_steps + p->cruise_steps)) {
        f = (double)p->cruise_hz;
    } else {
        const uint32_t from_end = p->total_steps - 1U - i;
        f = sqrt((double)p->end_hz * (double)p->end_hz +
                 2.0 * (double)p->decel_hz_per_s * (double)from_end);
    }
    return (uint32_t)llround(f);
}

/* The integer sqrt may differ from the double reference by at most 1 in the
 * presence of rounding; accept that slack. */
static void expect_freq_near(const ec_step_profile_t *p, uint32_t i)
{
    const uint32_t actual = ec_step_profile_frequency_at(p, i);
    const uint32_t ref = ref_frequency(p, i);
    const int64_t diff = (int64_t)actual - (int64_t)ref;

    if ((diff < -1) || (diff > 1)) {
        ++test_failures;
        (void)fprintf(stderr,
                      "%s:%d step %u expected ~%" PRIu32 ", actual %" PRIu32
                      "\n",
                      __FILE__, __LINE__, i, ref, actual);
    }
}

/* Float reference for the timer reload of one step. */
static uint32_t ref_reload(const ec_step_profile_t *p, uint32_t i,
                           uint32_t timer_hz)
{
    const uint32_t f = ref_frequency(p, i);
    const uint32_t rounded = (uint32_t)llround((double)timer_hz / (double)f);

    if (rounded == 0U) {
        return 0U;
    }
    return rounded - 1U;
}

/* The integer round may differ from the double reference by at most 1 tick. */
static void expect_reload_near(const ec_step_profile_t *p, uint32_t i,
                               uint32_t timer_hz)
{
    const uint32_t actual = ec_step_profile_reload_at(p, i, timer_hz);
    const uint32_t ref = ref_reload(p, i, timer_hz);
    const int64_t diff = (int64_t)actual - (int64_t)ref;

    if ((diff < -1) || (diff > 1)) {
        ++test_failures;
        (void)fprintf(stderr,
                      "%s:%d step %u reload expected ~%" PRIu32
                      ", actual %" PRIu32 "\n",
                      __FILE__, __LINE__, i, ref, actual);
    }
}

static void expect_profile_consistent(const ec_step_profile_t *p)
{
    EXPECT_EQ_U32(p->total_steps,
                  p->accel_steps + p->cruise_steps + p->decel_steps);
}

void test_step_profile(void)
{
    ec_step_profile_t p;

    TEST_CASE_BEGIN("C-STEP-001");
    /* Full trapezoid: plenty of room for accel + cruise + decel. */
    EXPECT_TRUE(ec_step_profile_plan(&p, 1000U, 100U, 1000U, 200U,
                                     5000U, 8000U));
    EXPECT_EQ_U32(1000U, p.total_steps);
    EXPECT_EQ_U32(99U, p.accel_steps);
    EXPECT_EQ_U32(841U, p.cruise_steps);
    EXPECT_EQ_U32(60U, p.decel_steps);
    EXPECT_EQ_U32(1000U, p.cruise_hz);
    expect_profile_consistent(&p);
    EXPECT_EQ_U32(100U, ec_step_profile_frequency_at(&p, 0U));
    EXPECT_EQ_U32(1000U, ec_step_profile_frequency_at(&p, 99U));
    EXPECT_EQ_U32(1000U, ec_step_profile_frequency_at(&p, 939U));
    EXPECT_EQ_U32(200U, ec_step_profile_frequency_at(&p, 999U));

    TEST_CASE_BEGIN("C-STEP-002");
    /* Every step across the trapezoid agrees with the float reference. */
    {
        uint32_t i;
        for (i = 0U; i < 1000U; ++i) {
            expect_freq_near(&p, i);
        }
    }

    TEST_CASE_BEGIN("C-STEP-003");
    /* Triangle case: too short to reach 1000 Hz, peak is lowered. */
    EXPECT_TRUE(ec_step_profile_plan(&p, 50U, 100U, 1000U, 100U,
                                     1000U, 1000U));
    EXPECT_EQ_U32(50U, p.total_steps);
    EXPECT_EQ_U32(244U, p.cruise_hz);
    expect_profile_consistent(&p);
    {
        uint32_t i;
        for (i = 0U; i < 50U; ++i) {
            expect_freq_near(&p, i);
        }
    }

    TEST_CASE_BEGIN("C-STEP-004");
    /* Single step at constant frequency: no room to accelerate. */
    EXPECT_TRUE(ec_step_profile_plan(&p, 1U, 100U, 100U, 100U, 1000U, 1000U));
    EXPECT_EQ_U32(1U, p.total_steps);
    EXPECT_EQ_U32(0U, p.accel_steps);
    EXPECT_EQ_U32(1U, p.cruise_steps);
    EXPECT_EQ_U32(0U, p.decel_steps);
    EXPECT_EQ_U32(100U, p.cruise_hz);
    EXPECT_EQ_U32(100U, ec_step_profile_frequency_at(&p, 0U));
    EXPECT_EQ_U32(0U, ec_step_profile_frequency_at(&p, 1U));

    TEST_CASE_BEGIN("C-STEP-005");
    /* Large cruise (100 kHz) must not overflow the uint32 squares. */
    EXPECT_TRUE(ec_step_profile_plan(&p, 1000000U, 10U, 100000U, 10U,
                                     100000U, 100000U));
    EXPECT_EQ_U32(1000000U, p.total_steps);
    EXPECT_EQ_U32(100000U, p.cruise_hz);
    expect_profile_consistent(&p);
    EXPECT_EQ_U32(10U, ec_step_profile_frequency_at(&p, 0U));
    EXPECT_EQ_U32(10U, ec_step_profile_frequency_at(&p, 999999U));

    TEST_CASE_BEGIN("C-STEP-006");
    /* Degenerate: endpoints differ by more than the move can span (start > end).
     * Defensive path only - assert structure, not per-step frequency. */
    EXPECT_TRUE(ec_step_profile_plan(&p, 3U, 100U, 1000U, 1U, 1000U, 1000U));
    EXPECT_EQ_U32(3U, p.total_steps);
    EXPECT_EQ_U32(100U, p.cruise_hz);
    expect_profile_consistent(&p);

    TEST_CASE_BEGIN("C-STEP-007");
    /* Invalid parameters are rejected and leave the struct untouched. */
    {
        ec_step_profile_t sentinel = {0U, 0U, 0U, 0U, 0U, 0U, 0U, 0U, 0U};
        p = sentinel;
        EXPECT_FALSE(ec_step_profile_plan(NULL, 100U, 100U, 1000U, 100U,
                                          1000U, 1000U));
        EXPECT_FALSE(ec_step_profile_plan(&p, 0U, 100U, 1000U, 100U,
                                          1000U, 1000U));
        EXPECT_FALSE(ec_step_profile_plan(&p, 100U, 0U, 1000U, 100U,
                                          1000U, 1000U));
        EXPECT_FALSE(ec_step_profile_plan(&p, 100U, 100U, 99U, 100U,
                                          1000U, 1000U));
        EXPECT_FALSE(ec_step_profile_plan(&p, 100U, 100U, 1000U, 0U,
                                          1000U, 1000U));
        EXPECT_FALSE(ec_step_profile_plan(&p, 100U, 100U, 1000U, 1001U,
                                          1000U, 1000U));
        EXPECT_FALSE(ec_step_profile_plan(&p, 100U, 100U, 1000U, 100U,
                                          0U, 1000U));
        EXPECT_FALSE(ec_step_profile_plan(&p, 100U, 100U, 1000U, 100U,
                                          1000U, 0U));
        /* Struct was never written on any of the failures above. */
        EXPECT_EQ_U32(sentinel.total_steps, p.total_steps);
        EXPECT_EQ_U32(sentinel.accel_steps, p.accel_steps);
        EXPECT_EQ_U32(sentinel.cruise_steps, p.cruise_steps);
        EXPECT_EQ_U32(sentinel.decel_steps, p.decel_steps);
        EXPECT_EQ_U32(sentinel.start_hz, p.start_hz);
        EXPECT_EQ_U32(sentinel.cruise_hz, p.cruise_hz);
        EXPECT_EQ_U32(sentinel.end_hz, p.end_hz);
        EXPECT_EQ_U32(sentinel.accel_hz_per_s, p.accel_hz_per_s);
        EXPECT_EQ_U32(sentinel.decel_hz_per_s, p.decel_hz_per_s);
    }

    TEST_CASE_BEGIN("C-STEP-008");
    /* Out-of-range frequency lookups return 0. */
    EXPECT_TRUE(ec_step_profile_plan(&p, 100U, 100U, 1000U, 100U,
                                     1000U, 1000U));
    EXPECT_EQ_U32(0U, ec_step_profile_frequency_at(NULL, 0U));
    EXPECT_EQ_U32(0U, ec_step_profile_frequency_at(&p, 100U));
    EXPECT_TRUE(ec_step_profile_frequency_at(&p, 99U) != 0U);

    TEST_CASE_BEGIN("C-STEP-009");
    /* Timer reload at exactly-divisible frequencies (timer_hz = 100000). */
    EXPECT_TRUE(ec_step_profile_plan(&p, 1000U, 100U, 1000U, 200U,
                                     5000U, 8000U));
    EXPECT_EQ_U32(999U, ec_step_profile_reload_at(&p, 0U, 100000U));   /* 100 Hz */
    EXPECT_EQ_U32(99U, ec_step_profile_reload_at(&p, 99U, 100000U));   /* 1000 Hz */
    EXPECT_EQ_U32(99U, ec_step_profile_reload_at(&p, 939U, 100000U));  /* cruise */
    EXPECT_EQ_U32(499U, ec_step_profile_reload_at(&p, 999U, 100000U)); /* 200 Hz */

    TEST_CASE_BEGIN("C-STEP-010");
    /* Every step's reload agrees with the float reference (non-divisible). */
    {
        uint32_t i;
        for (i = 0U; i < 1000U; ++i) {
            expect_reload_near(&p, i, 100000U);
        }
    }

    TEST_CASE_BEGIN("C-STEP-011");
    /* Boundary clamps: frequency >= timer_hz, out-of-range, NULL, timer_hz 0. */
    EXPECT_TRUE(ec_step_profile_plan(&p, 100U, 1000U, 1000U, 1000U,
                                     1000U, 1000U));
    EXPECT_EQ_U32(0U, ec_step_profile_reload_at(&p, 0U, 500U));      /* 1000 Hz > 500 */
    EXPECT_EQ_U32(0U, ec_step_profile_reload_at(&p, 100U, 100000U)); /* out of range */
    EXPECT_EQ_U32(0U, ec_step_profile_reload_at(NULL, 0U, 100000U)); /* NULL */
    EXPECT_EQ_U32(0U, ec_step_profile_reload_at(&p, 0U, 0U));        /* timer_hz 0 */

    TEST_CASE_BEGIN("C-STEP-012");
    /* P2-1: peak-formula overflow guard. Absurd accel rates (near UINT32_MAX)
     * must be rejected instead of silently wrapping to a wrong peak, and a
     * rejected plan must leave the struct untouched. */
    {
        ec_step_profile_t sentinel = {0U, 0U, 0U, 0U, 0U, 0U, 0U, 0U, 0U};
        p = sentinel;
        EXPECT_FALSE(ec_step_profile_plan(&p, 1000U, 100U, 4000000U, 100U,
                                          4294000000U, 4294000000U));
        EXPECT_FALSE(ec_step_profile_plan(&p, 1000U, 100U, 4000000U, 100U,
                                          UINT32_MAX, UINT32_MAX));
        EXPECT_EQ_U32(sentinel.total_steps, p.total_steps);
        EXPECT_EQ_U32(sentinel.accel_steps, p.accel_steps);
        EXPECT_EQ_U32(sentinel.cruise_hz, p.cruise_hz);
        /* A large-but-fitting triangle (2*a*d*total = 2e14) must still work. */
        EXPECT_TRUE(ec_step_profile_plan(&p, 100U, 100U, 1000000U, 100U,
                                         1000000U, 1000000U));
        expect_profile_consistent(&p);
        EXPECT_EQ_U32(10000U, p.cruise_hz);
    }
}
