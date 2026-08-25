#include "ec_protocol.h"
#include "test_support.h"

#include <string.h>

void test_protocol(void)
{
    /* CRC-16/MODBUS golden vector: "123456789" -> 0x4B37. */
    static const uint8_t modbus_vector[] = {
        0x31U, 0x32U, 0x33U, 0x34U, 0x35U, 0x36U, 0x37U, 0x38U, 0x39U
    };
    uint8_t buf[64];
    ec_proto_frame_t frame;
    ec_proto_frame_t decoded;
    size_t written;

    TEST_CASE_BEGIN("P-CRC16-001");
    EXPECT_EQ_U32(UINT32_C(0x4B37),
                  ec_crc16_modbus(modbus_vector, sizeof(modbus_vector)));

    /* Frame encode + decode roundtrip. */
    TEST_CASE_BEGIN("P-FRAME-001");
    {
        static const uint8_t payload[] = {0xAAU, 0xBBU, 0xCCU};
        frame.version = EC_PROTO_VERSION;
        frame.sender = EC_DEVICE_PI;
        frame.receiver = EC_DEVICE_STM32;
        frame.task_id = 0x1234U;
        frame.frame_seq = 0x0007U;
        frame.command = EC_CMD_ITEM_TASK;
        frame.payload = payload;
        frame.payload_len = (uint16_t)sizeof(payload);
        written = ec_proto_encode(&frame, buf, sizeof(buf));
        EXPECT_EQ_U32(EC_PROTO_FRAME_OVERHEAD + sizeof(payload), written);
        EXPECT_TRUE(ec_proto_decode(buf, written, &decoded));
        EXPECT_EQ_U8(EC_PROTO_VERSION, decoded.version);
        EXPECT_EQ_U8(EC_DEVICE_PI, decoded.sender);
        EXPECT_EQ_U8(EC_DEVICE_STM32, decoded.receiver);
        EXPECT_EQ_U32(0x1234U, decoded.task_id);
        EXPECT_EQ_U32(0x0007U, decoded.frame_seq);
        EXPECT_EQ_U8(EC_CMD_ITEM_TASK, decoded.command);
        EXPECT_EQ_U32(sizeof(payload), decoded.payload_len);
        EXPECT_TRUE(memcmp(decoded.payload, payload, sizeof(payload)) == 0);
    }

    /* Header bytes and big-endian field layout on the wire. */
    TEST_CASE_BEGIN("P-FRAME-002");
    {
        static const uint8_t payload[] = {0x01U};
        frame.version = EC_PROTO_VERSION;
        frame.sender = EC_DEVICE_PI;
        frame.receiver = EC_DEVICE_STM32;
        frame.task_id = 0x1234U;
        frame.frame_seq = 0x0055U;
        frame.command = EC_CMD_DISPLAY_ACK;
        frame.payload = payload;
        frame.payload_len = 1U;
        written = ec_proto_encode(&frame, buf, sizeof(buf));
        EXPECT_EQ_U8(EC_PROTO_HEADER_0, buf[0]);
        EXPECT_EQ_U8(EC_PROTO_HEADER_1, buf[1]);
        EXPECT_EQ_U8(EC_PROTO_VERSION, buf[2]);
        EXPECT_EQ_U8(0x12U, buf[5]); /* task_id high */
        EXPECT_EQ_U8(0x34U, buf[6]); /* task_id low */
        EXPECT_EQ_U8(0x00U, buf[7]); /* frame_seq high */
        EXPECT_EQ_U8(0x55U, buf[8]); /* frame_seq low */
        EXPECT_EQ_U8(EC_CMD_DISPLAY_ACK, buf[9]);
        EXPECT_EQ_U8(0x00U, buf[10]); /* data_len high */
        EXPECT_EQ_U8(0x01U, buf[11]); /* data_len low */
    }

    /* Decode rejects: bad header, bad version, bad CRC, too short. */
    TEST_CASE_BEGIN("P-FRAME-003");
    {
        frame.version = EC_PROTO_VERSION;
        frame.sender = EC_DEVICE_PI;
        frame.receiver = EC_DEVICE_STM32;
        frame.task_id = 1U;
        frame.frame_seq = 1U;
        frame.command = EC_CMD_HEARTBEAT;
        frame.payload = NULL;
        frame.payload_len = 0U;
        written = ec_proto_encode(&frame, buf, sizeof(buf));
        EXPECT_TRUE(ec_proto_decode(buf, written, &decoded));

        buf[0] = 0x00U; /* corrupt header */
        EXPECT_FALSE(ec_proto_decode(buf, written, &decoded));
        buf[0] = EC_PROTO_HEADER_0;

        buf[2] = 0x02U; /* wrong version */
        EXPECT_FALSE(ec_proto_decode(buf, written, &decoded));
        buf[2] = EC_PROTO_VERSION;

        buf[written - 1U] ^= 0xFFU; /* corrupt CRC */
        EXPECT_FALSE(ec_proto_decode(buf, written, &decoded));

        EXPECT_FALSE(ec_proto_decode(buf, written - 1U, &decoded)); /* short */
    }

    /* DISPLAY_ACK content CRC32 golden vector: 01 02 03 04 05 -> 0x470B99F4. */
    TEST_CASE_BEGIN("P-DACK-001");
    EXPECT_EQ_U32(UINT32_C(0x470B99F4),
                  ec_proto_display_content_crc32(0x01U, 0x02U, 0x03U, 0x04U,
                                                 0x05U));

    /* DISPLAY_ACK payload roundtrip (CRC32 big-endian on the wire). */
    TEST_CASE_BEGIN("P-DACK-002");
    {
        ec_proto_display_ack_t ack;
        ec_proto_display_ack_t ack_out;
        uint8_t dack_buf[EC_DISPLAY_ACK_PAYLOAD_LEN];

        ack.target_seq = 0x03U;
        ack.render_result = EC_DISPLAY_ACK_RENDERED;
        ack.display_crc32 = UINT32_C(0x470B99F4);
        EXPECT_TRUE(ec_proto_encode_display_ack(&ack, dack_buf,
                                                sizeof(dack_buf)));
        EXPECT_EQ_U8(0x03U, dack_buf[0]);
        EXPECT_EQ_U8(EC_DISPLAY_ACK_RENDERED, dack_buf[1]);
        EXPECT_EQ_U8(0x47U, dack_buf[2]); /* CRC32 big-endian */
        EXPECT_EQ_U8(0x0BU, dack_buf[3]);
        EXPECT_EQ_U8(0x99U, dack_buf[4]);
        EXPECT_EQ_U8(0xF4U, dack_buf[5]);
        EXPECT_TRUE(ec_proto_decode_display_ack(dack_buf, sizeof(dack_buf),
                                                &ack_out));
        EXPECT_EQ_U8(0x03U, ack_out.target_seq);
        EXPECT_EQ_U8(EC_DISPLAY_ACK_RENDERED, ack_out.render_result);
        EXPECT_EQ_U32(UINT32_C(0x470B99F4), ack_out.display_crc32);
        EXPECT_FALSE(ec_proto_decode_display_ack(dack_buf,
                                                 sizeof(dack_buf) - 1U,
                                                 &ack_out));
    }

    /* ITEM_TASK: full 8-byte payload golden (interface-contract sec. 5.2).
     * target_seq=1, class_id=2, image_id=2, X=-100.0 mm, Y=+100.0 mm,
     * grip_angle=0xFF -> 01 02 02 FC 18 03 E8 FF. */
    TEST_CASE_BEGIN("P-ITEM-001");
    {
        static const uint8_t golden[] = {
            0x01U, 0x02U, 0x02U, 0xFCU, 0x18U, 0x03U, 0xE8U, 0xFFU
        };
        ec_proto_item_task_t item;
        uint8_t enc[EC_PROTO_ITEM_TASK_PAYLOAD_LEN];

        EXPECT_TRUE(ec_proto_decode_item_task(golden, sizeof(golden), &item));
        EXPECT_EQ_U8(0x01U, item.target_seq);
        EXPECT_EQ_U8(0x02U, item.class_id);
        EXPECT_EQ_U8(0x02U, item.image_id);
        EXPECT_EQ_I16(-1000, item.x_mm10);
        EXPECT_EQ_I16(1000, item.y_mm10);
        EXPECT_EQ_U8(0xFFU, item.grip_angle);

        EXPECT_TRUE(ec_proto_encode_item_task(&item, enc, sizeof(enc)));
        EXPECT_TRUE(memcmp(enc, golden, sizeof(golden)) == 0);
    }

    /* ITEM_TASK: +-135.0 mm boundaries accepted and encoded big-endian. */
    TEST_CASE_BEGIN("P-ITEM-002");
    {
        ec_proto_item_task_t item;
        uint8_t enc[EC_PROTO_ITEM_TASK_PAYLOAD_LEN];

        item.target_seq = 0x01U;
        item.class_id = 0x02U;
        item.image_id = 0x02U;
        item.x_mm10 = 1350;
        item.y_mm10 = -1350;
        item.grip_angle = 0xFFU;
        EXPECT_TRUE(ec_proto_encode_item_task(&item, enc, sizeof(enc)));
        EXPECT_EQ_U8(0x05U, enc[3]); /* X high: +1350 */
        EXPECT_EQ_U8(0x46U, enc[4]); /* X low */
        EXPECT_EQ_U8(0xFAU, enc[5]); /* Y high: -1350 */
        EXPECT_EQ_U8(0xBAU, enc[6]); /* Y low */

        EXPECT_TRUE(ec_proto_decode_item_task(enc, sizeof(enc), &item));
        EXPECT_EQ_I16(1350, item.x_mm10);
        EXPECT_EQ_I16(-1350, item.y_mm10);
    }

    /* ITEM_TASK: out-of-range X/Y, non-0xFF angle, and short payload reject. */
    TEST_CASE_BEGIN("P-ITEM-003");
    {
        static const uint8_t bad_x[] = {
            0x01U, 0x02U, 0x02U, 0x05U, 0x47U, 0x03U, 0xE8U, 0xFFU
        }; /* X=+1351 */
        static const uint8_t bad_y[] = {
            0x01U, 0x02U, 0x02U, 0xFCU, 0x18U, 0xFAU, 0xB9U, 0xFFU
        }; /* Y=-1351 */
        static const uint8_t bad_angle[] = {
            0x01U, 0x02U, 0x02U, 0xFCU, 0x18U, 0x03U, 0xE8U, 0x2DU
        };
        static const uint8_t short_payload[] = {
            0x01U, 0x02U, 0x02U, 0xFCU, 0x18U, 0x03U, 0xE8U
        };
        ec_proto_item_task_t item;

        EXPECT_FALSE(ec_proto_decode_item_task(bad_x, sizeof(bad_x), &item));
        EXPECT_FALSE(ec_proto_decode_item_task(bad_y, sizeof(bad_y), &item));
        EXPECT_FALSE(ec_proto_decode_item_task(bad_angle, sizeof(bad_angle),
                                               &item));
        EXPECT_FALSE(ec_proto_decode_item_task(short_payload,
                                               sizeof(short_payload), &item));
    }

    /* ITEM_TASK: encode rejects out-of-range X/Y and non-0xFF angle. */
    TEST_CASE_BEGIN("P-ITEM-004");
    {
        ec_proto_item_task_t item;
        uint8_t enc[EC_PROTO_ITEM_TASK_PAYLOAD_LEN];

        item.target_seq = 1U;
        item.class_id = 2U;
        item.image_id = 2U;
        item.x_mm10 = 1351;
        item.y_mm10 = 0;
        item.grip_angle = 0xFFU;
        EXPECT_FALSE(ec_proto_encode_item_task(&item, enc, sizeof(enc)));

        item.x_mm10 = 0;
        item.y_mm10 = -1351;
        EXPECT_FALSE(ec_proto_encode_item_task(&item, enc, sizeof(enc)));

        item.y_mm10 = 0;
        item.grip_angle = 0x2DU;
        EXPECT_FALSE(ec_proto_encode_item_task(&item, enc, sizeof(enc)));

        item.grip_angle = 0xFFU;
        EXPECT_FALSE(ec_proto_encode_item_task(&item, enc,
                                               EC_PROTO_ITEM_TASK_PAYLOAD_LEN - 1U));
    }
}
