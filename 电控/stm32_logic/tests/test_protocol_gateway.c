#include "ec_protocol_gateway.h"
#include "test_support.h"

#include <string.h>

/* Encode `frame` and feed it byte-by-byte into `g`; return the transition
 * produced by the final (frame-complete) byte. */
static ec_transition_t feed_frame(ec_gateway_t *g, const ec_proto_frame_t *frame)
{
    uint8_t buf[EC_GATEWAY_RX_MAX];
    size_t written = ec_proto_encode(frame, buf, sizeof(buf));
    size_t i;
    ec_transition_t t;

    t.state = EC_STATE_FAULT_LOCK;
    t.fault_reason = EC_FAULT_NONE;
    t.actions = EC_ACTION_NONE;

    for (i = 0U; i < written; ++i) {
        t = ec_gateway_feed_byte(g, buf[i]);
    }
    return t;
}

/* Decode the pending TX frame and return its command, or 0xFF when none. */
static uint8_t tx_command(const ec_gateway_t *g)
{
    ec_proto_frame_t frame;

    if (ec_gateway_tx_len(g) == 0U) return UINT8_C(0xFF);
    if (!ec_proto_decode(ec_gateway_tx_data(g), ec_gateway_tx_len(g), &frame)) {
        return UINT8_C(0xFF);
    }
    return frame.command;
}

/* Push the gateway through the boot sequence to WAIT_TASK with round_id 7. */
static void boot_to_wait_task(ec_gateway_t *g)
{
    ec_gateway_event_t ev;
    ec_transition_t t;

    (void)memset(&ev, 0, sizeof(ev));
    ev.type = EC_EVENT_MANUAL_NEW_ROUND_CONFIRMED;
    ev.round_id = 7U;
    ev.round_closed = true;
    ev.danger_area_clear = true;
    ev.estop_released = true;
    t = ec_gateway_inject(g, &ev);
    EXPECT_EQ_U32(EC_STATE_POWER_ON, t.state);

    ev.type = EC_EVENT_POST_PASSED;
    t = ec_gateway_inject(g, &ev);
    EXPECT_EQ_U32(EC_STATE_HOMING, t.state);

    ev.type = EC_EVENT_HOMING_PASSED;
    t = ec_gateway_inject(g, &ev);
    EXPECT_EQ_U32(EC_STATE_PREPARE_BARRIER, t.state);

    ev.type = EC_EVENT_BARRIER_AVOIDANCE_VERIFIED;
    t = ec_gateway_inject(g, &ev);
    EXPECT_EQ_U32(EC_STATE_WAIT_TASK, t.state);
    EXPECT_EQ_U32(EC_CMD_BARRIER_READY, tx_command(g));
}

static void test_boot_and_frame_assembly(void)
{
    ec_gateway_t g;
    ec_proto_frame_t frame;
    ec_transition_t t;
    uint8_t payload[8];

    ec_gateway_init(&g);
    EXPECT_EQ_U32(EC_STATE_FAULT_LOCK, ec_gateway_state(&g));

    TEST_CASE_BEGIN("C-GW-BOOT-001");
    boot_to_wait_task(&g);

    TEST_CASE_BEGIN("C-GW-FRAME-001");
    /* Junk bytes before the frame are ignored. */
    ec_gateway_feed_byte(&g, 0x00U);
    ec_gateway_feed_byte(&g, 0x7FU);
    ec_gateway_feed_byte(&g, 0xA5U);
    ec_gateway_feed_byte(&g, 0x11U); /* 0xA5 then non-0x5A: resync/ignore */
    EXPECT_EQ_U32(EC_STATE_WAIT_TASK, ec_gateway_state(&g));

    /* A valid ITEM_TASK (task_id == round_id == 7) is accepted. */
    frame.version = EC_PROTO_VERSION;
    frame.sender = EC_DEVICE_PI;
    frame.receiver = EC_DEVICE_STM32;
    frame.task_id = 7U;
    frame.frame_seq = 100U;
    frame.command = EC_CMD_ITEM_TASK;
    payload[0] = 0x01U; /* target_seq */
    payload[1] = 0x03U; /* class_id */
    payload[2] = 0x09U; /* image_id */
    payload[3] = 0x00U; /* X high */
    payload[4] = 0x00U; /* X low */
    payload[5] = 0x00U; /* Y high */
    payload[6] = 0x00U; /* Y low */
    payload[7] = 0xFFU; /* grip_angle */
    frame.payload = payload;
    frame.payload_len = (uint16_t)sizeof(payload);
    t = feed_frame(&g, &frame);
    EXPECT_EQ_U32(EC_STATE_VALIDATE_TASK, t.state);
    EXPECT_EQ_U32(0x01U, g.item_target_seq);
    EXPECT_EQ_U32(0x03U, g.item_class_id);
    EXPECT_EQ_U32(0x09U, g.item_image_id);

    TEST_CASE_BEGIN("C-GW-FRAME-002");
    /* A duplicate ITEM_TASK is deduped (RESEND, no re-entry). */
    t = feed_frame(&g, &frame);
    EXPECT_EQ_U32(EC_STATE_VALIDATE_TASK, t.state);
    EXPECT_TRUE((t.actions & EC_ACTION_RESEND_CACHED_RESPONSE) != 0U);
}

