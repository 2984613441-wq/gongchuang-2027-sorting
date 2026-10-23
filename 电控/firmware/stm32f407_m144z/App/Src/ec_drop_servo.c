#include "ec_drop_servo.h"

#include "ec_board.h"

static uint16_t current_us = EC_DROP_SERVO_MID_US;
static bool ready;

bool ec_drop_servo_init(void)
{
    ready = false;
    current_us = EC_DROP_SERVO_MID_US;
    if (!ec_board_drop_servo_set_us(EC_DROP_SERVO_MID_US)) {
        current_us = 0U;
        return false;
    }

    ready = true;
    return true;
}

bool ec_drop_servo_set_us(uint16_t pulse_us)
{
    if (!ready || pulse_us < EC_DROP_SERVO_MIN_US ||
        pulse_us > EC_DROP_SERVO_MAX_US) {
        return false;
    }
    if (!ec_board_drop_servo_set_us(pulse_us)) {
        return false;
    }

    current_us = pulse_us;
    return true;
}

bool ec_drop_servo_open(void)
{
    return ec_drop_servo_set_us(EC_DROP_SERVO_OPEN_US);
}

bool ec_drop_servo_close(void)
{
    return ec_drop_servo_set_us(EC_DROP_SERVO_CLOSE_US);
}

bool ec_drop_servo_mid(void)
{
    return ec_drop_servo_set_us(EC_DROP_SERVO_MID_US);
}

bool ec_drop_servo_is_ready(void)
{
    return ready;
}

uint16_t ec_drop_servo_current_us(void)
{
    return current_us;
}

void ec_drop_servo_stop(void)
{
    ec_board_drop_servo_stop();
    current_us = 0U;
}
