from __future__ import annotations

import unittest

from electrical_control.protocol import (
    Command,
    ItemTaskIdentity,
    ItemTaskPayload,
    PayloadError,
    decode_item_task_identity_prefix,
    decode_item_task_payload,
    encode_item_task_identity_prefix,
    encode_item_task_payload,
)


class ItemTaskIdentityTests(unittest.TestCase):
    def test_frozen_identity_prefix_matches_c_layout(self) -> None:
        self.assertEqual(
            bytes.fromhex("01 03 09"),
            encode_item_task_identity_prefix(1, 3, 9),
        )

    def test_identity_round_trip_leaves_unfrozen_remainder_opaque(self) -> None:
        payload = bytes.fromhex("01 03 09 DE AD BE EF 2D")

        identity, remainder = decode_item_task_identity_prefix(payload)

        self.assertEqual(ItemTaskIdentity(1, 3, 9), identity)
        self.assertEqual(bytes.fromhex("DE AD BE EF 2D"), remainder)

    def test_short_identity_prefix_is_rejected(self) -> None:
        with self.assertRaises(PayloadError):
            decode_item_task_identity_prefix(bytes.fromhex("01 03"))

    def test_full_payload_round_trips_frozen_12_byte_golden(self) -> None:
        # P3 (2026-09-16): 12 bytes = the 8-byte drop frame + the grasp point.
        item = ItemTaskPayload(1, 2, 2, -1000, 1000, 0xFF, 250, -250)

        encoded = encode_item_task_payload(item)
        self.assertEqual(
            bytes.fromhex("01 02 02 FC 18 03 E8 FF 00 FA FF 06"), encoded
        )
        self.assertEqual(12, len(encoded))
        self.assertEqual(item, decode_item_task_payload(encoded))

    def test_pre_p3_8_byte_payload_is_refused(self) -> None:
        """fail-closed：旧线格式必须被拒，不能被当成 12 字节载荷解释。"""
        with self.assertRaises(PayloadError):
            decode_item_task_payload(bytes.fromhex("01 02 02 FC 18 03 E8 FF"))

    def test_missing_grasp_point_is_refused_at_the_wire_boundary(self) -> None:
        """没有毫米抓取点就不许序列化——绝不用 (0,0) 顶上（E-18 空夹）。"""
        item = ItemTaskPayload(1, 2, 2, -1000, 1000, 0xFF, None, None)

        self.assertIsNone(item.pick_x_position)
        with self.assertRaises(PayloadError):
            encode_item_task_payload(item)

    def test_grasp_point_is_required_at_construction(self) -> None:
        """§9.2：新字段没有默认值，构造点漏传即 TypeError（编不过，不是静默默认）。"""
        with self.assertRaises(TypeError):
            ItemTaskPayload(1, 2, 2, -1000, 1000, 0xFF)  # type: ignore[call-arg]

    def test_payload_is_loose_but_encode_enforces_boundary(self) -> None:
        # Plan A: the payload class stays a loose logical carrier; placeholder
        # 0/0/0 is legal, but the wire boundary rejects a non-0xFF grip_angle.
        item = ItemTaskPayload(1, 2, 2, 0, 0, 0, None, None)

        self.assertEqual(0, item.x_position)
        with self.assertRaises(PayloadError):
            encode_item_task_payload(item)

    def test_command_enum_carries_all_frozen_command_words(self) -> None:
        self.assertEqual(0x21, int(Command.ITEM_TASK))
        self.assertEqual(0x23, int(Command.ITEM_RESULT))
        self.assertEqual(0x25, int(Command.DISPLAY_ACK))
        self.assertEqual(0x26, int(Command.ESTOP))
        self.assertEqual(0x10, int(Command.BATCH_TARGETS))
        self.assertEqual(0x12, int(Command.TARGET_REACQUIRE_RSP))


if __name__ == "__main__":
    unittest.main()
