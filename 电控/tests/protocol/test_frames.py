from __future__ import annotations

import unittest

from electrical_control.protocol import (
    Command,
    Device,
    ItemResultPayload,
    PayloadError,
    decode_item_result_payload,
    decode_outer_frame,
    encode_display_ack_frame,
    encode_item_task_frame,
)


class ItemResultPayloadTests(unittest.TestCase):
    def test_decodes_frozen_three_byte_payload(self) -> None:
        payload = decode_item_result_payload(bytes.fromhex("01 00 00"))

        self.assertEqual(ItemResultPayload(1, 0, 0), payload)

    def test_rejects_wrong_length(self) -> None:
        for length in (2, 4):
            with self.subTest(length=length):
                with self.assertRaises(PayloadError):
                    decode_item_result_payload(bytes(length))


class DisplayAckFrameTests(unittest.TestCase):
    def test_known_display_ack_frame_matches_reference_bytes(self) -> None:
        encoded = encode_display_ack_frame(
            task_id=7,
            frame_seq=21,
            target_seq=1,
            render_result=0x00,
            content_crc32=0x470B99F4,
        )

        self.assertEqual(
            bytes.fromhex("A5 5A 01 02 03 00 07 00 15 25 00 06 01 00 47 0B 99 F4 85 32"),
            encoded,
        )

    def test_frame_decodes_with_frozen_display_ack_payload(self) -> None:
        encoded = encode_display_ack_frame(
            task_id=7,
            frame_seq=21,
            target_seq=3,
            render_result=0x00,
            content_crc32=0x470B99F4,
        )
        frame = decode_outer_frame(encoded)

        self.assertEqual(Device.RASPI, frame.sender)
        self.assertEqual(Device.STM32, frame.receiver)
        self.assertEqual(Command.DISPLAY_ACK, Command(frame.command))
        self.assertEqual(bytes.fromhex("03 00 47 0B 99 F4"), frame.payload)


class ItemTaskFrameTests(unittest.TestCase):
    def test_item_task_frame_uses_full_12_byte_payload(self) -> None:
        payload = bytes.fromhex("01 02 02 FC 18 03 E8 FF 00 FA FF 06")
        encoded = encode_item_task_frame(task_id=7, frame_seq=11, payload=payload)
        frame = decode_outer_frame(encoded)

        self.assertEqual(Command.ITEM_TASK, Command(frame.command))
        self.assertEqual(payload, frame.payload)
        # 14 bytes overhead + 12 payload = 26 (P3: was 22)
        self.assertEqual(26, len(encoded))

    def test_item_task_frame_rejects_wrong_payload_length(self) -> None:
        # 8 = the pre-P3 length: must be refused (fail-closed, no reinterpretation)
        for length in (0, 8, 11):
            with self.subTest(length=length):
                with self.assertRaises(PayloadError):
                    encode_item_task_frame(
                        task_id=7,
                        frame_seq=11,
                        payload=bytes(length),
                    )


if __name__ == "__main__":
    unittest.main()
