#include "ec_protocol_gateway.h"

#include "ec_crc32.h"

#include <string.h>

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

/* Queue an ACK frame (proposal sec. 3.3.1: reason(1) + target_seq(1)). */
static void emit_ack(ec_gateway_t *g, uint8_t reason, uint8_t target_seq)
{
    uint8_t payload[EC_ACK_PAYLOAD_LEN];

    payload[0] = reason;
    payload[1] = target_seq;
    emit_frame(g, EC_CMD_ACK, payload, sizeof(payload));
}

/* Queue a NACK frame (proposal sec. 3.3.2: reason(1) + target_seq(1)). */
static void emit_nack(ec_gateway_t *g, uint8_t reason, uint8_t target_seq)
{
    uint8_t payload[EC_NACK_PAYLOAD_LEN];

    payload[0] = reason;
    payload[1] = target_seq;
    emit_frame(g, EC_CMD_NACK, payload, sizeof(payload));
}

/* Consume an event, then materialise any EMIT_* actions as an outbound frame.
 * Only the first matching action wins; the current state machine never emits
 * two at once. Existing EMIT_* (BARRIER_READY / MOTION_DONE / ITEM_RESULT)
 * stay first; the ACK/NACK/RESEND/REJECT branches follow (proposal sec. 3.4).
 * A RESEND replay writes the cached bytes directly and does NOT increment
 * tx_seq (E-5); a cache miss fails closed (nothing emitted, tx_len stays 0). */
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
    } else if ((t.actions & EC_ACTION_ACK_ITEM_ACCEPTED) != 0U) {
        /* First acceptance of this item identity: ACK(ACCEPTED), then cache
         * the exact response bytes for later RESEND replays. */
        emit_ack(g, EC_ACK_REASON_ACCEPTED, g->item_target_seq);
        ec_gateway_resp_cache_store(g, event->identity, g->tx_buf,
                                    (uint16_t)g->tx_len);
    } else if ((t.actions & EC_ACTION_ACK_DISPLAY_CONSUMED) != 0U) {
        /* First valid DISPLAY_ACK consumption: ACK(ACK_CONSUMED), then cache.
         * ack.target_seq == item_target_seq (content-validated upstream). */
        emit_ack(g, EC_ACK_REASON_ACK_CONSUMED, g->item_target_seq);
        ec_gateway_resp_cache_store(g, event->identity, g->tx_buf,
                                    (uint16_t)g->tx_len);
    } else if ((t.actions & EC_ACTION_RESEND_CACHED_RESPONSE) != 0U) {
        const uint8_t *cached = NULL;
        uint16_t cached_len = 0U;

        if (ec_gateway_resp_cache_lookup(g, event->identity, &cached,
                                         &cached_len)) {
            (void)memcpy(g->tx_buf, cached, cached_len);
            g->tx_len = cached_len;
        }
        /* Miss: fail-closed - nothing emitted, nothing executed. */
    } else if ((t.actions & EC_ACTION_REJECT_NEW_TASK) != 0U) {
        uint8_t reason;

        reason = (event->round_id != g->sm.round_id)
                     ? EC_NACK_WRONG_ROUND
                     : EC_NACK_SINGLE_TASK_ONLY;
        emit_nack(g, reason, UINT8_C(0xFF));
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

    /* P1-FIX: Verify frame sender is PI (scheme B: Pi -> STM32).
     * Reject frames from wrong sender to prevent replay/spoofing. */
    if (frame->sender != EC_DEVICE_PI) {
        return none_transition(g);
    }

    /* P1-FIX: Reject new tasks when success_count is at 255 and state is
     * WAIT_TASK (the only state that accepts new items). The counter cannot
     * represent 256, so a new potentially-successful task would overflow.
     * Proposal sec. 3.4: explicit NACK replaces the former silent drop so the
     * Pi learns the task was rejected instead of timing out. */
    if (g->sm.state == EC_STATE_WAIT_TASK && g->success_count == UINT8_MAX) {
        emit_nack(g, EC_NACK_TASK_REJECTED, item.target_seq);
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
    /* 2026-09-18 BU-FIX: yuan wei ying bian ma false, dao zhi zhuang tai ji zai
     * FAULT_LOCK xia wu fa tong guo an quan tiao jian, lun ci yong yuan jian li bu qi lai.
     * gai wei App ceng mei lun tui jin de zhen shi zhi (jian shang last_* zi duan).
     * mo ren false = fail-closed. */
    event.danger_area_clear = g->last_danger_area_clear;
    event.estop_released = g->last_estop_released;
    event.content_validated = false;

    /* Latch the item context BEFORE the event is consumed: the ACK(ACCEPTED)
     * emitted by consume_and_emit must carry THIS item's target_seq. The
     * context is only meaningful once the item is accepted (VALIDATE_TASK),
     * and acceptance can only originate from WAIT_TASK - where the fields are
     * unused - so a rejected task cannot corrupt an in-flight item's context.
     * The post-consume latch below remains as the accepted-path guard. */
    if (g->sm.state == EC_STATE_WAIT_TASK) {
        g->item_target_seq = item.target_seq;
        g->item_class_id = item.class_id;
        g->item_image_id = item.image_id;
        g->item_x_mm10 = item.x_mm10;
        g->item_y_mm10 = item.y_mm10;
        g->item_pick_x_mm10 = item.pick_x_mm10;
        g->item_pick_y_mm10 = item.pick_y_mm10;
        g->item_has_pick = true;
    }

    t = consume_and_emit(g, &event);

    /* Latch the item context only if the state machine actually accepted the
     * item (dedup NEW + WAIT_TASK -> VALIDATE_TASK). */
    if (t.state == EC_STATE_VALIDATE_TASK) {
        g->item_target_seq = item.target_seq;
        g->item_class_id = item.class_id;
        g->item_image_id = item.image_id;
        g->item_x_mm10 = item.x_mm10;
        g->item_y_mm10 = item.y_mm10;
        g->item_pick_x_mm10 = item.pick_x_mm10;
        g->item_pick_y_mm10 = item.pick_y_mm10;
        g->item_has_pick = true;
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

    /* P1-FIX: Verify frame sender is PI (scheme B: Pi -> STM32).
     * Reject frames from wrong sender to prevent replay/spoofing. */
    if (frame->sender != EC_DEVICE_PI) {
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
        /* Content validation failed (target_seq / render_result / CRC / round):
         * explicit NACK per proposal sec. 3.4 (E-8). CRC-bad frames never get
         * here - they are dropped at the frame-level decode. */
        emit_nack(g, EC_NACK_ACK_NOT_APPLICABLE, ack.target_seq);
        return none_transition(g);
    }

    event.type = EC_EVENT_DISPLAY_ACK_VALIDATED;
    event.identity = g->sm.current_item; /* must match current_item */
    event.round_id = g->sm.round_id;
    event.round_closed = false;
    /* 2026-09-18 BU-FIX: yuan wei ying bian ma false, dao zhi zhuang tai ji zai
     * FAULT_LOCK xia wu fa tong guo an quan tiao jian, lun ci yong yuan jian li bu qi lai.
     * gai wei App ceng mei lun tui jin de zhen shi zhi (jian shang last_* zi duan).
     * mo ren false = fail-closed. */
    event.danger_area_clear = false;   /* DISPLAY_ACK lu jing wu xu gai: round_id qu zi sm, bu kao an quan biao zhi */
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
    ec_gateway_resp_cache_clear(g);

    g->success_count = 0U;
    g->item_target_seq = 0U;
    g->item_class_id = 0U;
    g->item_image_id = 0U;
    g->item_x_mm10 = 0;
    g->item_y_mm10 = 0;
    g->item_pick_x_mm10 = 0;
    g->item_pick_y_mm10 = 0;
    g->item_has_pick = false;
    g->item_result_code = EC_RESULT_UNKNOWN;
    g->tx_seq = 0U;
    g->rx_len = 0U;
    g->tx_len = 0U;
}

void ec_gateway_resp_cache_store(ec_gateway_t *g, ec_dedup_key_t key,
                                 const uint8_t *frame, uint16_t len)
{
    size_t index;
    size_t free_index = EC_GATEWAY_RESP_CACHE_CAPACITY;

    if ((g == NULL) || (frame == NULL) || (len == 0U) ||
        (len > EC_GATEWAY_TX_MAX)) {
        return;
    }

    for (index = 0U; index < EC_GATEWAY_RESP_CACHE_CAPACITY; ++index) {
        ec_gateway_resp_cache_entry_t *entry = &g->resp_cache[index];

        if (entry->occupied &&
            (entry->key.task_id == key.task_id) &&
            (entry->key.frame_seq == key.frame_seq) &&
            (entry->key.payload_fingerprint == key.payload_fingerprint)) {
            /* Same identity re-answered (e.g. ACK(ACCEPTED) then
             * ACK(ACK_CONSUMED)): refresh the cached bytes. */
            (void)memcpy(entry->frame, frame, len);
            entry->len = len;
            return;
        }
        if (!entry->occupied && (free_index == EC_GATEWAY_RESP_CACHE_CAPACITY)) {
            free_index = index;
        }
    }

    if (free_index != EC_GATEWAY_RESP_CACHE_CAPACITY) {
        ec_gateway_resp_cache_entry_t *entry = &g->resp_cache[free_index];

        entry->key = key;
        (void)memcpy(entry->frame, frame, len);
        entry->len = len;
        entry->occupied = true;
    }
    /* Full: drop (fail-closed). Dedup capacity == cache capacity, so the
     * dedup FULL -> FAULT_LOCK path fires first in practice. */
}

bool ec_gateway_resp_cache_lookup(const ec_gateway_t *g, ec_dedup_key_t key,
                                  const uint8_t **frame, uint16_t *len)
{
    size_t index;

    if ((g == NULL) || (frame == NULL) || (len == NULL)) return false;

    for (index = 0U; index < EC_GATEWAY_RESP_CACHE_CAPACITY; ++index) {
        const ec_gateway_resp_cache_entry_t *entry = &g->resp_cache[index];

        if (entry->occupied &&
            (entry->key.task_id == key.task_id) &&
            (entry->key.frame_seq == key.frame_seq) &&
            (entry->key.payload_fingerprint == key.payload_fingerprint)) {
            *frame = entry->frame;
            *len = entry->len;
            return true;
        }
    }
    return false;
}

/* 2026-09-18 BU-FIX: App ceng mei lun tui jin zhen shi an quan zhuang tai.
 * zhi cun chu, bu zuo ren he pan ding; pan ding reng you zhuang tai ji fu ze. */
void ec_gateway_update_safety_state(ec_gateway_t *g, bool danger_area_clear,
                                    bool estop_released)
{
    if (g == NULL) {
        return;
    }
    g->last_danger_area_clear = danger_area_clear;
    g->last_estop_released = estop_released;
}
void ec_gateway_resp_cache_clear(ec_gateway_t *g)
{
    size_t index;

    if (g == NULL) return;

    for (index = 0U; index < EC_GATEWAY_RESP_CACHE_CAPACITY; ++index) {
        g->resp_cache[index].occupied = false;
        g->resp_cache[index].len = 0U;
    }
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
        /* P2-FIX: round_id is emitted as a uint16 task_id in outbound frames;
         * a larger round id would be truncated on the wire and the DISPLAY_ACK
         * round gate could never match. Reject instead of silently wrapping. */
        if (event->round_id > UINT16_MAX) {
            return none_transition(g);
        }
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

    /* P2-FIX: reset success_count and item context only when the state machine
     * actually committed MANUAL_NEW_ROUND_CONFIRMED (FAULT_LOCK -> POWER_ON,
     * which itself requires round_id change + round_closed + danger_area_clear
     * + estop_released). A rejected confirmation must not clear counters. */
    if (event->type == EC_EVENT_MANUAL_NEW_ROUND_CONFIRMED &&
        transition.state == EC_STATE_POWER_ON) {
        g->success_count = 0U;
        g->item_target_seq = 0U;
        g->item_class_id = 0U;
        g->item_image_id = 0U;
        g->item_x_mm10 = 0;
        g->item_y_mm10 = 0;
        g->item_pick_x_mm10 = 0;
        g->item_pick_y_mm10 = 0;
        g->item_has_pick = false;
        g->item_result_code = EC_RESULT_UNKNOWN;
        /* Same window as dedup (proposal sec. 3.3.3 / E-7): a verified new
         * round invalidates every cached response. */
        ec_gateway_resp_cache_clear(g);
    }

    /* interface-contract sec. 6.1: success_count is 0..255, increments only
     * on the first valid SUCCESS result, and must not wrap 255 -> 0. Increment
     * only when the state machine actually committed WAIT_ITEM_RESULT ->
     * WAIT_DISPLAY_ACK, so a duplicate or replayed ITEM_RESULT is idempotent.
     * P1-FIX: At 255, reject NEW -> WAIT_TASK transitions that could accept
     * another potentially-successful item (state machine allows it, but the
     * counter cannot represent 256). */
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

bool ec_gateway_item_target(const ec_gateway_t *g, int16_t *x_mm10,
                            int16_t *y_mm10)
{
    if ((g == NULL) || (x_mm10 == NULL) || (y_mm10 == NULL)) {
        return false;
    }
    *x_mm10 = g->item_x_mm10;
    *y_mm10 = g->item_y_mm10;
    return true;
}

/* P3 (2026-09-16): the bench stub (fixed (0,0), always true) is gone. Read the
 * grasp point latched from ITEM_TASK offsets 8-11, mirroring
 * ec_gateway_item_target() above.
 *
 * The gate is item_has_pick, NOT "the gateway once accepted something": a bare
 * (0,0) from an unset latch must never be mistaken for a real device-centre
 * grasp. Both latch sites set the flag together with the coordinates, and both
 * clear sites (ec_gateway_init / verified new round) clear it together with
 * them, so the flag can never outlive the coordinates it describes. */
bool ec_gateway_item_pick(const ec_gateway_t *g, int16_t *x_mm10,
                          int16_t *y_mm10)
{
    if ((g == NULL) || (x_mm10 == NULL) || (y_mm10 == NULL)) {
        return false;
    }
    if (!g->item_has_pick) {
        return false; /* fail-closed: no grasp point has been supplied yet */
    }
    *x_mm10 = g->item_pick_x_mm10;
    *y_mm10 = g->item_pick_y_mm10;
    return true;
}

/* 2026-09-21 新增：读当前件的**类别 ID**（ITEM_TASK payload offset 1）。
 * 用途：按类别选择张开脉宽 —— 现场实测三类需要不同开度
 * （正方体 650 / 三棱柱 750 / 圆柱 800 µs，见 docs/交付/2026-09-21/现场脉宽标定记录）。
 *
 * 锁存与清除都与 item_pick 同批（:168/:183 与 :174/:189 一起写，
 * :284/:510 与 :290/:516 一起清），而 class_id 的现行取值域是 1..6
 * （视觉端 COLOR_TO_MATERIAL 的 bin_id），0 表示"没有已受理的件"。
 * 故直接用 `item_class_id == 0` 当闸，不需要额外标志位。 */
bool ec_gateway_item_class(const ec_gateway_t *g, uint8_t *class_id)
{
    if ((g == NULL) || (class_id == NULL)) {
        return false;
    }
    if (g->item_class_id == 0U) {
        return false; /* fail-closed：无已受理件，调用方退回默认张开脉宽 */
    }
    *class_id = g->item_class_id;
    return true;
}

bool ec_gateway_rx_active(const ec_gateway_t *g)
{
    return (g != NULL) && (g->rx_len != 0U);
}
