#include "ec_crc32.h"
#include "test_support.h"

void test_crc32(void)
{
    static const uint8_t vector[] = {0x01U, 0x02U, 0x03U, 0x04U, 0x05U};
    uint8_t network_order[4];
    uint32_t crc;

    TEST_CASE_BEGIN("C-CRC-001");
    crc = ec_crc32_iso_hdlc(vector, sizeof(vector));
    EXPECT_EQ_U32(UINT32_C(0x470B99F4), crc);

    TEST_CASE_BEGIN("C-CRC-002");
    network_order[0] = (uint8_t)(crc >> 24U);
    network_order[1] = (uint8_t)(crc >> 16U);
    network_order[2] = (uint8_t)(crc >> 8U);
    network_order[3] = (uint8_t)crc;
    EXPECT_EQ_U8(0x47U, network_order[0]);
    EXPECT_EQ_U8(0x0BU, network_order[1]);
    EXPECT_EQ_U8(0x99U, network_order[2]);
    EXPECT_EQ_U8(0xF4U, network_order[3]);
}
