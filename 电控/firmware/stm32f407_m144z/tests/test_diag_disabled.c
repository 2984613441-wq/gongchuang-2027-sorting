#include "ec_diag.h"
#include "ec_servo_test.h"
#include "ec_step_test.h"

#include <stdbool.h>
#include <string.h>

static char output[512];

void ec_diag_port_write(const char *text)
{
    size_t used = strlen(output);
    size_t length = strlen(text);
    if ((used + length) < sizeof(output)) {
        memcpy(&output[used], text, length + 1U);
    }
}

ec_input_snapshot_t ec_board_read_inputs(void)
{
    ec_input_snapshot_t inputs = {
        EC_INPUT_ALL_MASK, EC_INPUT_ALL_MASK, 0U
    };
    return inputs;
}

ec_step_test_mode_t ec_step_test_mode(void) { return EC_STEP_TEST_IDLE; }
bool ec_motion_test_is_armed(void) { return false; }
ec_axis_t ec_step_test_active_axis(void) { return EC_AXIS_NONE; }
void ec_step_test_stop(void) { }
bool ec_step_test_start(ec_axis_t axis) { (void)axis; return false; }
bool ec_motion_test_arm(uint16_t active_inputs)
{ (void)active_inputs; return false; }
bool ec_motion_test_start(ec_axis_t axis, ec_direction_t direction,
                          uint16_t active_inputs)
{ (void)axis; (void)direction; (void)active_inputs; return false; }
bool ec_motion_test_start_steps(ec_axis_t axis, ec_direction_t direction,
                                uint32_t steps, uint32_t frequency_hz,
                                uint16_t active_inputs)
{ (void)axis; (void)direction; (void)steps; (void)frequency_hz;
  (void)active_inputs; return false; }
uint32_t ec_motion_test_step_target(void) { return 0U; }
uint32_t ec_motion_test_step_remaining(void) { return 0U; }
ec_step_result_t ec_motion_test_step_result(void)
{ return EC_STEP_RESULT_NONE; }

bool ec_servo_test_is_armed(void) { return false; }
bool ec_servo_test_is_running(void) { return false; }
bool ec_servo_test_blocks_step(void) { return false; }
uint16_t ec_servo_test_active_pulse_us(void) { return 0U; }
ec_servo_test_mode_t ec_servo_test_mode(void) { return EC_SERVO_TEST_IDLE; }
void ec_servo_test_stop(void) { }
bool ec_servo_test_arm(uint16_t active_inputs, bool step_test_busy)
{ (void)active_inputs; (void)step_test_busy; return false; }
bool ec_servo_test_start(uint16_t pulse_us, uint16_t active_inputs,
                         bool step_test_busy)
{ (void)pulse_us; (void)active_inputs; (void)step_test_busy; return false; }

int main(void)
{
    output[0] = '\0';
    ec_diag_init();
    ec_diag_process_line("GROUP ARM");
    if (strstr(output, "ERR GROUP_TEST_DISABLED") == NULL) return 1;
    ec_diag_process_line("GROUP START XDIR0 YDIR0 OPEN");
    if (strstr(output, "ERR GROUP_TEST_DISABLED") == NULL) return 2;
    ec_diag_process_line("STATUS");
    if (strstr(output, "GROUP_TEST=0 GROUP_ARMED=0 GROUP_ACTIVE=0") == NULL) {
        return 3;
    }
    return 0;
}
