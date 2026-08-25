#include "ec_protocol_gateway.h"

#include "ec_crc32.h"

static ec_transition_t none_transition(const ec_gateway_t *g)
{
    ec_transition_t t;

    t.state = g->sm.state;
    t.fault_reason = g->sm.fault_reason;
    t.actions = EC_ACTION_NONE;
    return t;
}

/* Queue one outbound frame. The caller has already cleared tx_len for the
 * current dispatch/inject; this sets it only when the frame is emitted. */
static void emit_frame(ec_gateway_t *g, uint8_t command,
                       const uint8_t *payload, uint16_t payload_len)
{
    ec_proto_frame_t frame;
    size_t written;

    ++g->tx_seq; /* first emitted frame carries seq 1 */

    frame.version = EC_PROTO_VERSION;
    frame.sender = EC_DEVICE_STM32;
    frame.receiver = EC_DEVICE_PI; /* scheme B: STM32 -> Pi */
    frame.task_id = (uint16_t)g->sm.round_id; /* round_id <= UINT16_MAX */
    frame.frame_seq = g->tx_seq;
    frame.command = command;
    frame.payload = payload;
    frame.payload_len = payload_len;

    written = ec_proto_encode(&frame, g->tx_buf, EC_GATEWAY_TX_MAX);
    g->tx_len = (written != 0U) ? written : 0U;
}

/* Consume an event, then materialise any EMIT_* actions as an outbound frame.
 * Only the first EMIT action wins; the current state machine never emits two
 * at once. */
static ec_transition_t consume_and_emit(ec_gateway_t *g, const ec_event_t *event)
{
    ec_transition_t t = ec_sm_consume(&g->sm, event);

    if ((t.actions & EC_ACTION_EMIT_BARRIER_READY) != 0U) {
        emit_frame(g, EC_CMD_BARRIER_READY, NULL, 0U);
    } else if ((t.actions & EC_ACTION_EMIT_MOTION_DONE) != 0U) {
        emit_frame(g, EC_CMD_MOTION_DONE, NULL, 0U);
    } else if ((t.actions & EC_ACTION_EMIT_ITEM_RESULT) != 0U) {
        uint8_t payload[3];

        payload[0] = g->item_target_seq;
        payload[1] = g->item_result_code;
        payload[2] = EC_RESULT_BASIS_CONTROL_SEQUENCE;
        emit_frame(g, EC_CMD_ITEM_RESULT, payload, sizeof(payload));
    }

    return t;
}

static ec_transition_t handle_item_task(ec_gateway_t *g,
                                        const ec_proto_frame_t *frame)
{
    ec_proto_item_task_t item;
    ec_event_t event;
    ec_transition_t t;

    if (!ec_proto_decode_item_task(frame->payload, frame->payload_len, &item)) {
        return none_transition(g);
    }

    event.type = EC_EVENT_ITEM_TASK_ACCEPTED;
    event.identity.task_id = (uint32_t)frame->task_id;
    event.identity.frame_seq = (uint32_t)frame->frame_seq;
    /* Fingerprint distinguishes "same task_id + frame_seq, different payload"
     * (interface-contract sec. 5.2 conflict). CRC32 of the payload is a cheap,
     * deterministic fingerprint. */
    event.identity.payload_fingerprint =
        ec_crc32_iso_hdlc(frame->payload, frame->payload_len);
    event.round_id = (uint32_t)frame->task_id;
    event.round_closed = false;
    event.danger_area_clear = false;
    event.estop_released = false;
    event.content_validated = false;

    t = consume_and_emit(g, &event);

    /* Latch the item context only if the state machine actually accepted the
     * item (dedup NEW + WAIT_TASK -> VALIDATE_TASK). */
    if (t.state == EC_STATE_VALIDATE_TASK) {
        g->item_target_seq = item.target_seq;
        g->item_class_id = item.class_id;
        g->item_image_id = item.image_id;
    }
    return t;
}

