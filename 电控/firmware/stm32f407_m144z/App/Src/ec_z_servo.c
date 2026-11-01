#include "ec_z_servo.h"

#include "ec_board.h"

static uint16_t current_us = EC_Z_SERVO_MID_US;
static bool ready;

bool ec_z_servo_init(void)
{
    ready = false;
    current_us = EC_Z_SERVO_MID_US;
    if (!ec_board_z_servo_set_us(EC_Z_SERVO_MID_US)) {
        current_us = 0U;
        return false;
    }

    ready = true;
    return true;
}

bool ec_z_servo_set_us(uint16_t pulse_us)
{
    if (!ready || pulse_us < EC_Z_SERVO_MIN_US ||
        pulse_us > EC_Z_SERVO_MAX_US) {
        return false;
    }
    if (!ec_board_z_servo_set_us(pulse_us)) {
        return false;
    }

    current_us = pulse_us;
    return true;
}

bool ec_z_servo_up(void)
{
    return ec_z_servo_set_us(EC_Z_SERVO_UP_US);
}

bool ec_z_servo_down(void)
{
    return ec_z_servo_set_us(EC_Z_SERVO_DOWN_US);
}

bool ec_z_servo_mid(void)
{
    return ec_z_servo_set_us(EC_Z_SERVO_MID_US);
}

bool ec_z_servo_is_ready(void)
{
    return ready;
}

uint16_t ec_z_servo_current_us(void)
{
    return current_us;
}

void ec_z_servo_stop(void)
{
    ec_board_z_servo_stop();
    ready = false;
    current_us = 0U;
}
