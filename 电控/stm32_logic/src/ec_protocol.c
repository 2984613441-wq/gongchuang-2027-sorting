#include "ec_protocol.h"

#include "ec_crc32.h"

#include <string.h>

uint16_t ec_crc16_modbus(const uint8_t *data, size_t length)
{
    uint16_t crc = UINT16_C(0xFFFF);
    size_t index;

    for (index = 0U; index < length; ++index) {
        unsigned int bit;

        crc ^= (uint16_t)data[index];
        for (bit = 0U; bit < 8U; ++bit) {
            if ((crc & UINT16_C(0x0001)) != 0U) {
                crc = (uint16_t)((crc >> 1U) ^ UINT16_C(0xA001));
            } else {
                crc = (uint16_t)(crc >> 1U);
            }
        }
    }
    return crc;
}

size_t ec_proto_encode(const ec_proto_frame_t *frame, uint8_t *out,
                       size_t out_cap)
{
    size_t total;
    uint16_t crc;

    if ((frame == NULL) || (out == NULL)) return 0U;
    if ((frame->payload_len != 0U) && (frame->payload == NULL)) return 0U;
    total = EC_PROTO_HEADER_LEN + (size_t)frame->payload_len +
            EC_PROTO_CRC_LEN;
    if (out_cap < total) return 0U;

    out[0] = EC_PROTO_HEADER_0;
    out[1] = EC_PROTO_HEADER_1;
    out[2] = frame->version;
    out[3] = frame->sender;
    out[4] = frame->receiver;
    out[5] = (uint8_t)(frame->task_id >> 8U);
    out[6] = (uint8_t)frame->task_id;
    out[7] = (uint8_t)(frame->frame_seq >> 8U);
    out[8] = (uint8_t)frame->frame_seq;
    out[9] = frame->command;
    out[10] = (uint8_t)(frame->payload_len >> 8U);
    out[11] = (uint8_t)frame->payload_len;
    if (frame->payload_len != 0U) {
        (void)memcpy(&out[EC_PROTO_HEADER_LEN], frame->payload,
                     frame->payload_len);
    }

    crc = ec_crc16_modbus(out, EC_PROTO_HEADER_LEN + frame->payload_len);
    out[EC_PROTO_HEADER_LEN + frame->payload_len] = (uint8_t)(crc >> 8U);
    out[EC_PROTO_HEADER_LEN + frame->payload_len + 1U] = (uint8_t)crc;
    return total;
}

bool ec_proto_decode(const uint8_t *buf, size_t length, ec_proto_frame_t *frame)
{
    uint16_t data_len;
    uint16_t expected_crc;
    uint16_t actual_crc;

    if ((buf == NULL) || (frame == NULL)) return false;
    if (length < EC_PROTO_FRAME_OVERHEAD) return false;
    if ((buf[0] != EC_PROTO_HEADER_0) || (buf[1] != EC_PROTO_HEADER_1)) {
        return false;
    }
    if (buf[2] != EC_PROTO_VERSION) return false;

    data_len = (uint16_t)(((uint16_t)buf[10] << 8U) | (uint16_t)buf[11]);
    if (length < (EC_PROTO_FRAME_OVERHEAD + (size_t)data_len)) return false;

    expected_crc =
        ec_crc16_modbus(buf, EC_PROTO_HEADER_LEN + (size_t)data_len);
    actual_crc =
        (uint16_t)(((uint16_t)buf[EC_PROTO_HEADER_LEN + data_len] << 8U) |
                   (uint16_t)buf[EC_PROTO_HEADER_LEN + data_len + 1U]);
    if (actual_crc != expected_crc) return false;

    frame->version = buf[2];
    frame->sender = buf[3];
    frame->receiver = buf[4];
    frame->task_id = (uint16_t)(((uint16_t)buf[5] << 8U) | (uint16_t)buf[6]);
    frame->frame_seq = (uint16_t)(((uint16_t)buf[7] << 8U) | (uint16_t)buf[8]);
    frame->command = buf[9];
    frame->payload = &buf[EC_PROTO_HEADER_LEN];
    frame->payload_len = data_len;
    return true;
}

