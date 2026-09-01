#ifndef EC_STEP_PROFILE_H
#define EC_STEP_PROFILE_H

#include <stdbool.h>
#include <stdint.h>

/* Trapezoidal (accelerate / cruise / decelerate) velocity profile for a
 * single-axis stepper move, expressed entirely in the step domain (steps and
 * Hz). It is intentionally independent of millimetres, the mechanical
 * transmission ratio, the driver model, and the timer clock: the firmware
 * port layer converts Hz -> timer reload at the point of use, exactly as the
 * state-machine spec requires that no PWM parameter or driver model appear in
 * the hardware-independent layer (stm32-state-machine-pseudocode.md sec. 2).
 *
 * The profile follows the standard constant-acceleration model:
 *
 *     f(step)^2 = start_hz^2 + 2 * accel_hz_per_s * step   (accel phase)
 *     f         = cruise_hz                                 (cruise phase)
 *     f(step)^2 = cruise_hz^2 - 2 * decel_hz_per_s * step   (decel phase)
 *
 * This gives the physically correct sqrt-spacing of step delays, so the motor
 * is not asked to jump from rest to cruise (which is what loses steps).
 *
 * Rounding: the phase lengths use floor() integer division, which makes the
 * profile slightly conservative (the last accel step may land marginally below
 * cruise_hz) rather than overshooting. All frequency squares are computed in
 * uint64_t to avoid overflow for large accel rates / long moves.
 */

typedef struct {
    uint32_t total_steps;    /* == accel_steps + cruise_steps + decel_steps */
    uint32_t accel_steps;    /* steps from start_hz up to cruise_hz */
    uint32_t cruise_steps;   /* steps held at cruise_hz (0 in the triangle case) */
    uint32_t decel_steps;    /* steps from cruise_hz down to end_hz */
    uint32_t start_hz;       /* first-step frequency (>=1) */
    uint32_t cruise_hz;      /* peak actually reached (<= the requested cruise) */
    uint32_t end_hz;         /* final-step frequency (>=1) */
    uint32_t accel_hz_per_s; /* acceleration rate, Hz/s (>=1) */
    uint32_t decel_hz_per_s; /* deceleration rate, Hz/s (>=1) */
} ec_step_profile_t;

/* Compute the trapezoid plan for a move of `total_steps`.
 *
 *   total_steps  steps to move (>=1)
 *   start_hz     frequency of the first step (1..cruise_hz)
 *   cruise_hz    requested peak frequency (>=start_hz, >=end_hz)
 *   end_hz       frequency of the final step (1..cruise_hz)
 *   accel_hz_per_s  acceleration rate in Hz/s (>=1)
 *   decel_hz_per_s  deceleration rate in Hz/s (>=1)
 *
 * Handles the "triangle" case (total_steps too short to reach the requested
 * cruise): cruise_hz is lowered to the peak frequency that exactly fills the
 * move and cruise_steps becomes 0. The lowered peak is written back to
 * p->cruise_hz so the caller always sees the profile that was actually built.
 *
 * Returns false only on invalid parameters (leaves *p untouched on failure);
 * a valid-but-triangle plan still returns true.
 */
bool ec_step_profile_plan(ec_step_profile_t *p,
                          uint32_t total_steps,
                          uint32_t start_hz, uint32_t cruise_hz, uint32_t end_hz,
                          uint32_t accel_hz_per_s, uint32_t decel_hz_per_s);

/* Frequency (Hz, rounded to nearest) of the step at `step_index` (0-based,
 * step_index < total_steps). Safe to call from the step-timer ISR: the integer
 * sqrt is ~1 us on a 168 MHz M4, negligible against the 100 us worst case
 * (10 kHz) step period, so no delay table or recurrence is needed.
 * Returns 0 for an out-of-range index. */
uint32_t ec_step_profile_frequency_at(const ec_step_profile_t *p,
                                      uint32_t step_index);

/* Timer reload value (ARR) for the step at `step_index`, given a step-timer
 * clock of `timer_hz` ticks/second. This is the single hardware-adjacent
 * quantity in this layer, and even it is just an integer tick count, not a
 * register write:
 *
 *     reload = round(timer_hz / frequency) - 1     (ARR = period - 1)
 *
 * Returns 0 when the index is out of range (>= total_steps), when timer_hz is
 * 0, or when frequency >= timer_hz (clamped to the fastest legal rate, one
 * tick per step). The caller is responsible for ensuring the result fits the
 * timer's reload register (16-bit on TIM4/TIM8); for this project the 10 Hz
 * floor means reload <= 9999, which fits. */
uint32_t ec_step_profile_reload_at(const ec_step_profile_t *p,
                                   uint32_t step_index,
                                   uint32_t timer_hz);

#endif
