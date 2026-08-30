"""Unit tests for PySerialLink (real UART SerialLink over pyserial).

No real UART is touched: the pyserial import is faked via sys.modules so the
constructor never opens a real port, and the port object is a unittest.mock.Mock
injected through the test-only _set_serial_for_test hook. Frames are built with
the frozen electrical_control.protocol.encode_outer_frame codec.
"""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import Mock, patch

from electrical_control.protocol import (
    Command,
    Device,
    OuterFrame,
    VERSION,
    encode_outer_frame,
)
from electrical_control.rpi.serial_link_serial import MAX_PAYLOAD_LEN, PySerialLink


def make_frame(*, payload: bytes = b"") -> bytes:
    """Build one valid frozen outer frame (STM32 -> Pi, BARRIER_READY)."""
    return encode_outer_frame(
        OuterFrame(
            VERSION, Device.STM32, Device.RASPI, 7, 1, int(Command.BARRIER_READY), payload
        )
    )


class PySerialLinkTests(unittest.TestCase):
    def _make_link(self, ser: Mock) -> PySerialLink:
        """Construct a link whose constructor sees a fake 'serial' module."""
        fake_serial = types.ModuleType("serial")
        fake_serial.Serial = Mock(return_value=ser)
        with patch.dict(sys.modules, {"serial": fake_serial}):
            link = PySerialLink("COM9")
        link._set_serial_for_test(ser)
        return link

    def test_send_writes_raw_frame_to_serial_port(self) -> None:
        ser = Mock()
        link = self._make_link(ser)
        frame = make_frame()

        link.send(frame)

        ser.write.assert_called_once_with(frame)
        self.assertEqual(frame, ser.write.call_args.args[0])

    def test_receive_returns_complete_valid_frame(self) -> None:
        ser = Mock()
        frame = make_frame()
        ser.read.return_value = frame
        link = self._make_link(ser)

        self.assertEqual(frame, link.receive())

    def test_receive_skips_noise_and_resynchronizes_on_header(self) -> None:
        ser = Mock()
        frame = make_frame()
        ser.read.return_value = b"\x00\x7f\xa5\x11" + frame
        link = self._make_link(ser)

        self.assertEqual(frame, link.receive())

    def test_receive_returns_none_until_fragmented_frame_is_complete(self) -> None:
        ser = Mock()
        frame = make_frame()
        half = len(frame) // 2
        ser.read.side_effect = [frame[:half], frame[half:]]
        link = self._make_link(ser)

        self.assertIsNone(link.receive())
        self.assertEqual(frame, link.receive())

    def test_receive_discards_corrupt_frame(self) -> None:
        ser = Mock()
        frame = make_frame()
        corrupt = bytearray(frame)
        corrupt[-1] ^= 0xFF  # flip the CRC low byte
        ser.read.return_value = bytes(corrupt)
        link = self._make_link(ser)

        self.assertIsNone(link.receive())

    def test_receive_continues_scanning_after_corrupt_frame(self) -> None:
        ser = Mock()
        frame = make_frame()
        corrupt = bytearray(frame)
        corrupt[-1] ^= 0xFF
        ser.read.return_value = bytes(corrupt) + frame
        link = self._make_link(ser)

        self.assertEqual(frame, link.receive())

    def test_receive_discards_over_limit_data_len(self) -> None:
        ser = Mock()
        oversize = make_frame(payload=bytes(MAX_PAYLOAD_LEN + 1))
        ser.read.return_value = oversize
        link = self._make_link(ser)

        self.assertIsNone(link.receive())

    def test_receive_resynchronizes_after_over_limit_frame(self) -> None:
        ser = Mock()
        oversize = make_frame(payload=bytes(MAX_PAYLOAD_LEN + 1))
        frame = make_frame()
        ser.read.return_value = oversize + frame
        link = self._make_link(ser)

        self.assertEqual(frame, link.receive())

    def test_receive_returns_none_when_no_data_buffered(self) -> None:
        ser = Mock()
        ser.read.return_value = b""
        link = self._make_link(ser)

        self.assertIsNone(link.receive())
        self.assertIsNone(link.receive())

    def test_constructor_raises_clear_error_without_pyserial(self) -> None:
        with patch.dict(sys.modules, {"serial": None}):
            with self.assertRaises(ValueError) as ctx:
                PySerialLink("COM9")
        self.assertIn("pyserial", str(ctx.exception))
        self.assertIn("pip install pyserial", str(ctx.exception))

    def test_close_releases_port_and_is_idempotent(self) -> None:
        ser = Mock()
        link = self._make_link(ser)

        link.close()
        link.close()

        self.assertEqual(1, ser.close.call_count)
        self.assertIsNone(link.receive())


if __name__ == "__main__":
    unittest.main()
