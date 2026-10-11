#ifndef EC_SERVO_TEST_H
#define EC_SERVO_TEST_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    EC_SERVO_TEST_IDLE = 0,
    EC_SERVO_TEST_ARMED,
    EC_SERVO_TEST_RUNNING
} ec_servo_test_mode_t;

void ec_servo_test_init(void);
bool ec_servo_test_arm(uint16_t active_inputs, bool step_test_busy);
bool ec_servo_test_start(uint16_t pulse_us, uint16_t active_inputs,
                         bool step_test_busy);
void ec_servo_test_stop(void);
void ec_servo_test_poll(uint32_t now_ms, uint16_t active_inputs);
bool ec_servo_test_is_armed(void);
bool ec_servo_test_is_running(void);
bool ec_servo_test_blocks_step(void);
uint16_t ec_servo_test_active_pulse_us(void);
ec_servo_test_mode_t ec_servo_test_mode(void);

bool ec_servo_port_start(uint16_t pulse_us);
void ec_servo_port_stop(void);
uint32_t ec_servo_port_now_ms(void);

/* Legacy channel: TIM2_CH4 = PB11 (old WRIST/"Z" naming -- that name is VOID).
 * It does NOT drive the Z axis. Z axis + gripper = ONE LDX-335MG digital servo
 * on PB10 = TIM2_CH3 (ec_servo_port_start); lift and jaw are linked, i.e. one
 * single degree of freedom. The old DS3120MG model and the old 1100/1900 us
 * pulse widths are VOID and must be re-measured
 * (docs/测量表-②Z轴行程-2026-09-17.md:19).
 *
 * ec_axis_driver.c stopped starting this channel on 2026-09-16 (only ec_demo.c
 * still calls ec_servo_port_start_z), but its stop_all() still calls
 * ec_servo_port_stop_z(); ec_safety_port_stop_all() does NOT stop this
 * channel. Shares TIM2's 50 Hz servo period with PB10. */
bool ec_servo_port_start_z(uint16_t pulse_us);
void ec_servo_port_stop_z(void);

#endif
