#define main original_axis_test_main
#include "test_axis_driver.c"
#undef main
int main(void) {
    ec_axis_pick_place_t p;
    memset(&p,0,sizeof(p));
    p.step[0].kind=EC_AXIS_STEP_WAIT;
    p.step[0].servo_pulse_us=200;
    reset_log(); g_now_ms=0; ec_axis_driver_init();
    TEST_ASSERT(ec_axis_driver_start_pick_place(&p)==EC_AXIS_RESULT_OK);
    ec_axis_driver_poll(199,0);
    TEST_ASSERT(ec_axis_driver_state()==EC_AXIS_STATE_GRIPPING);
    TEST_ASSERT(ec_axis_driver_progress()==0);
    ec_axis_driver_poll(200,0);
    TEST_ASSERT(ec_axis_driver_state()==EC_AXIS_STATE_DONE);
    TEST_ASSERT(ec_axis_driver_progress()==1);
    TEST_ASSERT(g_z_servo_start_count==0);
    p.step[0].servo_pulse_us=0;
    ec_axis_driver_init();
    TEST_ASSERT(ec_axis_driver_start_pick_place(&p)==EC_AXIS_RESULT_INVALID_PARAM);
    p.step[0].servo_pulse_us=200;
    ec_axis_driver_init(); g_now_ms=0;
    TEST_ASSERT(ec_axis_driver_start_pick_place(&p)==EC_AXIS_RESULT_OK);
    ec_axis_driver_poll(100,EC_INPUT_ESTOP_FB);
    TEST_ASSERT(ec_axis_driver_state()==EC_AXIS_STATE_FAULT);
    puts("WAIT_PROBE PASS: 199ms pending; 200ms done; progress=1; no servo start; zero rejected; ESTOP faults");
    return 0;
}
