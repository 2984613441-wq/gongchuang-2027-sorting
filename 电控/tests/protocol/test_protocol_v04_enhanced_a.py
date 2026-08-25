"""RED contract tests for the user-approved protocol V0.4 enhanced A.

These tests intentionally name the desired API before production code exists.
They cover only the frozen payload/context subset, not the unfrozen outer frame.
"""

from __future__ import annotations

import unittest

import electrical_control.protocol as protocol


class ItemTaskV04PayloadTests(unittest.TestCase):
    def test_item_task_payload_encodes_frozen_8_byte_wire_format(self) -> None:
        item = protocol.ItemTaskPayload(
            target_seq=1,
            class_id=2,
            image_id=3,
            x_position=-1000,
            y_position=1000,
            grip_angle=0xFF,
        )

        self.assertEqual(3, item.image_id)
        self.assertEqual(
            bytes.fromhex("01 02 03 FC 18 03 E8 FF"),
            protocol.encode_item_task_payload(item),
        )


class RoundSuccessCounterTests(unittest.TestCase):
    def test_both_nodes_start_from_same_zero_value(self) -> None:
        raspi = protocol.RoundSuccessCounter()
        stm32 = protocol.RoundSuccessCounter()

        self.assertEqual(0, raspi.value)
        self.assertEqual(raspi.value, stm32.value)

    def test_only_successful_item_result_increments(self) -> None:
        counter = protocol.RoundSuccessCounter()

        counter.record_item_result(task_id=7, frame_seq=10, result_code=0x01)
        self.assertEqual(0, counter.value)
        counter.record_item_result(task_id=7, frame_seq=11, result_code=0x00)
        self.assertEqual(1, counter.value)

    def test_result_without_stable_identity_is_rejected(self) -> None:
        counter = protocol.RoundSuccessCounter()

        with self.assertRaises(protocol.ProtocolError):
            counter.record_item_result(result_code=0x00)

    def test_duplicate_result_identity_is_not_counted_twice(self) -> None:
        counter = protocol.RoundSuccessCounter()

        self.assertTrue(
            counter.record_item_result(task_id=7, frame_seq=11, result_code=0x00)
        )
        self.assertFalse(
            counter.record_item_result(task_id=7, frame_seq=11, result_code=0x00)
        )

        self.assertEqual(1, counter.value)

    def test_round_reset_restores_shared_initial_value(self) -> None:
        counter = protocol.RoundSuccessCounter()
        counter.record_item_result(task_id=7, frame_seq=11, result_code=0x00)

        counter.reset_round(new_round_verified=True)

        self.assertEqual(0, counter.value)

    def test_unverified_reset_and_desynchronized_context_are_rejected(self) -> None:
        counter = protocol.RoundSuccessCounter()
        counter.record_item_result(task_id=7, frame_seq=11, result_code=0x00)

        with self.assertRaises(protocol.ProtocolError):
            counter.reset_round(new_round_verified=False)
        with self.assertRaises(protocol.ProtocolError):
            protocol.verify_counter_context(
                local_task_id=7,
                local_success_count=counter.value,
                local_item=(1, 2, 3, 0),
                peer_task_id=7,
                peer_success_count=0,
                peer_item=(1, 2, 3, 0),
            )

        self.assertEqual(1, counter.value)

    def test_same_result_identity_with_different_result_is_a_conflict(self) -> None:
        counter = protocol.RoundSuccessCounter()
        counter.record_item_result(task_id=7, frame_seq=11, result_code=0x01)

        with self.assertRaises(protocol.ResultIdentityConflict):
            counter.record_item_result(task_id=7, frame_seq=11, result_code=0x00)

    def test_success_beyond_unsigned_byte_range_is_explicitly_rejected(self) -> None:
        counter = protocol.RoundSuccessCounter(initial_value=0xFF)

        with self.assertRaises(protocol.SuccessCountOverflow):
            counter.record_item_result(task_id=7, frame_seq=11, result_code=0x00)

        self.assertEqual(0xFF, counter.value)
        self.assertFalse(counter.can_accept_new_item)


class DisplayContentFromItemResultTests(unittest.TestCase):
    def test_display_digest_uses_task_image_and_updated_success_count(self) -> None:
        item = protocol.ItemTaskPayload(
            target_seq=1,
            class_id=2,
            image_id=3,
            x_position=0x1234,
            y_position=0x5678,
            grip_angle=90,
        )
        counter = protocol.RoundSuccessCounter()
        counter.record_item_result(task_id=7, frame_seq=11, result_code=0x00)

        with self.assertRaises(protocol.ProtocolError):
            protocol.verify_counter_context(
                local_task_id=7,
                local_success_count=1,
                local_item=(1, 2, 3, 0),
                peer_task_id=7,
                peer_success_count=1,
                peer_item=(1, 2, 4, 0),
            )

        content = protocol.build_display_content(
            item_task=item,
            success_count=counter.value,
            result_code=0x00,
        )

        self.assertEqual(bytes.fromhex("01 02 03 01 00"), content.canonical_bytes())
        self.assertEqual(1, content.target_seq)
        self.assertEqual(2, content.class_id)
        self.assertEqual(3, content.image_id)
        self.assertEqual(1, content.success_count)
        self.assertEqual(0x00, content.result_code)


if __name__ == "__main__":
    unittest.main()