static ec_transition_t handle_display_ack(ec_gateway_t *g,
                                          const ec_proto_frame_t *frame)
{
    ec_proto_display_ack_t ack;
    uint32_t expected_crc;
    ec_event_t event;
    bool valid;

    if (!ec_proto_decode_display_ack(frame->payload, frame->payload_len, &ack)) {
        return none_transition(g);
    }

    /* interface-contract sec. 5.5: target_seq must match the current item;
     * render_result must be RENDERED; the display-content CRC must match the
     * expected bytes (target_seq, class_id, image_id, success_count, result_code);
     * and the frame task_id must match the current round. */
    expected_crc = ec_proto_display_content_crc32(
        ack.target_seq, g->item_class_id, g->item_image_id, g->success_count,
        g->item_result_code);

    valid = (ack.target_seq == g->item_target_seq) &&
            (ack.render_result == EC_DISPLAY_ACK_RENDERED) &&
            (ack.display_crc32 == expected_crc) &&
            ((uint32_t)frame->task_id == g->sm.round_id);

    if (!valid) {
        return none_transition(g);
    }

    event.type = EC_EVENT_DISPLAY_ACK_VALIDATED;
    event.identity = g->sm.current_item; /* must match current_item */
    event.round_id = g->sm.round_id;
    event.round_closed = false;
    event.danger_area_clear = false;
    event.estop_released = false;
    event.content_validated = true;

    return consume_and_emit(g, &event);
}

static ec_transition_t dispatch_frame(ec_gateway_t *g, const uint8_t *buf,
                                      size_t len)
{
    ec_proto_frame_t frame;

    if (!ec_proto_decode(buf, len, &frame)) {
        return none_transition(g);
    }

    if (frame.receiver != EC_DEVICE_STM32) {
        return none_transition(g);
    }

    switch (frame.command) {
    case EC_CMD_ITEM_TASK:
        return handle_item_task(g, &frame);
    case EC_CMD_DISPLAY_ACK:
        return handle_display_ack(g, &frame);
    default:
        /* HEARTBEAT / HEARTBEAT_ACK / DEVICE_READY / ACK / NACK / ESTOP and
         * the not-yet-frozen commands are out of scope for this slice. */
        return none_transition(g);
    }
}

void ec_gateway_init(ec_gateway_t *g)
{
    if (g == NULL) return;

    (void)ec_dedup_init(&g->dedup, g->dedup_storage,
                        EC_GATEWAY_DEDUP_CAPACITY);
    ec_sm_init(&g->sm, &g->dedup);

    g->success_count = 0U;
    g->item_target_seq = 0U;
    g->item_class_id = 0U;
    g->item_image_id = 0U;
    g->item_result_code = EC_RESULT_UNKNOWN;
    g->tx_seq = 0U;
    g->rx_len = 0U;
    g->tx_len = 0U;
}

ec_transition_t ec_gateway_feed_byte(ec_gateway_t *g, uint8_t byte)
{
    ec_transition_t none;

    if (g == NULL) {
        none.state = EC_STATE_FAULT_LOCK;
        none.fault_reason = EC_FAULT_RESTART_CONTEXT_UNPROVEN;
        none.actions = EC_ACTION_NONE;
        return none;
    }

    g->tx_len = 0U;
    none = none_transition(g);

    if (g->rx_len == 0U) {
        if (byte != EC_PROTO_HEADER_0) return none;
        g->rx_buf[0] = byte;
        g->rx_len = 1U;
        return none;
    }

    if (g->rx_len == 1U) {
        if (byte != EC_PROTO_HEADER_1) {
            /* 0xA5 not followed by 0x5A: resync on a fresh 0xA5, else reset. */
            if (byte == EC_PROTO_HEADER_0) {
                g->rx_len = 1U;
            } else {
                g->rx_len = 0U;
            }
            return none;
        }
        g->rx_buf[1] = byte;
        g->rx_len = 2U;
        return none;
    }

    if (g->rx_len < EC_PROTO_HEADER_LEN) {
        g->rx_buf[g->rx_len] = byte;
        ++g->rx_len;
        return none;
    }

    /* Header complete (rx_len == EC_PROTO_HEADER_LEN). Read data_len, then
     * collect payload + CRC until the frame is complete. */
    {
        uint16_t data_len =
            (uint16_t)(((uint16_t)g->rx_buf[10] << 8U) | (uint16_t)g->rx_buf[11]);
        size_t total =
            EC_PROTO_HEADER_LEN + (size_t)data_len + EC_PROTO_CRC_LEN;

        if (total > EC_GATEWAY_RX_MAX) {
            g->rx_len = 0U; /* oversized frame: drop */
            return none;
        }

        g->rx_buf[g->rx_len] = byte;
        ++g->rx_len;

        if (g->rx_len >= total) {
            ec_transition_t t = dispatch_frame(g, g->rx_buf, total);
            g->rx_len = 0U;
            return t;
        }
        return none;
    }
}

