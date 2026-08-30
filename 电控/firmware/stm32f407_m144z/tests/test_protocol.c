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

    TEST_ASSERT(ec_crc16_modbus(modbus_vector, sizeof(modbus_vector)) == 0x4B37U);

    /* Frame encode + decode roundtrip. */
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
        TEST_ASSERT(written == EC_PROTO_FRAME_OVERHEAD + sizeof(payload));
        TEST_ASSERT(ec_proto_decode(buf, written, &decoded));
        TEST_ASSERT(decoded.version == EC_PROTO_VERSION);
        TEST_ASSERT(decoded.sender == EC_DEVICE_PI);
        TEST_ASSERT(decoded.receiver == EC_DEVICE_STM32);
        TEST_ASSERT(decoded.task_id == 0x1234U);
        TEST_ASSERT(decoded.frame_seq == 0x0007U);
        TEST_ASSERT(decoded.command == EC_CMD_ITEM_TASK);
        TEST_ASSERT(decoded.payload_len == sizeof(payload));
        TEST_ASSERT(memcmp(decoded.payload, payload, sizeof(payload)) == 0);
    }

    /* Big-endian field layout on the wire. */
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
        TEST_ASSERT(buf[0] == EC_PROTO_HEADER_0);
        TEST_ASSERT(buf[1] == EC_PROTO_HEADER_1);
        TEST_ASSERT(buf[2] == EC_PROTO_VERSION);
        TEST_ASSERT(buf[5] == 0x12U); /* task_id high */
        TEST_ASSERT(buf[6] == 0x34U); /* task_id low */
        TEST_ASSERT(buf[7] == 0x00U); /* frame_seq high */
        TEST_ASSERT(buf[8] == 0x55U); /* frame_seq low */
        TEST_ASSERT(buf[9] == EC_CMD_DISPLAY_ACK);
        TEST_ASSERT(buf[10] == 0x00U); /* data_len high */
        TEST_ASSERT(buf[11] == 0x01U); /* data_len low */
    }

    /* Decode rejects: bad header, bad version, bad CRC, too short. */
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
        TEST_ASSERT(ec_proto_decode(buf, written, &decoded));

        buf[0] = 0x00U; /* corrupt header */
        TEST_ASSERT(!ec_proto_decode(buf, written, &decoded));
        buf[0] = EC_PROTO_HEADER_0;

        buf[2] = 0x02U; /* wrong version */
        TEST_ASSERT(!ec_proto_decode(buf, written, &decoded));
        buf[2] = EC_PROTO_VERSION;

        buf[written - 1U] ^= 0xFFU; /* corrupt CRC */
        TEST_ASSERT(!ec_proto_decode(buf, written, &decoded));

        TEST_ASSERT(!ec_proto_decode(buf, written - 1U, &decoded)); /* short */
    }

    /* DISPLAY_ACK content CRC32 golden vector: 01 02 03 04 05 -> 0x470B99F4. */
    TEST_ASSERT(ec_proto_display_content_crc32(0x01U, 0x02U, 0x03U, 0x04U,
                                               0x05U) == UINT32_C(0x470B99F4));

    /* DISPLAY_ACK payload roundtrip (CRC32 big-endian on the wire). */
    {
        ec_proto_display_ack_t ack;
        ec_proto_display_ack_t ack_out;
        uint8_t dack_buf[EC_DISPLAY_ACK_PAYLOAD_LEN];

        ack.target_seq = 0x03U;
        ack.render_result = EC_DISPLAY_ACK_RENDERED;
        ack.display_crc32 = UINT32_C(0x470B99F4);
        TEST_ASSERT(ec_proto_encode_display_ack(&ack, dack_buf,
                                                sizeof(dack_buf)));
        TEST_ASSERT(dack_buf[0] == 0x03U);
        TEST_ASSERT(dack_buf[1] == EC_DISPLAY_ACK_RENDERED);
        TEST_ASSERT(dack_buf[2] == 0x47U);
        TEST_ASSERT(dack_buf[3] == 0x0BU);
        TEST_ASSERT(dack_buf[4] == 0x99U);
        TEST_ASSERT(dack_buf[5] == 0xF4U);
        TEST_ASSERT(ec_proto_decode_display_ack(dack_buf, sizeof(dack_buf),
                                                &ack_out));
        TEST_ASSERT(ack_out.target_seq == 0x03U);
        TEST_ASSERT(ack_out.render_result == EC_DISPLAY_ACK_RENDERED);
        TEST_ASSERT(ack_out.display_crc32 == UINT32_C(0x470B99F4));
        TEST_ASSERT(!ec_proto_decode_display_ack(dack_buf,
                                                 sizeof(dack_buf) - 1U,
                                                 &ack_out));
    }

    /* ITEM_TASK: full 8-byte payload golden (interface-contract sec. 5.2).
     * target_seq=1, class_id=2, image_id=2, X=-100.0 mm, Y=+100.0 mm,
     * grip_angle=0xFF -> 01 02 02 FC 18 03 E8 FF. */
    {
        static const uint8_t golden[] = {
            0x01U, 0x02U, 0x02U, 0xFCU, 0x18U, 0x03U, 0xE8U, 0xFFU
        };
        ec_proto_item_task_t item;
        uint8_t enc[EC_PROTO_ITEM_TASK_PAYLOAD_LEN];

        TEST_ASSERT(ec_proto_decode_item_task(golden, sizeof(golden), &item));
        TEST_ASSERT(item.target_seq == 0x01U);
        TEST_ASSERT(item.class_id == 0x02U);
        TEST_ASSERT(item.image_id == 0x02U);
        TEST_ASSERT(item.x_mm10 == -1000);
        TEST_ASSERT(item.y_mm10 == 1000);
        TEST_ASSERT(item.grip_angle == 0xFFU);

        TEST_ASSERT(ec_proto_encode_item_task(&item, enc, sizeof(enc)));
        TEST_ASSERT(memcmp(enc, golden, sizeof(golden)) == 0);
    }

    /* ITEM_TASK: +-135.0 mm boundaries accepted and encoded big-endian. */
    {
        ec_proto_item_task_t item;
        uint8_t enc[EC_PROTO_ITEM_TASK_PAYLOAD_LEN];

        item.target_seq = 0x01U;
        item.class_id = 0x02U;
        item.image_id = 0x02U;
        item.x_mm10 = 1450;
        item.y_mm10 = -1450;
        item.grip_angle = 0xFFU;
        TEST_ASSERT(ec_proto_encode_item_task(&item, enc, sizeof(enc)));
        TEST_ASSERT(enc[3] == 0x05U); /* X high: +1450 */
        TEST_ASSERT(enc[4] == 0xAAU); /* X low */
        TEST_ASSERT(enc[5] == 0xFAU); /* Y high: -1450 */
        TEST_ASSERT(enc[6] == 0x56U); /* Y low */

        TEST_ASSERT(ec_proto_decode_item_task(enc, sizeof(enc), &item));
        TEST_ASSERT(item.x_mm10 == 1450);
        TEST_ASSERT(item.y_mm10 == -1450);
    }

    /* ITEM_TASK: out-of-range X/Y, non-0xFF angle, and short payload reject. */
    {
        static const uint8_t bad_x[] = {
            0x01U, 0x02U, 0x02U, 0x05U, 0xABU, 0x03U, 0xE8U, 0xFFU
        }; /* X=+1451 */
        static const uint8_t bad_y[] = {
            0x01U, 0x02U, 0x02U, 0xFCU, 0x18U, 0xFAU, 0x55U, 0xFFU
        }; /* Y=-1451 */
        static const uint8_t bad_angle[] = {
            0x01U, 0x02U, 0x02U, 0xFCU, 0x18U, 0x03U, 0xE8U, 0x2DU
        };
        static const uint8_t short_payload[] = {
            0x01U, 0x02U, 0x02U, 0xFCU, 0x18U, 0x03U, 0xE8U
        }; /* 7 bytes: missing grip_angle */
        ec_proto_item_task_t item;

        TEST_ASSERT(!ec_proto_decode_item_task(bad_x, sizeof(bad_x), &item));
        TEST_ASSERT(!ec_proto_decode_item_task(bad_y, sizeof(bad_y), &item));
        TEST_ASSERT(!ec_proto_decode_item_task(bad_angle, sizeof(bad_angle),
                                               &item));
        TEST_ASSERT(!ec_proto_decode_item_task(short_payload,
                                               sizeof(short_payload), &item));
    }

    /* ITEM_TASK: encode rejects out-of-range X/Y and non-0xFF angle. */
    {
        ec_proto_item_task_t item;
        uint8_t enc[EC_PROTO_ITEM_TASK_PAYLOAD_LEN];

        item.target_seq = 1U;
        item.class_id = 2U;
        item.image_id = 2U;
        item.x_mm10 = 1451;
        item.y_mm10 = 0;
        item.grip_angle = 0xFFU;
        TEST_ASSERT(!ec_proto_encode_item_task(&item, enc, sizeof(enc)));

        item.x_mm10 = 0;
        item.y_mm10 = -1451;
        TEST_ASSERT(!ec_proto_encode_item_task(&item, enc, sizeof(enc)));

        item.y_mm10 = 0;
        item.grip_angle = 0x2DU;
        TEST_ASSERT(!ec_proto_encode_item_task(&item, enc, sizeof(enc)));

        item.grip_angle = 0xFFU;
        TEST_ASSERT(!ec_proto_encode_item_task(&item, enc,
                                               EC_PROTO_ITEM_TASK_PAYLOAD_LEN - 1U));
    }
}
