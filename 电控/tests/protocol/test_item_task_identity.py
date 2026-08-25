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

    def test_full_payload_round_trips_frozen_8_byte_golden(self) -> None:
        item = ItemTaskPayload(1, 2, 2, -1000, 1000, 0xFF)

        encoded = encode_item_task_payload(item)
        self.assertEqual(bytes.fromhex("01 02 02 FC 18 03 E8 FF"), encoded)
        self.assertEqual(item, decode_item_task_payload(encoded))

    def test_payload_is_loose_but_encode_enforces_boundary(self) -> None:
        # Plan A: the payload class stays a loose logical carrier; placeholder
        # 0/0/0 is legal, but the wire boundary rejects a non-0xFF grip_angle.
        item = ItemTaskPayload(1, 2, 2, 0, 0, 0)

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