static void test_full_cycle(void)
{
    ec_gateway_t g;
    ec_proto_frame_t frame;
    ec_gateway_event_t ev;
    ec_transition_t t;
    uint8_t payload[8];
    ec_proto_display_ack_t ack;
    uint8_t ack_payload[EC_DISPLAY_ACK_PAYLOAD_LEN];

    ec_gateway_init(&g);
    boot_to_wait_task(&g);

    TEST_CASE_BEGIN("C-GW-CYCLE-001");
    frame.version = EC_PROTO_VERSION;
    frame.sender = EC_DEVICE_PI;
    frame.receiver = EC_DEVICE_STM32;
    frame.task_id = 7U;
    frame.frame_seq = 1U;
    frame.command = EC_CMD_ITEM_TASK;
    payload[0] = 0x02U;
    payload[1] = 0x04U;
    payload[2] = 0x05U;
    payload[3] = 0x00U;
    payload[4] = 0x00U;
    payload[5] = 0x00U;
    payload[6] = 0x00U;
    payload[7] = 0xFFU;
    frame.payload = payload;
    frame.payload_len = (uint16_t)sizeof(payload);
    t = feed_frame(&g, &frame);
    EXPECT_EQ_U32(EC_STATE_VALIDATE_TASK, t.state);

    (void)memset(&ev, 0, sizeof(ev));
    ev.type = EC_EVENT_TASK_SAFETY_VALIDATED;
    ev.content_validated = true;
    t = ec_gateway_inject(&g, &ev);
    EXPECT_EQ_U32(EC_STATE_EXECUTING, t.state);
    EXPECT_EQ_U32(EC_ACTION_START_MOTION, t.actions);

    ev.type = EC_EVENT_MOTION_DONE;
    t = ec_gateway_inject(&g, &ev);
    EXPECT_EQ_U32(EC_STATE_WAIT_ITEM_RESULT, t.state);
    EXPECT_EQ_U32(EC_CMD_MOTION_DONE, tx_command(&g));

    TEST_CASE_BEGIN("C-GW-CYCLE-002");
    ev.type = EC_EVENT_ITEM_RESULT_RECORDED;
    ev.result_code = EC_RESULT_SUCCESS;
    t = ec_gateway_inject(&g, &ev);
    EXPECT_EQ_U32(EC_STATE_WAIT_DISPLAY_ACK, t.state);
    EXPECT_EQ_U32(EC_CMD_ITEM_RESULT, tx_command(&g));
    EXPECT_EQ_U32(1U, g.success_count);

    /* Verify the emitted ITEM_RESULT payload is target_seq/result/basis. */
    {
        ec_proto_frame_t out;
        EXPECT_TRUE(ec_proto_decode(ec_gateway_tx_data(&g),
                                    ec_gateway_tx_len(&g), &out));
        EXPECT_EQ_U32(3U, out.payload_len);
        EXPECT_EQ_U32(0x02U, out.payload[0]); /* target_seq */
        EXPECT_EQ_U32(EC_RESULT_SUCCESS, out.payload[1]);
        EXPECT_EQ_U32(EC_RESULT_BASIS_CONTROL_SEQUENCE, out.payload[2]);
    }

    TEST_CASE_BEGIN("C-GW-CYCLE-003");
    ack.target_seq = 0x02U;
    ack.render_result = EC_DISPLAY_ACK_RENDERED;
    ack.display_crc32 = ec_proto_display_content_crc32(
        0x02U, 0x04U, 0x05U, g.success_count, g.item_result_code);
    EXPECT_TRUE(ec_proto_encode_display_ack(&ack, ack_payload,
                                            sizeof(ack_payload)));

    frame.command = EC_CMD_DISPLAY_ACK;
    frame.frame_seq = 2U;
    frame.payload = ack_payload;
    frame.payload_len = (uint16_t)sizeof(ack_payload);
    t = feed_frame(&g, &frame);
    EXPECT_EQ_U32(EC_STATE_PREPARE_BARRIER, t.state);
    EXPECT_TRUE((t.actions & EC_ACTION_PREPARE_BARRIER) != 0U);
}