ec_transition_t ec_gateway_inject(ec_gateway_t *g,
                                  const ec_gateway_event_t *event)
{
    ec_event_t e;
    ec_state_t pre_state;
    ec_transition_t transition;
    ec_transition_t none;

    if (g == NULL) {
        none.state = EC_STATE_FAULT_LOCK;
        none.fault_reason = EC_FAULT_RESTART_CONTEXT_UNPROVEN;
        none.actions = EC_ACTION_NONE;
        return none;
    }

    g->tx_len = 0U;

    if (event == NULL) {
        return none_transition(g);
    }

    e.type = event->type;
    e.identity = g->sm.current_item;
    e.round_id = g->sm.round_id;
    e.round_closed = event->round_closed;
    e.danger_area_clear = event->danger_area_clear;
    e.estop_released = event->estop_released;
    e.content_validated = event->content_validated;

    if (event->type == EC_EVENT_MANUAL_NEW_ROUND_CONFIRMED) {
        e.round_id = event->round_id;
    }

    pre_state = g->sm.state;

    /* The EMIT_ITEM_RESULT action must read the result code before the state
     * machine consumes the event. Latch it only while the machine can still
     * accept this item's result (WAIT_ITEM_RESULT + current item present). */
    if (event->type == EC_EVENT_ITEM_RESULT_RECORDED &&
        pre_state == EC_STATE_WAIT_ITEM_RESULT &&
        g->sm.has_current_item) {
        g->item_result_code = event->result_code;
    }

    transition = consume_and_emit(g, &e);

    /* interface-contract sec. 6.1: success_count is 0..255, increments only
     * on the first valid SUCCESS result, and must not wrap 255 -> 0. Increment
     * only when the state machine actually committed WAIT_ITEM_RESULT ->
     * WAIT_DISPLAY_ACK, so a duplicate or replayed ITEM_RESULT is idempotent. */
    if (event->type == EC_EVENT_ITEM_RESULT_RECORDED &&
        pre_state == EC_STATE_WAIT_ITEM_RESULT &&
        transition.state == EC_STATE_WAIT_DISPLAY_ACK &&
        event->result_code == EC_RESULT_SUCCESS) {
        if (g->success_count != UINT8_MAX) {
            ++g->success_count;
        }
    }

    return transition;
}

const uint8_t *ec_gateway_tx_data(const ec_gateway_t *g)
{
    return (g != NULL) ? g->tx_buf : NULL;
}

size_t ec_gateway_tx_len(const ec_gateway_t *g)
{
    return (g != NULL) ? g->tx_len : 0U;
}

ec_state_t ec_gateway_state(const ec_gateway_t *g)
{
    return (g != NULL) ? g->sm.state : EC_STATE_FAULT_LOCK;
}

bool ec_gateway_rx_active(const ec_gateway_t *g)
{
    return (g != NULL) && (g->rx_len != 0U);
}
