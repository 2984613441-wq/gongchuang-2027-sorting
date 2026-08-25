from __future__ import annotations

import unittest

from electrical_control.protocol import (
    Device,
    OuterFrame,
    PayloadError,
    crc16_modbus,
    decode_outer_frame,
    encode_outer_frame,
)


class Crc16ModbusTests(unittest.TestCase):
    def test_known_modbus_vector(self) -> None:
        self.assertEqual(0x4B37, crc16_modbus(b"123456789"))


class OuterFrameCodecTests(unittest.TestCase):
    def test_known_frame_matches_c_reference_bytes(self) -> None:
        frame = OuterFrame(
            version=0x01,
            sender=Device.RASPI,
            receiver=Device.STM32,
            task_id=0x1234,
            frame_seq=0x0007,
            command=0x21,
            payload=bytes.fromhex("AA BB CC"),
        )

        encoded = encode_outer_frame(frame)

        self.assertEqual(
            bytes.fromhex("A5 5A 01 02 03 12 34 00 07 21 00 03 AA BB CC B2 6F"),
            encoded,
        )

    def test_frame_round_trip_preserves_fields(self) -> None:
        frame = OuterFrame(
            version=0x01,
            sender=Device.RASPI,
            receiver=Device.STM32,
            task_id=0x1234,
            frame_seq=0x0055,
            command=0x25,
            payload=bytes.fromhex("01 00 47 0B 99 F4"),
        )

        decoded = decode_outer_frame(encode_outer_frame(frame))

        self.assertEqual(frame, decoded)

    def test_header_and_big_endian_layout_are_stable(self) -> None:
        frame = OuterFrame(0x01, Device.RASPI, Device.STM32, 0x1234, 0x0055, 0x25, b"\x01")
        encoded = encode_outer_frame(frame)

        self.assertEqual(0xA5, encoded[0])
        self.assertEqual(0x5A, encoded[1])
        self.assertEqual(0x01, encoded[2])
        self.assertEqual(0x02, encoded[3])
        self.assertEqual(0x03, encoded[4])
        self.assertEqual(0x12, encoded[5])
        self.assertEqual(0x34, encoded[6])
        self.assertEqual(0x00, encoded[7])
        self.assertEqual(0x55, encoded[8])
        self.assertEqual(0x25, encoded[9])
        self.assertEqual(0x00, encoded[10])
        self.assertEqual(0x01, encoded[11])

    def test_trailing_bytes_are_ignored(self) -> None:
        frame = OuterFrame(0x01, Device.RASPI, Device.STM32, 1, 1, 0x20, b"")
        encoded = encode_outer_frame(frame)

        decoded = decode_outer_frame(encoded + b"\x00\x00")

        self.assertEqual(frame, decoded)

    def test_bad_header_is_rejected(self) -> None:
        frame = OuterFrame(0x01, Device.RASPI, Device.STM32, 1, 1, 0x20, b"")
        encoded = bytearray(encode_outer_frame(frame))
        encoded[0] = 0x00

        with self.assertRaises(PayloadError):
            decode_outer_frame(encoded)

    def test_bad_version_is_rejected(self) -> None:
        frame = OuterFrame(0x01, Device.RASPI, Device.STM32, 1, 1, 0x20, b"")
        encoded = bytearray(encode_outer_frame(frame))
        encoded[2] = 0x02

        with self.assertRaises(PayloadError):
            decode_outer_frame(encoded)

    def test_bad_crc_is_rejected(self) -> None:
        frame = OuterFrame(0x01, Device.RASPI, Device.STM32, 1, 1, 0x20, b"")
        encoded = bytearray(encode_outer_frame(frame))
        encoded[-1] ^= 0xFF

        with self.assertRaises(PayloadError):
            decode_outer_frame(encoded)

    def test_short_frame_is_rejected(self) -> None:
        frame = OuterFrame(0x01, Device.RASPI, Device.STM32, 1, 1, 0x20, b"")
        encoded = encode_outer_frame(frame)

        with self.assertRaises(PayloadError):
            decode_outer_frame(encoded[:-1])

    def test_unknown_device_id_is_rejected(self) -> None:
        frame = OuterFrame(0x01, Device.RASPI, Device.STM32, 1, 1, 0x20, b"")
        encoded = bytearray(encode_outer_frame(frame))
        encoded[4] = 0x7F

        with self.assertRaises(PayloadError):
            decode_outer_frame(encoded)

    def test_encode_requires_frozen_version(self) -> None:
        frame = OuterFrame(0x02, Device.RASPI, Device.STM32, 1, 1, 0x20, b"")

        with self.assertRaises(PayloadError):
            encode_outer_frame(frame)


if __name__ == "__main__":
    unittest.main()
