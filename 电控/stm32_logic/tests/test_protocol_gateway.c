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

/* Build and feed a standard PI-sourced ITEM_TASK frame (X = Y = 0). */
static ec_transition_t feed_item_task(ec_gateway_t *g, uint16_t task_id,
                                      uint16_t frame_seq, uint8_t target_seq,
                                      uint8_t class_id, uint8_t image_id)
{
    ec_proto_frame_t frame;
    uint8_t payload[EC_PROTO_ITEM_TASK_PAYLOAD_LEN];

    (void)memset(&frame, 0, sizeof(frame));
    frame.version = EC_PROTO_VERSION;
    frame.sender = EC_DEVICE_PI;
    frame.receiver = EC_DEVICE_STM32;
    frame.task_id = task_id;
    frame.frame_seq = frame_seq;
    frame.command = EC_CMD_ITEM_TASK;
    payload[0] = target_seq;
    payload[1] = class_id;
    payload[2] = image_id;
    payload[3] = 0x00U;
    payload[4] = 0x00U;
    payload[5] = 0x00U;
    payload[6] = 0x00U;
    payload[7] = EC_PROTO_ITEM_TASK_ANGLE_NONE;
    frame.payload = payload;
    frame.payload_len = (uint16_t)sizeof(payload);
    return feed_frame(g, &frame);
}

/* Drive the current item through safety-validated / motion-done / item-result /
 * valid DISPLAY_ACK / barrier-verified, back to WAIT_TASK. */
