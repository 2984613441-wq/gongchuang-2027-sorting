#ifndef EC_PROTOCOL_GATEWAY_H
#define EC_PROTOCOL_GATEWAY_H

/* Production protocol gateway: bridges the frozen binary frame codec
 * (ec_protocol.h) and the dormant state machine (ec_state_machine.h).
 *
 * Responsibilities (all pure logic, no HAL - lives in stm32_logic):
 *   - assemble a frame from a byte stream (frame start 0xA5 0x5A, length from
 *     the header data_len, then CRC check)
 *   - turn inbound ITEM_TASK / DISPLAY_ACK frames into state-machine events
 *     (ITEM_TASK_ACCEPTED / DISPLAY_ACK_VALIDATED)
 *   - turn outbound EMIT_* actions into frames (BARRIER_READY / MOTION_DONE /
 *     ITEM_RESULT) with an incrementing STM32 frame_seq
 *   - maintain the round-local success_count (interface-contract sec. 6.1)
 *   - expose a manual/hardware event injection entry point for the boot
 *     sequence (POST/homing/barrier/new-round) and the motion-done / item-
 *     result / task-validated events that only the app layer can source
 *
 * The app layer (ec_app.c) binds it: UART RX bytes -> feed_byte, completed
 * axis program -> inject(MOTION_DONE), tx_buf -> board UART transmit, and the
 * START_MOTION / SAFE_LOCK actions -> axis driver / safety adapter.
 */

#include "ec_protocol.h"
#include "ec_state_machine.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Dedup capacity: one slot per distinct item identity this round. A round is
 * bounded by the barrier / 15 s budget, so 8 is ample; raise it only if a
 * round is ever observed to exceed it. */
#define EC_GATEWAY_DEDUP_CAPACITY 8U

/* Max assembled RX frame and queued TX frame. Every currently-defined command
 * is small (ITEM_TASK 12 = identity 3 + drop X/Y + angle + grasp X/Y, DISPLAY_ACK
 * 6, ITEM_RESULT 3); 64 bytes leaves ample margin. */
#define EC_GATEWAY_RX_MAX 64U
#define EC_GATEWAY_TX_MAX 64U

/* Response cache (proposal 2026-08-29 sec. 3.3.3): one slot per distinct item
 * identity this round, same capacity and clear timing as the dedup cache
 * (E-7). Stores the exact outbound response frame bytes - ACK(ACCEPTED) on
 * item acceptance, ACK(ACK_CONSUMED) on display-ack consumption - so a
 * duplicate request can be answered by replaying the original bytes without
 * incrementing tx_seq (E-5). */
#define EC_GATEWAY_RESP_CACHE_CAPACITY EC_GATEWAY_DEDUP_CAPACITY

typedef struct {
    ec_dedup_key_t key;
    uint8_t frame[EC_GATEWAY_TX_MAX];
    uint16_t len;
    bool occupied;
} ec_gateway_resp_cache_entry_t;

/* ITEM_RESULT result codes (interface-contract sec. 5.3). */
#define EC_RESULT_SUCCESS UINT8_C(0x00)
#define EC_RESULT_DROP_FAILED UINT8_C(0x01)
#define EC_RESULT_GRIP_FAILED UINT8_C(0x02)
#define EC_RESULT_POSITION_UNREACHABLE UINT8_C(0x03)
#define EC_RESULT_SAFETY_INTERRUPT UINT8_C(0x04)
#define EC_RESULT_UNKNOWN UINT8_C(0xFF)

/* ITEM_RESULT basis (interface-contract sec. 5.3): CONTROL_SEQUENCE is the
 * base-chain value; CONFIRMED requires a result-confirmation sensor that the
 * current build does not have. */
#define EC_RESULT_BASIS_CONTROL_SEQUENCE UINT8_C(0x00)

