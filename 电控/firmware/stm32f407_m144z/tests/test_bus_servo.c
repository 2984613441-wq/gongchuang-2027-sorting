/* 总线舵机帧构造与校验的主机测试。
 * 期望值由手算得出（见注释），用于锁死帧格式 —— 这是最容易写错的一环。 */
#include "ec_bus_servo.h"
#include "test_support.h"

#include <stdio.h>
#include <string.h>

static void test_move_frame_grip_open(void)
{
    uint8_t f[EC_BUS_SERVO_MOVE_FRAME_LEN];
    /* GRIP 400 500 → id=1, LEN=7, cmd=1, pos=400=0x0190, time=500=0x01F4
     * sum(2..8) = 01+07+01+90+01+F4+01 = 399
     * CK = ~399 & 0xFF = 0x70 */
    const uint8_t expect[EC_BUS_SERVO_MOVE_FRAME_LEN] = {
        0x55, 0x55, 0x01, 0x07, 0x01, 0x90, 0x01, 0xF4, 0x01, 0x70
    };
    TEST_ASSERT(ec_bus_servo_build_move(f, sizeof(f), EC_BUS_SERVO_ID_DEFAULT,
                                        EC_GRIP_POS_OPEN, 500U) ==
                EC_BUS_SERVO_MOVE_FRAME_LEN);
    TEST_ASSERT(memcmp(f, expect, sizeof(expect)) == 0);
}

static void test_move_frame_grip_close(void)
{
    uint8_t f[EC_BUS_SERVO_MOVE_FRAME_LEN];
    /* GRIP 640 1000 → pos=640=0x0280, time=1000=0x03E8
     * sum(2..8) = 01+07+01+80+02+E8+03 = 374
     * CK = ~374 & 0xFF。注意 ~x == -(x+1)，故 ~374 = -375，
     *      -375 & 0xFF = 137 = 0x89（不是 0x8A —— 手算时勿漏这个 +1） */
    const uint8_t expect[EC_BUS_SERVO_MOVE_FRAME_LEN] = {
        0x55, 0x55, 0x01, 0x07, 0x01, 0x80, 0x02, 0xE8, 0x03, 0x89
    };
    TEST_ASSERT(ec_bus_servo_build_move(f, sizeof(f), EC_BUS_SERVO_ID_DEFAULT,
                                        EC_GRIP_POS_CLOSE, 1000U) ==
                EC_BUS_SERVO_MOVE_FRAME_LEN);
    TEST_ASSERT(memcmp(f, expect, sizeof(expect)) == 0);
}

static void test_rejects_bad_args(void)
{
    uint8_t f[EC_BUS_SERVO_MOVE_FRAME_LEN];
    /* 位置 1001 超出协议量程 0-1000 —— 必须拒绝，绝不截断成错误角度 */
    TEST_ASSERT(ec_bus_servo_build_move(f, sizeof(f), 1U, 1001U, 500U) == 0U);
    /* 时间 30001 超出上限 */
    TEST_ASSERT(ec_bus_servo_build_move(f, sizeof(f), 1U, 500U, 30001U) == 0U);
    /* 空指针 */
    TEST_ASSERT(ec_bus_servo_build_move(NULL, sizeof(f), 1U, 500U, 500U) == 0U);
    /* 缓冲区不足一帧 */
    TEST_ASSERT(ec_bus_servo_build_move(f, EC_BUS_SERVO_MOVE_FRAME_LEN - 1U,
                                        1U, 500U, 500U) == 0U);
}

static void test_checksum_bounds(void)
{
    const uint8_t f[EC_BUS_SERVO_MOVE_FRAME_LEN] = {
        0x55, 0x55, 0x01, 0x07, 0x01, 0x90, 0x01, 0xF4, 0x01, 0x00
    };
    TEST_ASSERT(ec_bus_servo_checksum(f, EC_BUS_SERVO_MOVE_FRAME_LEN) == 0x70U);
    /* len < 4 或无指针：拒绝而非乱算 */
    TEST_ASSERT(ec_bus_servo_checksum(f, 3U) == 0U);
    TEST_ASSERT(ec_bus_servo_checksum(NULL, EC_BUS_SERVO_MOVE_FRAME_LEN) == 0U);
}

int main(void)
{
    test_move_frame_grip_open();
    test_move_frame_grip_close();
    test_rejects_bad_args();
    test_checksum_bounds();
    printf("ALL BUS SERVO HOST TESTS PASSED\n");
    return 0;
}
