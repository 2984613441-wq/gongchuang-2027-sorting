#include "ec_protocol.h"

#include <stdio.h>
#include <string.h>

/* Host-only cross-language reference for the P3 (12-byte) ITEM_TASK payload.
 * Prints one line per vector:
 *
 *   NAME <payload hex> | <whole frame hex>
 *
 * 工具/p3_cross_language_check.py re-derives the same bytes from the Python
 * codec and requires byte equality INCLUDING the CRC. Keep the vector table
 * below and the Python table in that script in sync. */
typedef struct {
    const char *name;
    uint16_t task_id;
    uint16_t frame_seq;
    uint8_t target_seq;
    uint8_t class_id;
    int16_t x_mm10;
    int16_t y_mm10;
    int16_t pick_x_mm10;
    int16_t pick_y_mm10;
} item_task_vector_t;

static const item_task_vector_t vectors[] = {
    /* Golden vector also used by test_protocol.c P-ITEM-001. */
    {"GOLDEN", 0x0007U, 0x000BU, 0x01U, 0x02U, -1000, 1000, 250, -250},
    /* Both pairs at the protocol domain boundary, opposite signs: catches a
     * swapped pair or a missing big-endian byte order. */
    {"BOUND", 0x1234U, 0x00FFU, 0xFFU, 0x02U, 1450, -1450, -1450, 1450},
};

static void print_hex(const uint8_t *data, size_t len)
{
    size_t i;

    for (i = 0U; i < len; ++i) {
        (void)printf("%02X%s", data[i], (i + 1U < len) ? " " : "");
    }
}

int main(void)
{
    size_t v;

    for (v = 0U; v < (sizeof(vectors) / sizeof(vectors[0])); ++v) {
        const item_task_vector_t *vec = &vectors[v];
        ec_proto_item_task_t item;
        ec_proto_frame_t frame;
        uint8_t payload[EC_PROTO_ITEM_TASK_PAYLOAD_LEN];
        uint8_t buf[64];
        size_t written;

        (void)memset(&item, 0, sizeof(item));
        item.target_seq = vec->target_seq;
        item.class_id = vec->class_id;
        item.image_id = vec->class_id; /* frozen 1:1 invariant */
        item.x_mm10 = vec->x_mm10;
        item.y_mm10 = vec->y_mm10;
        item.grip_angle = EC_PROTO_ITEM_TASK_ANGLE_NONE;
        item.pick_x_mm10 = vec->pick_x_mm10;
        item.pick_y_mm10 = vec->pick_y_mm10;

        if (!ec_proto_encode_item_task(&item, payload, sizeof(payload))) {
            return 1;
        }

        frame.version = EC_PROTO_VERSION;
        frame.sender = EC_DEVICE_PI;
        frame.receiver = EC_DEVICE_STM32;
        frame.task_id = vec->task_id;
        frame.frame_seq = vec->frame_seq;
        frame.command = EC_CMD_ITEM_TASK;
        frame.payload = payload;
        frame.payload_len = (uint16_t)sizeof(payload);

        written = ec_proto_encode(&frame, buf, sizeof(buf));
        if (written == 0U) {
            return 1;
        }

        (void)printf("%s ", vec->name);
        print_hex(payload, sizeof(payload));
        (void)printf(" | ");
        print_hex(buf, written);
        (void)printf("\n");
    }

    /* Fail-closed probe: the pre-P3 8-byte payload must be REFUSED by the
     * exact-length check (never reinterpreted as a valid 12-byte one). */
    {
        static const uint8_t old8[] = {0x01U, 0x02U, 0x02U, 0xFCU,
                                       0x18U, 0x03U, 0xE8U, 0xFFU};
        ec_proto_item_task_t item;

        (void)printf("OLD8 %s\n",
                     ec_proto_decode_item_task(old8, (uint16_t)sizeof(old8),
                                               &item)
                         ? "ACCEPTED"
                         : "REJECTED");
    }
    return 0;
}
