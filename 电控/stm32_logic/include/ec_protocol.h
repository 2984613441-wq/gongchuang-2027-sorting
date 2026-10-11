#ifndef EC_PROTOCOL_H
#define EC_PROTOCOL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Wire protocol frame codec (interface-contract.md V0.4).
 *
 * Frozen (user-adjudicated 2026-08-24):
 *   - frame header 0xA5 0x5A
 *   - protocol version 0x01
 *   - frame-level CRC = CRC-16/MODBUS (poly 0x8005, init 0xFFFF, no reflect,
 *     no final xor)
 *   - task_id / frame_seq / data_len fields are big-endian ("network byte order")
 *
 * Not frozen (do NOT guess here - see interface-contract.md sec. 5.2 note + sec. 8):
 *   - timeouts / retry counts / heartbeat interval
 */

/* Frame layout (offsets in bytes):
 *   0..1   header       0xA5 0x5A
 *   2      version      0x01
 *   3      sender       device id
 *   4      receiver     device id
 *   5..6   task_id      big-endian
 *   7..8   frame_seq    big-endian
 *   9      command      command word
 *   10..11 data_len     big-endian, payload byte count
 *   12..   payload      data_len bytes
 *   ..+2   crc16        big-endian, over bytes 0..(11+data_len)
 */
#define EC_PROTO_HEADER_0 UINT8_C(0xA5)
#define EC_PROTO_HEADER_1 UINT8_C(0x5A)
#define EC_PROTO_VERSION UINT8_C(0x01)

#define EC_PROTO_HEADER_LEN 12U   /* bytes before the payload */
#define EC_PROTO_CRC_LEN 2U
#define EC_PROTO_FRAME_OVERHEAD (EC_PROTO_HEADER_LEN + EC_PROTO_CRC_LEN)

/* Device ids (interface-contract.md sec. 3). */
#define EC_DEVICE_MAIXCAM UINT8_C(0x01)
#define EC_DEVICE_PI UINT8_C(0x02)
#define EC_DEVICE_STM32 UINT8_C(0x03)

/* Command words (interface-contract.md sec. 4). L0 shared + L2 dispatch chain. */
#define EC_CMD_HEARTBEAT UINT8_C(0x01)
#define EC_CMD_HEARTBEAT_ACK UINT8_C(0x02)
#define EC_CMD_DEVICE_READY UINT8_C(0x03)
#define EC_CMD_ERROR UINT8_C(0x04)
#define EC_CMD_ACK UINT8_C(0x05)
#define EC_CMD_NACK UINT8_C(0x06)
#define EC_CMD_BARRIER_READY UINT8_C(0x20)
#define EC_CMD_ITEM_TASK UINT8_C(0x21)
#define EC_CMD_MOTION_DONE UINT8_C(0x22)
#define EC_CMD_ITEM_RESULT UINT8_C(0x23)
#define EC_CMD_DISPLAY_DATA UINT8_C(0x24)
#define EC_CMD_DISPLAY_ACK UINT8_C(0x25)
#define EC_CMD_ESTOP UINT8_C(0x26)

/* A decoded/encoded outer frame. `payload` points into the caller's buffer
 * (on decode) or the caller's own payload memory (on encode). */
typedef struct {
    uint8_t version;
    uint8_t sender;
    uint8_t receiver;
    uint16_t task_id;
    uint16_t frame_seq;
    uint8_t command;
    const uint8_t *payload;
    uint16_t payload_len;
} ec_proto_frame_t;

/* CRC-16/MODBUS over `data`. Golden vector: "123456789" -> 0x4B37. */
uint16_t ec_crc16_modbus(const uint8_t *data, size_t length);

/* Serialise a frame into `out` (needs EC_PROTO_HEADER_LEN + payload_len +
 * EC_PROTO_CRC_LEN bytes). Returns total bytes written, or 0 on error. */
size_t ec_proto_encode(const ec_proto_frame_t *frame, uint8_t *out,
                       size_t out_cap);

/* Parse one frame from `buf` (must start at a frame boundary; trailing bytes
 * beyond the frame are ignored). Validates header, version and CRC. On
 * success returns true and fills `*frame` with pointers into `buf`. */
bool ec_proto_decode(const uint8_t *buf, size_t length, ec_proto_frame_t *frame);

/* --- DISPLAY_ACK payload (0x25) - FROZEN (interface-contract.md sec. 5.5) ---
 *   target_seq(1) + render_result(1) + display_crc32(4, big-endian) = 6 bytes.
 *   render_result 0x00 = RENDERED; other values are not a release. */
#define EC_DISPLAY_ACK_RENDERED UINT8_C(0x00)
#define EC_DISPLAY_ACK_PAYLOAD_LEN 6U

typedef struct {
    uint8_t target_seq;
    uint8_t render_result;
    uint32_t display_crc32;
} ec_proto_display_ack_t;

/* Display-content CRC32 input = the five frozen single bytes
 * target_seq + class_id + image_id + success_count + result_code, in that
 * order (interface-contract.md sec. 5.5). Golden vector for bytes
 * 01 02 03 04 05 is 0x470B99F4. */
uint32_t ec_proto_display_content_crc32(uint8_t target_seq, uint8_t class_id,
                                        uint8_t image_id,
                                        uint8_t success_count,
                                        uint8_t result_code);

