#include "ec_protocol.h"

#include <stdio.h>

/* Host-only cross-language reference: emit the same frame used by the Python
 * outer-frame test as one uppercase, space-separated hex line. */
int main(void)
{
    static const uint8_t payload[] = {0xAAU, 0xBBU, 0xCCU};
    uint8_t buf[64];
    size_t written;
    size_t i;
    ec_proto_frame_t frame;

    frame.version = EC_PROTO_VERSION;
    frame.sender = EC_DEVICE_PI;
    frame.receiver = EC_DEVICE_STM32;
    frame.task_id = 0x1234U;
    frame.frame_seq = 0x0007U;
    frame.command = EC_CMD_ITEM_TASK;
    frame.payload = payload;
    frame.payload_len = (uint16_t)sizeof(payload);

    written = ec_proto_encode(&frame, buf, sizeof(buf));
    if (written == 0U) {
        return 1;
    }

    for (i = 0U; i < written; ++i) {
        (void)printf("%02X%c", buf[i], (i + 1U < written) ? ' ' : '\n');
    }
    return 0;
}
