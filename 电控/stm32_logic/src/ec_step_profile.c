#include "ec_step_profile.h"

#include <stddef.h>   /* NULL */

/* Integer square root, floor(sqrt(n)). ~64 shift/compare iterations, well
 * under 1 us on the 168 MHz M4 - fast enough for the per-step ISR at this
 * project's max 10 kHz step rate. */
static uint64_t ec_isqrt_u64(uint64_t n)
{
    uint64_t r = 0U;
    uint64_t bit;

    if (n == 0U) {
        return 0U;
    }

    /* Highest power of four that fits in a uint64_t is 4^31 = 2^62. */
    bit = ((uint64_t)1U) << 62U;
    while (bit > n) {
        bit >>= 2U;
    }

    while (bit != 0U) {
        const uint64_t candidate = r + bit;
        if (n >= candidate) {
            n -= candidate;
            r = (r >> 1U) + bit;
        } else {
            r >>= 1U;
        }
        bit >>= 2U;
    }
    return r;
}

/* Nearest-integer square root, round(sqrt(n)) = floor(sqrt(n) + 0.5). */
static uint64_t ec_isqrt_u64_round(uint64_t n)
{
    const uint64_t r = ec_isqrt_u64(n);

    /* r^2 <= n < (r+1)^2. The midpoint between r and r+1 is r^2 + r + 1/4, so
     * round up exactly when n - r^2 > r. */
    if ((n - (r * r)) > r) {
        return r + 1U;
    }
    return r;
}

bool ec_step_profile_plan(ec_step_profile_t *p,
                          uint32_t total_steps,
                          uint32_t start_hz, uint32_t cruise_hz, uint32_t end_hz,
                          uint32_t accel_hz_per_s, uint32_t decel_hz_per_s)
{
    uint64_t peak_hz;      /* peak frequency actually reached */
    uint64_t accel_steps;  /* steps in the accel phase */
    uint64_t decel_steps;  /* steps in the decel phase */
    uint64_t cruise_steps; /* steps held at peak_hz (>=0) */

    if ((p == NULL) || (total_steps == 0U) ||
        (start_hz == 0U) || (end_hz == 0U) ||
        (cruise_hz < start_hz) || (cruise_hz < end_hz) ||
        (accel_hz_per_s == 0U) || (decel_hz_per_s == 0U)) {
        return false;
    }

    /* Phase lengths at the requested cruise, from f^2 = f0^2 + 2*a*step
     * (accel) and f^2 = cruise^2 - 2*d*step (decel):
     *     accel_steps = (cruise^2 - start^2) / (2*a)
     *     decel_steps = (cruise^2 - end^2)   / (2*d)
     * All in uint64_t so large cruise_hz / accel rates cannot overflow. */
    {
        const uint64_t cruise2 = (uint64_t)cruise_hz * (uint64_t)cruise_hz;
        const uint64_t start2 = (uint64_t)start_hz * (uint64_t)start_hz;
        const uint64_t end2 = (uint64_t)end_hz * (uint64_t)end_hz;

        accel_steps = (cruise2 - start2) / (2U * (uint64_t)accel_hz_per_s);
        decel_steps = (cruise2 - end2) / (2U * (uint64_t)decel_hz_per_s);
        peak_hz = cruise_hz;
    }

    /* Triangle case: the move is too short to reach the requested cruise, so
     * the peak is lowered until accel + decel fills total_steps. Solve
     *     (v^2 - start^2)/(2a) + (v^2 - end^2)/(2d) = total_steps
     * for v:
     *     v^2 = (2*a*d*total_steps + d*start^2 + a*end^2) / (a + d)          */
    if ((accel_steps + decel_steps) > total_steps) {
        const uint64_t a = accel_hz_per_s;
        const uint64_t d = decel_hz_per_s;
        const uint64_t start2 = (uint64_t)start_hz * (uint64_t)start_hz;
        const uint64_t end2 = (uint64_t)end_hz * (uint64_t)end_hz;
        uint64_t v2;

        /* Overflow guard: the peak formula's three products (2*a*d*total,
         * d*start2, a*end2) must fit in uint64. Only reachable with absurd
         * rates (>= ~1e9 Hz/s) or near-UINT32_MAX moves; fail closed instead
         * of silently wrapping to a wrong peak. 2U * total_steps cannot wrap
         * (total_steps <= UINT32_MAX). */
        if ((a > (UINT64_MAX / d)) ||
            ((a * d) > (UINT64_MAX / (2U * (uint64_t)total_steps))) ||
            (start2 > (UINT64_MAX / d)) ||
            (end2 > (UINT64_MAX / a))) {
            return false;
        }

        v2 = (2U * a * d * (uint64_t)total_steps +
              d * start2 + a * end2) /
             (a + d);

        /* The peak cannot sit below either endpoint; clamp it up. This only
         * triggers when the move is shorter than the start<->end transition
         * itself, i.e. the endpoints cannot both be honoured. */
        if (v2 < start2) {
            v2 = start2;
        }
        if (v2 < end2) {
            v2 = end2;
        }

        peak_hz = ec_isqrt_u64(v2);
        accel_steps = (peak_hz * peak_hz - start2) / (2U * a);
        decel_steps = (peak_hz * peak_hz - end2) / (2U * d);

        /* Still over budget: the move cannot span start<->end at all. Put every
         * step in the one dominant phase so the invariant
         * total == accel + cruise + decel still holds. */
        if ((accel_steps + decel_steps) > total_steps) {
            if (start_hz > end_hz) {
                decel_steps = total_steps;
                accel_steps = 0U;
            } else {
                accel_steps = total_steps;
                decel_steps = 0U;
            }
        }
    }

    /* Whatever the floor() rounding dropped lands here as a short cruise: the
     * full cruise in the trapezoid case, or 0..2 steps in the triangle case. */
    cruise_steps = (uint64_t)total_steps - accel_steps - decel_steps;

    p->total_steps = total_steps;
    p->accel_steps = (uint32_t)accel_steps;
    p->cruise_steps = (uint32_t)cruise_steps;
    p->decel_steps = (uint32_t)decel_steps;
    p->start_hz = start_hz;
    p->cruise_hz = (uint32_t)peak_hz;
    p->end_hz = end_hz;
    p->accel_hz_per_s = accel_hz_per_s;
    p->decel_hz_per_s = decel_hz_per_s;

    return true;
}