typedef struct {
    ec_state_machine_t sm;
    ec_dedup_t dedup;
    ec_dedup_entry_t dedup_storage[EC_GATEWAY_DEDUP_CAPACITY];
    ec_gateway_resp_cache_entry_t resp_cache[EC_GATEWAY_RESP_CACHE_CAPACITY];

    /* Round-local success count (interface-contract sec. 6.1): only the first
     * valid SUCCESS item result this round increments it. */
    uint8_t success_count;

    /* Current item context (frozen ITEM_TASK identity prefix). Set on
     * ITEM_TASK_ACCEPTED; used to validate DISPLAY_ACK and build ITEM_RESULT. */
    uint8_t item_target_seq;
    uint8_t item_class_id;
    uint8_t item_image_id;

    /* Drop (basket) coordinates of the current item, in 0.1mm units, origin =
     * device center (interface-contract sec. 5.2). Latched with the identity
     * prefix; consumed by the app layer to build the pick-place motion program. */
    int16_t item_x_mm10;
    int16_t item_y_mm10;

    /* P3 (2026-09-16): grasp (pick) point latch, same frame and units as
     * item_x/y. Written in the SAME latch blocks as item_x/y and cleared in the
     * SAME blocks - splitting the two would recreate the E-18 class of bug
     * ("new grasp point paired with the previous item's drop point", or the
     * reverse after a new round). */
    int16_t item_pick_x_mm10;
    int16_t item_pick_y_mm10;
    /* True only once an accepted ITEM_TASK has latched a grasp point.
     * ec_gateway_item_pick() refuses to answer while this is false, so a call
     * that arrives before any item (or after a verified new round) fails closed
     * instead of silently commanding a (0,0) = device-centre grasp. Rejecting
     * "no grasp point supplied" at the source is the sender's job: the wire has
     * no "absent pick" encoding (ec_protocol.h), and the Python/PC-tool codecs
     * refuse to serialise an ITEM_TASK without one. */
    bool item_has_pick;

    /* 2026-09-18 BU-FIX: ben di mei jie ren he an jian(START/MANUAL_RESET/ESTOP jun xuan kong),
     * gu wu fa chan sheng MANUAL_NEW_ROUND_CONFIRMED shi jian. wei shi xian "shu mei pai
     * fa lai ITEM_TASK ji ke jian li xin yi lun", wang guan xu yao zai gou zao gai shi jian shi
     * dai shang ZHEN SHI de an quan zhuang tai.
     * 🔴 zhe liang ge zhi bi xu you App ceng mei lun yong zhen shi active_inputs ji suan hou
     *    tui jin lai, JUE DUI bu ke xie si wei true —— na deng yu rao guo ji ting jian cha.
     * mo ren false = fail-closed: App ceng mei tui jin lai zhi qian, jian li lun ci yi ding shi bai. */
    bool last_danger_area_clear;
    bool last_estop_released;

    /* Result code of the current item's completed axis program, used to build
     * ITEM_RESULT and to validate DISPLAY_ACK content. */
    uint8_t item_result_code;

    /* Outbound STM32 frame sequence (interface-contract sec. 3): incremented
     * per emitted frame so the peer can dedup/order. */
    uint16_t tx_seq;

    /* Frame assembly: RX byte stream -> one complete frame. */
    uint8_t rx_buf[EC_GATEWAY_RX_MAX];
    size_t rx_len;

    /* Pending outbound frame, constructed by the last transition's EMIT_*
     * actions. Valid until the next dispatch/inject. */
    uint8_t tx_buf[EC_GATEWAY_TX_MAX];
    size_t tx_len;
} ec_gateway_t;

/* Manual/hardware-sourced event. Only the fields the named event consumes are
 * used; the gateway fills identity / round_id for context-sensitive events
 * (TASK_SAFETY_VALIDATED / MOTION_DONE / ITEM_RESULT_RECORDED) from the
 * state-machine current item + round. */
typedef struct {
    ec_event_type_t type;
    /* MANUAL_NEW_ROUND_CONFIRMED only. */
    uint32_t round_id;
    bool round_closed;
    bool danger_area_clear;
    bool estop_released;
    /* TASK_SAFETY_VALIDATED only. */
    bool content_validated;
    /* ITEM_RESULT_RECORDED only (ITEM_RESULT result code, sec. 5.3). */
    uint8_t result_code;
} ec_gateway_event_t;

