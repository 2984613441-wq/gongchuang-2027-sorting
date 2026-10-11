/* test_ec_interp.c - Unit tests for XY interpolation algorithm
 *
 * Tests Bresenham line interpolation correctness across various scenarios:
 * - 45° diagonal lines
 * - Shallow/steep angles
 * - Negative directions
 * - Single-axis degenerate cases
 */

#include "ec_interp.h"
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>

/* Simple test framework */
static int test_count = 0;
static int test_passed = 0;

#define TEST_ASSERT(cond) do { \
    test_count++; \
    if (!(cond)) { \
        printf("FAIL at line %d: %s\n", __LINE__, #cond); \
    } else { \
        test_passed++; \
    } \
} while(0)

static void test_diagonal_45deg(void)
{
    printf("Test: 45° diagonal (0,0) -> (10,10)\n");
    interp_state_t state;
    interp_init(&state, 0, 0, 10, 10);

    int x_steps = 0, y_steps = 0;

    while (!interp_is_finished(&state)) {
        interp_axis_t axis = interp_step(&state);
        if (axis & INTERP_AXIS_X) x_steps++;
        if (axis & INTERP_AXIS_Y) y_steps++;
    }

    TEST_ASSERT(x_steps == 10);
    TEST_ASSERT(y_steps == 10);
    TEST_ASSERT(state.x_current == 10);
    TEST_ASSERT(state.y_current == 10);
}

static void test_shallow_angle(void)
{
    printf("Test: Shallow angle (0,0) -> (100,20)\n");
    interp_state_t state;
    interp_init(&state, 0, 0, 100, 20);

    int x_steps = 0, y_steps = 0;

    while (!interp_is_finished(&state)) {
        interp_axis_t axis = interp_step(&state);
        if (axis & INTERP_AXIS_X) x_steps++;
        if (axis & INTERP_AXIS_Y) y_steps++;
    }

    TEST_ASSERT(x_steps == 100);
    TEST_ASSERT(y_steps == 20);
    TEST_ASSERT(state.x_current == 100);
    TEST_ASSERT(state.y_current == 20);
}

static void test_steep_angle(void)
{
    printf("Test: Steep angle (0,0) -> (20,100)\n");
    interp_state_t state;
    interp_init(&state, 0, 0, 20, 100);

    int x_steps = 0, y_steps = 0;

    while (!interp_is_finished(&state)) {
        interp_axis_t axis = interp_step(&state);
        if (axis & INTERP_AXIS_X) x_steps++;
        if (axis & INTERP_AXIS_Y) y_steps++;
    }

    TEST_ASSERT(x_steps == 20);
    TEST_ASSERT(y_steps == 100);
    TEST_ASSERT(state.x_current == 20);
    TEST_ASSERT(state.y_current == 100);
}

static void test_negative_x(void)
{
    printf("Test: Negative X (0,0) -> (-50,30)\n");
    interp_state_t state;
    interp_init(&state, 0, 0, -50, 30);

    int x_steps = 0, y_steps = 0;

    while (!interp_is_finished(&state)) {
        interp_axis_t axis = interp_step(&state);
        if (axis & INTERP_AXIS_X) x_steps++;
        if (axis & INTERP_AXIS_Y) y_steps++;
    }

    TEST_ASSERT(x_steps == 50);
    TEST_ASSERT(y_steps == 30);
    TEST_ASSERT(state.x_current == -50);
    TEST_ASSERT(state.y_current == 30);
}

static void test_negative_y(void)
{
    printf("Test: Negative Y (0,0) -> (30,-50)\n");
    interp_state_t state;
    interp_init(&state, 0, 0, 30, -50);

    int x_steps = 0, y_steps = 0;

    while (!interp_is_finished(&state)) {
        interp_axis_t axis = interp_step(&state);
        if (axis & INTERP_AXIS_X) x_steps++;
        if (axis & INTERP_AXIS_Y) y_steps++;
    }

    TEST_ASSERT(x_steps == 30);
    TEST_ASSERT(y_steps == 50);
    TEST_ASSERT(state.x_current == 30);
    TEST_ASSERT(state.y_current == -50);
}

static void test_both_negative(void)
{
    printf("Test: Both negative (10,10) -> (-20,-30)\n");
    interp_state_t state;
    interp_init(&state, 10, 10, -20, -30);

    int x_steps = 0, y_steps = 0;

    while (!interp_is_finished(&state)) {
        interp_axis_t axis = interp_step(&state);
        if (axis & INTERP_AXIS_X) x_steps++;
        if (axis & INTERP_AXIS_Y) y_steps++;
    }

    TEST_ASSERT(x_steps == 30);  /* |10 - (-20)| = 30 */
    TEST_ASSERT(y_steps == 40);  /* |10 - (-30)| = 40 */
    TEST_ASSERT(state.x_current == -20);
    TEST_ASSERT(state.y_current == -30);
}

static void test_x_only(void)
{
    printf("Test: X-only (0,0) -> (50,0)\n");
    interp_state_t state;
    interp_init(&state, 0, 0, 50, 0);

    int x_steps = 0, y_steps = 0;

    while (!interp_is_finished(&state)) {
        interp_axis_t axis = interp_step(&state);
        if (axis & INTERP_AXIS_X) x_steps++;
        if (axis & INTERP_AXIS_Y) y_steps++;
    }

    TEST_ASSERT(x_steps == 50);
    TEST_ASSERT(y_steps == 0);
    TEST_ASSERT(state.x_current == 50);
    TEST_ASSERT(state.y_current == 0);
}

static void test_y_only(void)
{
    printf("Test: Y-only (0,0) -> (0,50)\n");
    interp_state_t state;
    interp_init(&state, 0, 0, 0, 50);

    int x_steps = 0, y_steps = 0;

    while (!interp_is_finished(&state)) {
        interp_axis_t axis = interp_step(&state);
        if (axis & INTERP_AXIS_X) x_steps++;
        if (axis & INTERP_AXIS_Y) y_steps++;
    }

    TEST_ASSERT(x_steps == 0);
    TEST_ASSERT(y_steps == 50);
    TEST_ASSERT(state.x_current == 0);
    TEST_ASSERT(state.y_current == 50);
}

static void test_zero_distance(void)
{
    printf("Test: Zero distance (5,5) -> (5,5)\n");
    interp_state_t state;
    interp_init(&state, 5, 5, 5, 5);

    TEST_ASSERT(interp_is_finished(&state) == false);  /* Not finished yet */

    interp_axis_t axis = interp_step(&state);
    TEST_ASSERT(axis == INTERP_AXIS_NONE);  /* First step detects completion */
    TEST_ASSERT(interp_is_finished(&state) == true);
}

int main(void)
{
    printf("=== XY Interpolation Algorithm Tests ===\n\n");

    test_diagonal_45deg();
    test_shallow_angle();
    test_steep_angle();
    test_negative_x();
    test_negative_y();
    test_both_negative();
    test_x_only();
    test_y_only();
    test_zero_distance();

    printf("\n=== Test Summary ===\n");
    printf("Passed: %d/%d\n", test_passed, test_count);

    return (test_passed == test_count) ? 0 : 1;
}