uint32_t ec_step_profile_frequency_at(const ec_step_profile_t *p,
                                      uint32_t step_index)
{
    uint64_t f_squared;

    if ((p == NULL) || (step_index >= p->total_steps)) {
        return 0U;
    }

    if (step_index < p->accel_steps) {
        /* f^2 = start^2 + 2*a*step ; step 0 lands exactly on start_hz. */
        f_squared = (uint64_t)p->start_hz * (uint64_t)p->start_hz +
                    2U * (uint64_t)p->accel_hz_per_s * step_index;
    } else if (step_index < (p->accel_steps + p->cruise_steps)) {
        return p->cruise_hz;
    } else {
        /* Decel phase, counted backwards from the end so the final step lands
         * exactly on end_hz: f^2 = end^2 + 2*d*steps_from_end. */
        const uint32_t steps_from_end =
            p->total_steps - 1U - step_index;
        f_squared = (uint64_t)p->end_hz * (uint64_t)p->end_hz +
                    2U * (uint64_t)p->decel_hz_per_s * steps_from_end;
    }

    return (uint32_t)ec_isqrt_u64_round(f_squared);
}

uint32_t ec_step_profile_reload_at(const ec_step_profile_t *p,
                                   uint32_t step_index,
                                   uint32_t timer_hz)
{
    uint32_t frequency;
    uint64_t period;   /* timer_hz / frequency, rounded to nearest */

    if (timer_hz == 0U) {
        return 0U;
    }

    frequency = ec_step_profile_frequency_at(p, step_index);
    if (frequency == 0U) {       /* index out of range */
        return 0U;
    }
    if (frequency >= timer_hz) { /* clamp: fastest, one tick per step */
        return 0U;
    }

    /* round(timer_hz / frequency) = (timer_hz + frequency/2) / frequency, in
     * uint64 so large timer clocks cannot overflow the +frequency/2 term. */
    period = ((uint64_t)timer_hz + (uint64_t)frequency / 2U) /
             (uint64_t)frequency;
    return (uint32_t)period - 1U;   /* ARR = period - 1 */
}