static void test_display_ack_rejection(void)
{
    ec_gateway_t g;
    ec_proto_frame_t frame;
    ec_gateway_event_t ev;
    ec_transition_t t;
    uint8_t payload[8];
    ec_proto_display_ack_t ack;
    uint8_t ack_payload[EC_DISPLAY_ACK_PAYLOAD_LEN];

    ec_gateway_init(&g);
    boot_to_wait_task(&g);

    frame.version = EC_PROTO_VERSION;
    frame.sender = EC_DEVICE_PI;
    frame.receiver = EC_DEVICE_STM32;
    frame.task_id = 7U;
    frame.frame_seq = 1U;
    frame.command = EC_CMD_ITEM_TASK;
    payload[0] = 0x01U;
    payload[1] = 0x02U;
    payload[2] = 0x03U;
    payload[3] = 0x00U;
    payload[4] = 0x00U;
    payload[5] = 0x00U;
    payload[6] = 0x00U;
    payload[7] = 0xFFU;
    frame.payload = payload;
    frame.payload_len = (uint16_t)sizeof(payload);
    (void)feed_frame(&g, &frame);

    (void)memset(&ev, 0, sizeof(ev));
    ev.type = EC_EVENT_TASK_SAFETY_VALIDATED;
    ev.content_validated = true;
    (void)ec_gateway_inject(&g, &ev);
    ev.type = EC_EVENT_MOTION_DONE;
    (void)ec_gateway_inject(&g, &ev);
    ev.type = EC_EVENT_ITEM_RESULT_RECORDED;
    ev.result_code = EC_RESULT_SUCCESS;
    t = ec_gateway_inject(&g, &ev);
    EXPECT_EQ_U32(EC_STATE_WAIT_DISPLAY_ACK, t.state);

    TEST_CASE_BEGIN("C-GW-ACK-REJ-001");
    /* Wrong target_seq -> rejected, stays WAIT_DISPLAY_ACK. */
    ack.target_seq = 0x09U;
    ack.render_result = EC_DISPLAY_ACK_RENDERED;
    ack.display_crc32 = ec_proto_display_content_crc32(
        0x09U, 0x02U, 0x03U, g.success_count, g.item_result_code);
    (void)ec_proto_encode_display_ack(&ack, ack_payload, sizeof(ack_payload));
    frame.command = EC_CMD_DISPLAY_ACK;
    frame.frame_seq = 2U;
    frame.payload = ack_payload;
    frame.payload_len = (uint16_t)sizeof(ack_payload);
    t = feed_frame(&g, &frame);
    EXPECT_EQ_U32(EC_STATE_WAIT_DISPLAY_ACK, t.state);

    TEST_CASE_BEGIN("C-GW-ACK-REJ-002");
    /* Non-RENDERED render_result -> rejected. */
    ack.target_seq = 0x01U;
    ack.render_result = 0x01U;
    ack.display_crc32 = ec_proto_display_content_crc32(
        0x01U, 0x02U, 0x03U, g.success_count, g.item_result_code);
    (void)ec_proto_encode_display_ack(&ack, ack_payload, sizeof(ack_payload));
    frame.frame_seq = 3U;
    frame.payload = ack_payload;
    t = feed_frame(&g, &frame);
    EXPECT_EQ_U32(EC_STATE_WAIT_DISPLAY_ACK, t.state);

    TEST_CASE_BEGIN("C-GW-ACK-REJ-003");
    /* Wrong CRC32 (bad class_id in content) -> rejected. */
    ack.target_seq = 0x01U;
    ack.render_result = EC_DISPLAY_ACK_RENDERED;
    ack.display_crc32 = ec_proto_display_content_crc32(
        0x01U, 0x0FU, 0x03U, g.success_count, g.item_result_code);
    (void)ec_proto_encode_display_ack(&ack, ack_payload, sizeof(ack_payload));
    frame.frame_seq = 4U;
    frame.payload = ack_payload;
    t = feed_frame(&g, &frame);
    EXPECT_EQ_U32(EC_STATE_WAIT_DISPLAY_ACK, t.state);
}