bool ec_proto_encode_display_ack(const ec_proto_display_ack_t *ack,
                                 uint8_t *out, uint16_t out_cap);
bool ec_proto_decode_display_ack(const uint8_t *payload, uint16_t payload_len,
                                 ec_proto_display_ack_t *out);

/* --- ACK / NACK payloads (0x05 / 0x06) - FROZEN by user adjudication
 * 2026-08-29 (docs/design/2026-08-29-ack-response-definition-proposal.md,
 * unresolved items E-1/E-2): reason(1) + target_seq(1) = 2 bytes.
 * ACK reasons: ACCEPTED (ITEM_TASK accepted), ACK_CONSUMED (DISPLAY_ACK
 * consumed). NACK reasons: STALE_OR_ORDER / UNEXPECTED_MESSAGE /
 * SINGLE_TASK_ONLY / ACK_NOT_APPLICABLE / WRONG_ROUND / TASK_REJECTED.
 * target_seq echoes the item identity; 0xFF when unavailable. */
#define EC_ACK_PAYLOAD_LEN 2U
#define EC_NACK_PAYLOAD_LEN 2U

#define EC_ACK_REASON_ACCEPTED UINT8_C(0x00)
#define EC_ACK_REASON_ACK_CONSUMED UINT8_C(0x01)

#define EC_NACK_STALE_OR_ORDER UINT8_C(0x10)
#define EC_NACK_UNEXPECTED_MESSAGE UINT8_C(0x11)
#define EC_NACK_SINGLE_TASK_ONLY UINT8_C(0x12)
#define EC_NACK_ACK_NOT_APPLICABLE UINT8_C(0x13)
#define EC_NACK_WRONG_ROUND UINT8_C(0x14)
#define EC_NACK_TASK_REJECTED UINT8_C(0x15)

bool ec_proto_encode_ack(uint8_t reason, uint8_t target_seq, uint8_t *out,
                         uint16_t out_cap);
bool ec_proto_decode_ack(const uint8_t *payload, uint16_t payload_len,
                         uint8_t *reason, uint8_t *target_seq);
bool ec_proto_encode_nack(uint8_t reason, uint8_t target_seq, uint8_t *out,
                          uint16_t out_cap);
bool ec_proto_decode_nack(const uint8_t *payload, uint16_t payload_len,
                          uint8_t *reason, uint8_t *target_seq);

/* --- ITEM_TASK payload (0x21) - FROZEN (interface-contract.md sec. 5.2) ---
 * 2026-09-16 (P3): payload 8 -> 12 bytes, the grasp (pick) point appended at
 * the TAIL. The competition requires a random grasp point and a fixed drop
 * point; the 8-byte payload only carried the drop point, so the grasp point
 * was hard-wired to (0,0) in the firmware -> every real grasp would close on
 * empty air (ledger E-18). Appending instead of reusing offsets 3-6 keeps the
 * frozen "drop point" meaning of those bytes.
 *
 *   offset 0     target_seq(1)
 *   offset 1     class_id(1)
 *   offset 2     image_id(1)
 *   offset 3-4   x_mm10(2, int16 BE, 0.1mm)      drop X (semantics unchanged)
 *   offset 5-6   y_mm10(2, int16 BE, 0.1mm)      drop Y (semantics unchanged)
 *   offset 7     grip_angle(1, always 0xFF)
 *   offset 8-9   pick_x_mm10(2, int16 BE, 0.1mm) *NEW* grasp X
 *   offset 10-11 pick_y_mm10(2, int16 BE, 0.1mm) *NEW* grasp Y
 *
 * Both coordinate pairs share one frame: origin = device center, units 0.1mm,
 * |value| > 1450 (+-145.0 mm) rejected. The grasp point is additionally
 * bounded by the tighter mechanical reach limit (EC_MOTION_REACH_LIMIT_MM10 =
 * 825 in ec_motion_plan.h), but that check belongs to the motion planner; this
 * codec only enforces the protocol domain.
 * grip_angle must be 0xFF (claw does not rotate); 0..180 unused this round.
 *
 * There is no "no grasp point" encoding on the wire. A sender that has no
 * millimetre grasp point must not send this frame at all (Python raises
 * PayloadError; see item_context.py). The strict length check makes old and
 * new firmware mutually incompatible (12 != 8 -> decode fails -> fail-closed,
 * never misaligned execution); Pi and STM32 must be upgraded together. */
#define EC_PROTO_ITEM_TASK_PAYLOAD_LEN 12U
#define EC_PROTO_ITEM_TASK_X_LIMIT 1450
#define EC_PROTO_ITEM_TASK_ANGLE_NONE UINT8_C(0xFF)

typedef struct {
    uint8_t target_seq;
    uint8_t class_id;
    uint8_t image_id;
    int16_t x_mm10;         /* drop X (semantics unchanged) */
    int16_t y_mm10;         /* drop Y (semantics unchanged) */
    uint8_t grip_angle;
    int16_t pick_x_mm10;    /* *NEW* grasp X */
    int16_t pick_y_mm10;    /* *NEW* grasp Y */
} ec_proto_item_task_t;

bool ec_proto_encode_item_task(const ec_proto_item_task_t *item,
                               uint8_t *payload, uint16_t cap);
bool ec_proto_decode_item_task(const uint8_t *payload, uint16_t payload_len,
                               ec_proto_item_task_t *out);

#endif