void ec_gateway_init(ec_gateway_t *g);

/* 2026-09-18 BU-FIX: App ceng mei lun tui jin zhen shi an quan zhuang tai (jian shang). */
void ec_gateway_update_safety_state(ec_gateway_t *g, bool danger_area_clear,
                                    bool estop_released);

/* Feed one RX byte. When a complete, CRC-valid frame has been assembled it is
 * dispatched and the resulting transition returned. When no frame completed
 * (or the frame was rejected / out of context), returns a transition with the
 * current state and EC_ACTION_NONE. */
ec_transition_t ec_gateway_feed_byte(ec_gateway_t *g, uint8_t byte);

/* Inject a manual/hardware event and consume it. */
ec_transition_t ec_gateway_inject(ec_gateway_t *g,
                                  const ec_gateway_event_t *event);

/* Outbound frame produced by the last dispatch/inject's EMIT_* actions. */
const uint8_t *ec_gateway_tx_data(const ec_gateway_t *g);
size_t ec_gateway_tx_len(const ec_gateway_t *g);

ec_state_t ec_gateway_state(const ec_gateway_t *g);

/* Read the current item's drop coordinates (0.1mm, device-center origin).
 * Returns false (and leaves x and y untouched) if g or an out-pointer is NULL;
 * otherwise writes the latched values. */
bool ec_gateway_item_target(const ec_gateway_t *g, int16_t *x_mm10,
                            int16_t *y_mm10);

/* Read the current item's PICK (grasp) coordinates - same frame and same units
 * (0.1mm, origin = device center) as ec_gateway_item_target() above; the grasp
 * point differs per item, the drop point does not.
 *
 * P3 (2026-09-16): the temporary bench stub (fixed (0,0), always true) is gone.
 * The grasp point now comes from the ITEM_TASK latch (offsets 8-11).
 *
 * Fail-closed rule: returns false while no accepted ITEM_TASK has latched a
 * grasp point (item_has_pick == false), i.e. after ec_gateway_init() or after a
 * verified new round. (0,0) is a legal grasp point (device centre), so it must
 * only be honoured when a sender actually said so - the call site
 * (ec_app_start_motion) turns false into POSITION_UNREACHABLE and never guesses
 * a coordinate. */
bool ec_gateway_item_pick(const ec_gateway_t *g, int16_t *x_mm10,
                          int16_t *y_mm10);

/* 2026-09-21 新增：读当前件的**类别 ID**（ITEM_TASK payload offset 1，取值 1..6）。
 * 用途 = 按类别选择张开脉宽（现场实测三类需要不同开度）。
 *
 * Fail-closed 与 ec_gateway_item_pick() 同款：**没有已受理的件**时返回 false
 * （item_class_id == 0 —— ec_gateway_init 与验证过的新轮次都会把它清零，
 * 且它和 pick 坐标是同批锁存/同批清除的）。调用方此时必须退回默认张开脉宽
 * EC_AXIS_GRIPPER_OPEN_US，**绝不猜类别**。 */
bool ec_gateway_item_class(const ec_gateway_t *g, uint8_t *class_id);

/* Response cache (same window as dedup; cleared on verified new round).
 * Store records the exact response frame bytes for one identity (overwriting
 * an existing entry for the same key, e.g. ACK(ACCEPTED) then
 * ACK(ACK_CONSUMED)); lookup returns a pointer into the cache on hit;
 * clear drops every entry. */
void ec_gateway_resp_cache_store(ec_gateway_t *g, ec_dedup_key_t key,
                                 const uint8_t *frame, uint16_t len);
bool ec_gateway_resp_cache_lookup(const ec_gateway_t *g, ec_dedup_key_t key,
                                  const uint8_t **frame, uint16_t *len);
void ec_gateway_resp_cache_clear(ec_gateway_t *g);

/* True while a binary frame is mid-assembly (rx_len > 0). The app layer uses
 * this to route RX bytes: while a frame is assembling, bytes go to the
 * gateway; otherwise they are ASCII diagnostics. */
bool ec_gateway_rx_active(const ec_gateway_t *g);

#endif
