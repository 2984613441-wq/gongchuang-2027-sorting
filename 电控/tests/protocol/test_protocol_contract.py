"""Executable regression contract inherited by protocol V0.4.

These tests intentionally describe the desired public API before production
code exists.  Run with ``PYTHONPATH=电控/src`` from the repository root.
"""

from __future__ import annotations

import unittest

from electrical_control.protocol import (
    Command,
    Device,
    DirectionError,
    DisplayAckContextValidator,
    DisplayAckMessage,
    DisplayAckReceived,
    DisplayContent,
    DomainEvent,
    Frame,
    PayloadError,
    ProtocolCodec,
    crc32_iso_hdlc,
    decode_display_ack_payload,
    encode_display_ack_payload,
    validate_direction,
)


class Crc32IsoHdlcTests(unittest.TestCase):
    def test_known_display_content_vector(self) -> None:
        canonical_content = bytes.fromhex("01 02 03 04 05")

        checksum = crc32_iso_hdlc(canonical_content)

        self.assertEqual(0x470B99F4, checksum)
        self.assertEqual(bytes.fromhex("47 0B 99 F4"), checksum.to_bytes(4, "big"))


class CriticalMessageDirectionTests(unittest.TestCase):
    STM32_TO_RASPI = (
        Command.BARRIER_READY,
        Command.MOTION_DONE,
        Command.ITEM_RESULT,
    )

    def test_stm32_status_events_accept_only_stm32_to_raspi(self) -> None:
        for command in self.STM32_TO_RASPI:
            with self.subTest(command=command):
                validate_direction(command, Device.STM32, Device.RASPI)

    def test_stm32_status_events_reject_reverse_direction(self) -> None:
        for command in self.STM32_TO_RASPI:
            with self.subTest(command=command):
                with self.assertRaises(DirectionError):
                    validate_direction(command, Device.RASPI, Device.STM32)

    def test_display_ack_accepts_only_raspi_to_stm32(self) -> None:
        validate_direction(Command.DISPLAY_ACK, Device.RASPI, Device.STM32)

        with self.assertRaises(DirectionError):
            validate_direction(Command.DISPLAY_ACK, Device.STM32, Device.RASPI)


class DisplayAckPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.content = DisplayContent(
            target_seq=1,
            class_id=2,
            image_id=3,
            success_count=4,
            result_code=5,
        )

    def test_five_fields_form_exact_canonical_digest_input(self) -> None:
        self.assertEqual(bytes.fromhex("01 02 03 04 05"), self.content.canonical_bytes())
        self.assertEqual(0x470B99F4, self.content.crc32)

    def test_display_ack_payload_round_trip_uses_network_byte_order(self) -> None:
        payload = encode_display_ack_payload(self.content, render_result=0x00)

        self.assertEqual(bytes.fromhex("01 00 47 0B 99 F4"), payload)
        decoded = decode_display_ack_payload(payload, expected_content=self.content)
        self.assertEqual(1, decoded.target_seq)
        self.assertEqual(0x00, decoded.render_result)
        self.assertEqual(0x470B99F4, decoded.content_crc32)

    def test_wrong_crc_is_rejected(self) -> None:
        wrong_crc_payload = bytes.fromhex("01 00 47 0B 99 F5")

        with self.assertRaises(PayloadError):
            decode_display_ack_payload(wrong_crc_payload, expected_content=self.content)

    def test_digest_of_wrong_field_order_is_rejected(self) -> None:
        wrong_order = bytes.fromhex("01 03 02 04 05")
        wrong_order_crc = crc32_iso_hdlc(wrong_order).to_bytes(4, "big")
        payload = bytes((1, 0)) + wrong_order_crc

        with self.assertRaises(PayloadError):
            decode_display_ack_payload(payload, expected_content=self.content)

    def test_little_endian_crc_output_is_rejected(self) -> None:
        little_endian_payload = bytes.fromhex("01 00 F4 99 0B 47")

        with self.assertRaises(PayloadError):
            decode_display_ack_payload(little_endian_payload, expected_content=self.content)

    def test_non_rendered_result_is_not_a_valid_display_ack(self) -> None:
        payload = bytes.fromhex("01 01 47 0B 99 F4")

        with self.assertRaises(PayloadError):
            decode_display_ack_payload(payload, expected_content=self.content)

    def test_wrong_target_is_rejected_even_when_digest_matches(self) -> None:
        payload = bytes.fromhex("02 00 47 0B 99 F4")

        with self.assertRaises(PayloadError):
            decode_display_ack_payload(payload, expected_content=self.content)


class ProtocolCodecBoundaryTests(unittest.TestCase):
    def test_codec_maps_valid_display_ack_to_wire_message_only(self) -> None:
        content = DisplayContent(1, 2, 3, 4, 5)
        frame = Frame(
            sender=Device.RASPI,
            receiver=Device.STM32,
            task_id=7,
            frame_seq=11,
            command=Command.DISPLAY_ACK,
            payload=encode_display_ack_payload(content, render_result=0x00),
        )

        message = ProtocolCodec().to_validated_message(frame)

        self.assertIsInstance(message, DisplayAckMessage)
        self.assertFalse(isinstance(message, DomainEvent))
        self.assertFalse(hasattr(message, "execute"))
        self.assertFalse(hasattr(message, "motion_action"))

    def test_context_validator_maps_wire_message_to_domain_event(self) -> None:
        content = DisplayContent(1, 2, 3, 4, 5)
        frame = Frame(
            sender=Device.RASPI,
            receiver=Device.STM32,
            task_id=7,
            frame_seq=11,
            command=Command.DISPLAY_ACK,
            payload=encode_display_ack_payload(content, render_result=0x00),
        )

        message = ProtocolCodec().to_validated_message(frame)
        event = DisplayAckContextValidator().to_domain_event(
            message,
            expected_display_content=content,
        )

        self.assertIsInstance(event, DisplayAckReceived)
        self.assertEqual(7, event.task_id)
        self.assertEqual(11, event.frame_seq)
        self.assertEqual(1, event.target_seq)
        self.assertTrue(event.crc_match)
        self.assertFalse(hasattr(event, "execute"))
        self.assertFalse(hasattr(event, "motion_action"))

    def test_codec_rejects_reverse_direction_before_domain_mapping(self) -> None:
        content = DisplayContent(1, 2, 3, 4, 5)
        reverse_frame = Frame(
            sender=Device.STM32,
            receiver=Device.RASPI,
            task_id=7,
            frame_seq=11,
            command=Command.DISPLAY_ACK,
            payload=encode_display_ack_payload(content, render_result=0x00),
        )

        with self.assertRaises(DirectionError):
            ProtocolCodec().to_validated_message(reverse_frame)


if __name__ == "__main__":
    unittest.main()