static void complete_item_cycle(ec_gateway_t *g)
{
    ec_gateway_event_t ev;
    ec_proto_frame_t frame;
    ec_proto_display_ack_t ack;
    uint8_t ack_payload[EC_DISPLAY_ACK_PAYLOAD_LEN];

    (void)memset(&ev, 0, sizeof(ev));
    ev.type = EC_EVENT_TASK_SAFETY_VALIDATED;
    ev.content_validated = true;
    (void)ec_gateway_inject(g, &ev);

    ev.type = EC_EVENT_MOTION_DONE;
    (void)ec_gateway_inject(g, &ev);

    ev.type = EC_EVENT_ITEM_RESULT_RECORDED;
    ev.result_code = EC_RESULT_SUCCESS;
    (void)ec_gateway_inject(g, &ev);

    /* Valid DISPLAY_ACK for the current item (content CRC rebuilt from the
     * latched item context + success_count + result code). */
    ack.target_seq = g->item_target_seq;
    ack.render_result = EC_DISPLAY_ACK_RENDERED;
    ack.display_crc32 = ec_proto_display_content_crc32(
        g->item_target_seq, g->item_class_id, g->item_image_id,
        g->success_count, g->item_result_code);
    (void)ec_proto_encode_display_ack(&ack, ack_payload, sizeof(ack_payload));

    (void)memset(&frame, 0, sizeof(frame));
    frame.version = EC_PROTO_VERSION;
    frame.sender = EC_DEVICE_PI;
    frame.receiver = EC_DEVICE_STM32;
    frame.task_id = (uint16_t)g->sm.round_id;
    frame.frame_seq = 2U;
    frame.command = EC_CMD_DISPLAY_ACK;
    frame.payload = ack_payload;
    frame.payload_len = (uint16_t)sizeof(ack_payload);
    (void)feed_frame(g, &frame);

    ev.type = EC_EVENT_BARRIER_AVOIDANCE_VERIFIED;
    (void)ec_gateway_inject(g, &ev);
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

static void test_new_round_guards(void)
{
    ec_gateway_t g;
    ec_gateway_event_t ev;
    ec_transition_t t;
    ec_proto_frame_t frame;
    uint8_t payload[8];

    ec_gateway_init(&g);
    boot_to_wait_task(&g);

    /* Drive one successful item so counters and item context are non-zero. */
    frame.version = EC_PROTO_VERSION;
    frame.sender = EC_DEVICE_PI;
    frame.receiver = EC_DEVICE_STM32;
    frame.task_id = 7U;
    frame.frame_seq = 1U;
    frame.command = EC_CMD_ITEM_TASK;
    payload[0] = 0x01U; /* target_seq */
    payload[1] = 0x02U; /* class_id */
    payload[2] = 0x03U; /* image_id */
    payload[3] = 0x00U;
    payload[4] = 0x00U;
    payload[5] = 0x00U;
    payload[6] = 0x00U;
    payload[7] = 0xFFU; /* grip_angle */
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
    ev.type = EC_EVENT_ITEM_RESULT_RECORDED;
    ev.result_code = EC_RESULT_SUCCESS;
    t = ec_gateway_inject(&g, &ev);
    EXPECT_EQ_U32(EC_STATE_WAIT_DISPLAY_ACK, t.state);
    EXPECT_EQ_U32(1U, g.success_count);
    EXPECT_EQ_U32(0x01U, g.item_target_seq);

    TEST_CASE_BEGIN("C-GW-ROUND-002");
    /* A confirmation the machine rejects (same round_id while not in
     * FAULT_LOCK) must NOT clear counters or item context. */
    (void)memset(&ev, 0, sizeof(ev));
    ev.type = EC_EVENT_MANUAL_NEW_ROUND_CONFIRMED;
    ev.round_id = 7U; /* not a new round id */
    ev.round_closed = true;
    ev.danger_area_clear = true;
    ev.estop_released = true;
    t = ec_gateway_inject(&g, &ev);
    EXPECT_EQ_U32(EC_STATE_WAIT_DISPLAY_ACK, t.state);
    EXPECT_EQ_U32(1U, g.success_count);
    EXPECT_EQ_U32(0x01U, g.item_target_seq);

    TEST_CASE_BEGIN("C-GW-ROUND-003");
    /* round_id beyond UINT16_MAX would be truncated on the wire; reject it
     * before any mutation. */
    ev.round_id = UINT32_C(0x10000);
    t = ec_gateway_inject(&g, &ev);
    EXPECT_EQ_U32(EC_STATE_WAIT_DISPLAY_ACK, t.state);
    EXPECT_EQ_U32(1U, g.success_count);
    EXPECT_EQ_U32(0x01U, g.item_target_seq);

    TEST_CASE_BEGIN("C-GW-ROUND-004");
    /* A verified new round from FAULT_LOCK clears counters and item context. */
    (void)memset(&ev, 0, sizeof(ev));
    ev.type = EC_EVENT_EMERGENCY_STOP;
    (void)ec_gateway_inject(&g, &ev);
    EXPECT_EQ_U32(EC_STATE_FAULT_LOCK, ec_gateway_state(&g));

    (void)memset(&ev, 0, sizeof(ev));
    ev.type = EC_EVENT_MANUAL_NEW_ROUND_CONFIRMED;
    ev.round_id = 8U;
    ev.round_closed = true;
    ev.danger_area_clear = true;
    ev.estop_released = true;
    t = ec_gateway_inject(&g, &ev);
    EXPECT_EQ_U32(EC_STATE_POWER_ON, t.state);
    EXPECT_EQ_U32(0U, g.success_count);
    EXPECT_EQ_U32(0U, g.item_target_seq);
    EXPECT_EQ_U32(EC_RESULT_UNKNOWN, g.item_result_code);
}

static void test_response_frames(void)
{
    ec_gateway_t g;
    ec_transition_t t;
    ec_proto_frame_t out;
    uint8_t ack_reason = 0U;
    uint8_t ack_target = 0U;
    uint8_t first_tx[EC_GATEWAY_TX_MAX];
    size_t first_len;
    uint16_t seq_after_accept;

    ec_gateway_init(&g);
    boot_to_wait_task(&g);

    TEST_CASE_BEGIN("C-GW-RESP-001");
    /* Fresh ITEM_TASK -> ACK(ACCEPTED, item.target_seq) is emitted and the
     * exact response bytes are cached (proposal sec. 3.4 / E-4). */
    t = feed_item_task(&g, 7U, 100U, 0x01U, 0x03U, 0x09U);
    EXPECT_EQ_U32(EC_STATE_VALIDATE_TASK, t.state);
    EXPECT_EQ_U8(EC_CMD_ACK, tx_command(&g));
    EXPECT_TRUE(ec_proto_decode(ec_gateway_tx_data(&g),
                                ec_gateway_tx_len(&g), &out));
    EXPECT_EQ_U32(EC_ACK_PAYLOAD_LEN, out.payload_len);
    EXPECT_TRUE(ec_proto_decode_ack(out.payload, out.payload_len,
                                    &ack_reason, &ack_target));
    EXPECT_EQ_U8(EC_ACK_REASON_ACCEPTED, ack_reason);
    EXPECT_EQ_U8(0x01U, ack_target);
    EXPECT_EQ_U32(2U, g.tx_seq); /* BARRIER_READY(1) + ACK(2) */
    first_len = ec_gateway_tx_len(&g);
    EXPECT_TRUE(first_len <= sizeof(first_tx));
    (void)memcpy(first_tx, ec_gateway_tx_data(&g), first_len);
    seq_after_accept = g.tx_seq;

    TEST_CASE_BEGIN("C-GW-RESP-002");
    /* Duplicate ITEM_TASK (same task_id + frame_seq + payload) -> the cached
     * ACK(ACCEPTED) is replayed byte-for-byte and tx_seq is NOT incremented
     * (proposal sec. 3.2 rule 2 / E-5). */
    t = feed_item_task(&g, 7U, 100U, 0x01U, 0x03U, 0x09U);
    EXPECT_EQ_U32(EC_STATE_VALIDATE_TASK, t.state);
    EXPECT_TRUE((t.actions & EC_ACTION_RESEND_CACHED_RESPONSE) != 0U);
    EXPECT_EQ_U8(EC_CMD_ACK, tx_command(&g));
    EXPECT_EQ_U32(seq_after_accept, g.tx_seq);
    EXPECT_EQ_U32(first_len, ec_gateway_tx_len(&g));
    EXPECT_TRUE(memcmp(first_tx, ec_gateway_tx_data(&g), first_len) == 0);
}

static void test_stale_and_order_gate(void)
{
    ec_gateway_t g;
    ec_transition_t t;
    ec_proto_frame_t out;
    uint8_t nack_reason = 0U;
    uint8_t nack_target = 0U;

    ec_gateway_init(&g);
    boot_to_wait_task(&g);

    /* Accept item seq 100, then complete the cycle back to WAIT_TASK so the
     * order-gate watermark (last_accepted_frame_seq == 100) is set. */
    t = feed_item_task(&g, 7U, 100U, 0x01U, 0x03U, 0x09U);
    EXPECT_EQ_U32(EC_STATE_VALIDATE_TASK, t.state);
    complete_item_cycle(&g);
    EXPECT_EQ_U32(EC_STATE_WAIT_TASK, ec_gateway_state(&g));

    TEST_CASE_BEGIN("C-GW-ORDER-001");
    /* Stale frame: seq 50 <= last accepted 100 and never seen -> the order
     * gate rejects it with NACK. Round matches, so the reason is
     * SINGLE_TASK_ONLY (proposal sec. 3.4 / 3.6 item 4). */
    t = feed_item_task(&g, 7U, 50U, 0x02U, 0x04U, 0x0AU);
    EXPECT_EQ_U32(EC_STATE_WAIT_TASK, t.state);
    EXPECT_TRUE((t.actions & EC_ACTION_REJECT_NEW_TASK) != 0U);
    EXPECT_EQ_U8(EC_CMD_NACK, tx_command(&g));
    EXPECT_TRUE(ec_proto_decode(ec_gateway_tx_data(&g),
                                ec_gateway_tx_len(&g), &out));
    EXPECT_TRUE(ec_proto_decode_nack(out.payload, out.payload_len,
                                     &nack_reason, &nack_target));
    EXPECT_EQ_U8(EC_NACK_SINGLE_TASK_ONLY, nack_reason);
    EXPECT_EQ_U8(0xFFU, nack_target);

    TEST_CASE_BEGIN("C-GW-ORDER-002");
    /* Re-send of the same stale frame: dedup now holds it (recorded by the
     * first observe) -> RESEND, but the response cache has no entry for it
     * (it was rejected, never answered) -> fail-closed, nothing emitted. */
    t = feed_item_task(&g, 7U, 50U, 0x02U, 0x04U, 0x0AU);
    EXPECT_EQ_U32(EC_STATE_WAIT_TASK, t.state);
    EXPECT_TRUE((t.actions & EC_ACTION_RESEND_CACHED_RESPONSE) != 0U);
    EXPECT_EQ_U32(0U, ec_gateway_tx_len(&g));
    EXPECT_EQ_U8(0xFFU, tx_command(&g));
}

static void test_display_ack_resend(void)
{
    ec_gateway_t g;
    ec_transition_t t;
    ec_gateway_event_t ev;
    ec_proto_frame_t frame;
    ec_proto_display_ack_t ack;
    uint8_t ack_payload[EC_DISPLAY_ACK_PAYLOAD_LEN];
    ec_proto_frame_t out;
    uint8_t ack_reason = 0U;
    uint8_t ack_target = 0U;
    uint8_t first_tx[EC_GATEWAY_TX_MAX];
    size_t first_len;
    uint16_t seq_after_consume;

    ec_gateway_init(&g);
    boot_to_wait_task(&g);

    /* Accept item and drive to WAIT_DISPLAY_ACK. */
    t = feed_item_task(&g, 7U, 1U, 0x02U, 0x04U, 0x05U);
    EXPECT_EQ_U32(EC_STATE_VALIDATE_TASK, t.state);

    (void)memset(&ev, 0, sizeof(ev));
    ev.type = EC_EVENT_TASK_SAFETY_VALIDATED;
    ev.content_validated = true;
    (void)ec_gateway_inject(&g, &ev);
    ev.type = EC_EVENT_MOTION_DONE;
    (void)ec_gateway_inject(&g, &ev);
    ev.type = EC_EVENT_ITEM_RESULT_RECORDED;
    ev.result_code = EC_RESULT_SUCCESS;
    (void)ec_gateway_inject(&g, &ev);
    EXPECT_EQ_U32(EC_STATE_WAIT_DISPLAY_ACK, ec_gateway_state(&g));

    /* Valid DISPLAY_ACK for the current item. */
    ack.target_seq = 0x02U;
    ack.render_result = EC_DISPLAY_ACK_RENDERED;
    ack.display_crc32 = ec_proto_display_content_crc32(
        0x02U, 0x04U, 0x05U, g.success_count, g.item_result_code);
    EXPECT_TRUE(ec_proto_encode_display_ack(&ack, ack_payload,
                                            sizeof(ack_payload)));

    (void)memset(&frame, 0, sizeof(frame));
    frame.version = EC_PROTO_VERSION;
    frame.sender = EC_DEVICE_PI;
    frame.receiver = EC_DEVICE_STM32;
    frame.task_id = 7U;
    frame.frame_seq = 2U;
    frame.command = EC_CMD_DISPLAY_ACK;
    frame.payload = ack_payload;
    frame.payload_len = (uint16_t)sizeof(ack_payload);

    TEST_CASE_BEGIN("C-GW-DACK-REPLAY-001");
    /* First valid consumption -> ACK(ACK_CONSUMED, ack.target_seq) emitted and
     * cached; PREPARE_BARRIER still set. */
    t = feed_frame(&g, &frame);
    EXPECT_EQ_U32(EC_STATE_PREPARE_BARRIER, t.state);
    EXPECT_TRUE((t.actions & EC_ACTION_PREPARE_BARRIER) != 0U);
    EXPECT_EQ_U8(EC_CMD_ACK, tx_command(&g));
    EXPECT_TRUE(ec_proto_decode(ec_gateway_tx_data(&g),
                                ec_gateway_tx_len(&g), &out));
    EXPECT_TRUE(ec_proto_decode_ack(out.payload, out.payload_len,
                                    &ack_reason, &ack_target));
    EXPECT_EQ_U8(EC_ACK_REASON_ACK_CONSUMED, ack_reason);
    EXPECT_EQ_U8(0x02U, ack_target);
    first_len = ec_gateway_tx_len(&g);
    EXPECT_TRUE(first_len <= sizeof(first_tx));
    (void)memcpy(first_tx, ec_gateway_tx_data(&g), first_len);
    seq_after_consume = g.tx_seq;

    TEST_CASE_BEGIN("C-GW-DACK-REPLAY-002");
    /* Repeat DISPLAY_ACK -> the cached ACK(ACK_CONSUMED) is replayed
     * byte-for-byte without incrementing tx_seq; no second consumption, no
     * re-release (proposal sec. 3.3.4 / 3.5 idempotency). */
    t = feed_frame(&g, &frame);
    EXPECT_EQ_U32(EC_STATE_PREPARE_BARRIER, t.state);
    EXPECT_TRUE((t.actions & EC_ACTION_RESEND_CACHED_RESPONSE) != 0U);
    EXPECT_EQ_U8(EC_CMD_ACK, tx_command(&g));
    EXPECT_EQ_U32(seq_after_consume, g.tx_seq);
    EXPECT_EQ_U32(first_len, ec_gateway_tx_len(&g));
    EXPECT_TRUE(memcmp(first_tx, ec_gateway_tx_data(&g), first_len) == 0);
}

static void test_conflict_at_gateway(void)
{
    ec_gateway_t g;
    ec_transition_t t;

    ec_gateway_init(&g);
    boot_to_wait_task(&g);

    /* Accept identity (7, 100) with payload A, then return to WAIT_TASK. */
    t = feed_item_task(&g, 7U, 100U, 0x01U, 0x03U, 0x09U);
    EXPECT_EQ_U32(EC_STATE_VALIDATE_TASK, t.state);
    complete_item_cycle(&g);
    EXPECT_EQ_U32(EC_STATE_WAIT_TASK, ec_gateway_state(&g));

    TEST_CASE_BEGIN("C-GW-CONFLICT-001");
    /* Same (task_id, frame_seq) with a DIFFERENT payload -> dedup CONFLICT ->
     * FAULT_LOCK (interface-contract sec. 5.2); the response cache must not
     * mask the conflict. */
    t = feed_item_task(&g, 7U, 100U, 0x01U, 0x04U, 0x09U); /* class differs */
    EXPECT_EQ_U32(EC_STATE_FAULT_LOCK, t.state);
    EXPECT_EQ_U32(EC_FAULT_DEDUP_CONFLICT, t.fault_reason);
    EXPECT_TRUE((t.actions & EC_ACTION_SAFE_LOCK) != 0U);
}

static void test_cache_cleared_on_new_round(void)
{
    ec_gateway_t g;
    ec_gateway_event_t ev;
    ec_transition_t t;
    ec_proto_frame_t out;
    uint8_t ack_reason = 0U;
    uint8_t ack_target = 0U;
    uint8_t nack_reason = 0U;
    uint8_t nack_target = 0U;
    uint16_t seq_before;

    ec_gateway_init(&g);
    boot_to_wait_task(&g);

    /* Round 7: accept (7, 100) -> ACK(ACCEPTED) cached. */
    t = feed_item_task(&g, 7U, 100U, 0x01U, 0x03U, 0x09U);
    EXPECT_EQ_U32(EC_STATE_VALIDATE_TASK, t.state);

    TEST_CASE_BEGIN("C-GW-CACHE-CLEAR-001");
    /* Fault, then a verified new round (8): dedup + response cache + order
     * watermark are all cleared together (proposal sec. 3.3.3 / E-7). */
    (void)memset(&ev, 0, sizeof(ev));
    ev.type = EC_EVENT_EMERGENCY_STOP;
    (void)ec_gateway_inject(&g, &ev);
    EXPECT_EQ_U32(EC_STATE_FAULT_LOCK, ec_gateway_state(&g));

    (void)memset(&ev, 0, sizeof(ev));
    ev.type = EC_EVENT_MANUAL_NEW_ROUND_CONFIRMED;
    ev.round_id = 8U;
    ev.round_closed = true;
    ev.danger_area_clear = true;
    ev.estop_released = true;
    t = ec_gateway_inject(&g, &ev);
    EXPECT_EQ_U32(EC_STATE_POWER_ON, t.state);

    ev.type = EC_EVENT_POST_PASSED;
    (void)ec_gateway_inject(&g, &ev);
    ev.type = EC_EVENT_HOMING_PASSED;
    (void)ec_gateway_inject(&g, &ev);
    ev.type = EC_EVENT_BARRIER_AVOIDANCE_VERIFIED;
    (void)ec_gateway_inject(&g, &ev);
    EXPECT_EQ_U32(EC_STATE_WAIT_TASK, ec_gateway_state(&g));

    TEST_CASE_BEGIN("C-GW-CACHE-CLEAR-002");
    /* Same seq as the old round, but the new round's task_id: dedup is
     * cleared, so it is NEW -> a fresh ACK(ACCEPTED) is emitted (tx_seq
     * increments), NOT a replay of the old cached ACK. */
    seq_before = g.tx_seq;
    t = feed_item_task(&g, 8U, 100U, 0x01U, 0x03U, 0x09U);
    EXPECT_EQ_U32(EC_STATE_VALIDATE_TASK, t.state);
    EXPECT_EQ_U8(EC_CMD_ACK, tx_command(&g));
    EXPECT_TRUE(ec_proto_decode(ec_gateway_tx_data(&g),
                                ec_gateway_tx_len(&g), &out));
    EXPECT_TRUE(ec_proto_decode_ack(out.payload, out.payload_len,
                                    &ack_reason, &ack_target));
    EXPECT_EQ_U8(EC_ACK_REASON_ACCEPTED, ack_reason);
    EXPECT_EQ_U8(0x01U, ack_target);
    EXPECT_EQ_U32(seq_before + 1U, g.tx_seq); /* fresh emit, not a replay */

    TEST_CASE_BEGIN("C-GW-CACHE-CLEAR-003");
    /* Old task_id (7) after the new round: the round gate rejects with
     * NACK(WRONG_ROUND) - the stale cached ACK is never replayed. */
    t = feed_item_task(&g, 7U, 100U, 0x01U, 0x03U, 0x09U);
    EXPECT_EQ_U32(EC_STATE_VALIDATE_TASK, t.state); /* round-8 item ongoing */
    EXPECT_TRUE((t.actions & EC_ACTION_REJECT_NEW_TASK) != 0U);
    EXPECT_EQ_U8(EC_CMD_NACK, tx_command(&g));
    EXPECT_TRUE(ec_proto_decode(ec_gateway_tx_data(&g),
                                ec_gateway_tx_len(&g), &out));
    EXPECT_TRUE(ec_proto_decode_nack(out.payload, out.payload_len,
                                     &nack_reason, &nack_target));
    EXPECT_EQ_U8(EC_NACK_WRONG_ROUND, nack_reason);
    EXPECT_EQ_U8(0xFFU, nack_target);
}

void test_protocol_gateway(void)
{
    test_boot_and_frame_assembly();
    test_full_cycle();
    test_display_ack_rejection();
    test_crc_rejection_and_round_gate();
    test_result_idempotency();
    test_new_round_guards();
    test_response_frames();
    test_stale_and_order_gate();
    test_display_ack_resend();
    test_conflict_at_gateway();
    test_cache_cleared_on_new_round();
}