uint32_t ec_proto_display_content_crc32(uint8_t target_seq, uint8_t class_id,
                                        uint8_t image_id,
                                        uint8_t success_count,
                                        uint8_t result_code)
{
    uint8_t sequence[5];

    sequence[0] = target_seq;
    sequence[1] = class_id;
    sequence[2] = image_id;
    sequence[3] = success_count;
    sequence[4] = result_code;
    return ec_crc32_iso_hdlc(sequence, sizeof(sequence));
}

bool ec_proto_encode_display_ack(const ec_proto_display_ack_t *ack,
                                 uint8_t *out, uint16_t out_cap)
{
    if ((ack == NULL) || (out == NULL) || (out_cap < EC_DISPLAY_ACK_PAYLOAD_LEN)) {
        return false;
    }
    out[0] = ack->target_seq;
    out[1] = ack->render_result;
    out[2] = (uint8_t)(ack->display_crc32 >> 24U);
    out[3] = (uint8_t)(ack->display_crc32 >> 16U);
    out[4] = (uint8_t)(ack->display_crc32 >> 8U);
    out[5] = (uint8_t)ack->display_crc32;
    return true;
}

bool ec_proto_decode_display_ack(const uint8_t *payload, uint16_t payload_len,
                                 ec_proto_display_ack_t *out)
{
    if ((payload == NULL) || (out == NULL)) return false;
    /* Exactly 6 bytes, matching the Python codec (== check), so a frame with a
     * longer payload cannot diverge the two implementations. */
    if (payload_len != EC_DISPLAY_ACK_PAYLOAD_LEN) return false;

    out->target_seq = payload[0];
    out->render_result = payload[1];
    out->display_crc32 = ((uint32_t)payload[2] << 24U) |
                         ((uint32_t)payload[3] << 16U) |
                         ((uint32_t)payload[4] << 8U) | (uint32_t)payload[5];
    return true;
}

bool ec_proto_encode_item_task(const ec_proto_item_task_t *item,
                               uint8_t *payload, uint16_t cap)
{
    if ((item == NULL) || (payload == NULL)) return false;
    if (cap < EC_PROTO_ITEM_TASK_PAYLOAD_LEN) return false;
    if ((item->x_mm10 < -EC_PROTO_ITEM_TASK_X_LIMIT) ||
        (item->x_mm10 > EC_PROTO_ITEM_TASK_X_LIMIT)) {
        return false;
    }
    if ((item->y_mm10 < -EC_PROTO_ITEM_TASK_X_LIMIT) ||
        (item->y_mm10 > EC_PROTO_ITEM_TASK_X_LIMIT)) {
        return false;
    }
    if (item->grip_angle != EC_PROTO_ITEM_TASK_ANGLE_NONE) return false;

    payload[0] = item->target_seq;
    payload[1] = item->class_id;
    payload[2] = item->image_id;
    payload[3] = (uint8_t)((uint16_t)item->x_mm10 >> 8U);
    payload[4] = (uint8_t)item->x_mm10;
    payload[5] = (uint8_t)((uint16_t)item->y_mm10 >> 8U);
    payload[6] = (uint8_t)item->y_mm10;
    payload[7] = item->grip_angle;
    return true;
}

bool ec_proto_decode_item_task(const uint8_t *payload, uint16_t payload_len,
                               ec_proto_item_task_t *out)
{
    int16_t x;
    int16_t y;

    if ((payload == NULL) || (out == NULL)) return false;
    if (payload_len != EC_PROTO_ITEM_TASK_PAYLOAD_LEN) return false;
    if (payload[7] != EC_PROTO_ITEM_TASK_ANGLE_NONE) return false;

    /* Big-endian int16 via explicit byte arithmetic (avoids a direct
     * *(int16_t*) dereference, which breaks on little-endian ARM). */
    x = (int16_t)(((uint16_t)payload[3] << 8U) | (uint16_t)payload[4]);
    y = (int16_t)(((uint16_t)payload[5] << 8U) | (uint16_t)payload[6]);
    if ((x < -EC_PROTO_ITEM_TASK_X_LIMIT) || (x > EC_PROTO_ITEM_TASK_X_LIMIT)) {
        return false;
    }
    if ((y < -EC_PROTO_ITEM_TASK_X_LIMIT) || (y > EC_PROTO_ITEM_TASK_X_LIMIT)) {
        return false;
    }

    out->target_seq = payload[0];
    out->class_id = payload[1];
    out->image_id = payload[2];
    out->x_mm10 = x;
    out->y_mm10 = y;
    out->grip_angle = payload[7];
    return true;
}