static void test_crc_rejection_and_round_gate(void)
{
    ec_gateway_t g;
    ec_proto_frame_t frame;
    ec_transition_t t;
    uint8_t payload[8];
    uint8_t buf[EC_GATEWAY_RX_MAX];
    size_t written;
    size_t i;

    ec_gateway_init(&g);
    boot_to_wait_task(&g);

    t.state = EC_STATE_FAULT_LOCK;
    t.fault_reason = EC_FAULT_NONE;
    t.actions = EC_ACTION_NONE;

    TEST_CASE_BEGIN("C-GW-CRC-001");
    /* Corrupt one payload byte: frame-level CRC must fail, no dispatch. */
    frame.version = EC_PROTO_VERSION;
    frame.sender = EC_DEVICE_PI;
    frame.receiver = EC_DEVICE_STM32;
    frame.task_id = 7U;
    frame.frame_seq = 1U;
    frame.command = EC_CMD_ITEM_TASK;
    payload[0] = 0x01U;
    payload[1] = 0x02U;
    payload[2] = 0x03U;
    payload[3] = 0x00U;
    payload[4] = 0x00U;
    payload[5] = 0x00U;
    payload[6] = 0x00U;
    payload[7] = 0xFFU;
    frame.payload = payload;
    frame.payload_len = (uint16_t)sizeof(payload);
    written = ec_proto_encode(&frame, buf, sizeof(buf));
    buf[EC_PROTO_HEADER_LEN] ^= 0xFFU; /* corrupt payload byte */
    for (i = 0U; i < written; ++i) {
        t = ec_gateway_feed_byte(&g, buf[i]);
    }
    EXPECT_EQ_U32(EC_STATE_WAIT_TASK, t.state);

    TEST_CASE_BEGIN("C-GW-ROUND-001");
    /* ITEM_TASK with a mismatched task_id (round gate) is rejected. */
    frame.task_id = 8U;
    frame.frame_seq = 2U;
    payload[0] = 0x01U;
    payload[1] = 0x02U;
    payload[2] = 0x03U;
    t = feed_frame(&g, &frame);
    EXPECT_EQ_U32(EC_STATE_WAIT_TASK, t.state);
    EXPECT_TRUE((t.actions & EC_ACTION_REJECT_NEW_TASK) != 0U);
}

static void test_result_idempotency(void)
{
    ec_gateway_t g;
    ec_proto_frame_t frame;
    ec_gateway_event_t ev;
    ec_transition_t t;
    uint8_t payload[8];

    ec_gateway_init(&g);
    boot_to_wait_task(&g);

    frame.version = EC_PROTO_VERSION;
    frame.sender = EC_DEVICE_PI;
    frame.receiver = EC_DEVICE_STM32;
    frame.task_id = 7U;
    frame.frame_seq = 1U;
    frame.command = EC_CMD_ITEM_TASK;
    payload[0] = 0x01U;
    payload[1] = 0x02U;
    payload[2] = 0x03U;
    payload[3] = 0x00U;
    payload[4] = 0x00U;
    payload[5] = 0x00U;
    payload[6] = 0x00U;
    payload[7] = 0xFFU;
    frame.payload = payload;
    frame.payload_len = (uint16_t)sizeof(payload);
    t = feed_frame(&g, &frame);
    EXPECT_EQ_U32(EC_STATE_VALIDATE_TASK, t.state);

    (void)memset(&ev, 0, sizeof(ev));
    ev.type = EC_EVENT_TASK_SAFETY_VALIDATED;
    ev.content_validated = true;
    (void)ec_gateway_inject(&g, &ev);

    ev.type = EC_EVENT_MOTION_DONE;
    (void)ec_gateway_inject(&g, &ev);

    TEST_CASE_BEGIN("C-GW-RESULT-ONCE-001");
    ev.type = EC_EVENT_ITEM_RESULT_RECORDED;
    ev.result_code = EC_RESULT_SUCCESS;
    t = ec_gateway_inject(&g, &ev);
    EXPECT_EQ_U32(EC_STATE_WAIT_DISPLAY_ACK, t.state);
    EXPECT_EQ_U32(1U, g.success_count);

    TEST_CASE_BEGIN("C-GW-RESULT-ONCE-002");
    /* A duplicate ITEM_RESULT must not double-count (interface-contract 6.1). */
    t = ec_gateway_inject(&g, &ev);
    EXPECT_EQ_U32(EC_STATE_WAIT_DISPLAY_ACK, t.state);
    EXPECT_EQ_U32(1U, g.success_count);
}

void test_protocol_gateway(void)
{
    test_boot_and_frame_assembly();
    test_full_cycle();
    test_display_ack_rejection();
    test_crc_rejection_and_round_gate();
    test_result_idempotency();
}
