#include "ec_bus_servo.h"

/* LEN 字段：MOVE_TIME_WRITE 时固定为 7（ID+LEN+CMD+4 数据字节）。 */
#define BUS_SERVO_MOVE_LEN_FIELD UINT8_C(7)

uint8_t ec_bus_servo_checksum(const uint8_t *frame, size_t len)
{
    uint32_t sum = 0U;
    size_t i;

    if ((frame == NULL) || (len < 4U)) {
        return 0U;
    }
    /* 从索引 2 累加到 len-2（末字节是校验位本身，不含）。 */
    for (i = 2U; (i + 1U) < len; i++) {
        sum += frame[i];
    }
    return (uint8_t)(~sum & UINT32_C(0xFF));
}

size_t ec_bus_servo_build_move(uint8_t *out, size_t out_len, uint8_t id,
                               uint16_t position, uint16_t time_ms)
{
    if ((out == NULL) || (out_len < EC_BUS_SERVO_MOVE_FRAME_LEN)) {
        return 0U;
    }
    /* 越界一律拒绝，不截断 —— 截断会发出角度错误的指令。 */
    if (position > EC_BUS_SERVO_POS_MAX) {
        return 0U;
    }
    if (time_ms > EC_BUS_SERVO_TIME_MAX_MS) {
        return 0U;
    }

    out[0] = EC_BUS_SERVO_HEADER;
    out[1] = EC_BUS_SERVO_HEADER;
    out[2] = id;
    out[3] = BUS_SERVO_MOVE_LEN_FIELD;
    out[4] = EC_BUS_SERVO_CMD_MOVE_TIME_WRITE;
    out[5] = (uint8_t)(position & UINT16_C(0x00FF));
    out[6] = (uint8_t)(position >> 8);
    out[7] = (uint8_t)(time_ms & UINT16_C(0x00FF));
    out[8] = (uint8_t)(time_ms >> 8);
    out[9] = ec_bus_servo_checksum(out, EC_BUS_SERVO_MOVE_FRAME_LEN);
    return EC_BUS_SERVO_MOVE_FRAME_LEN;
}
