"""Real UART SerialLink over pyserial for the Raspberry Pi host side.

PySerialLink implements the SerialLink contract (one complete outer frame per
send/receive) on top of a pyserial Serial port. Baud 115200 8N1 is the frozen
STM32 USART2 configuration (firmware main.c huart2: PA2/PA3, 115200, 8N1); the
port name is a deployment configuration and must be injected.

Byte-level frame-boundary parsing mirrors PiProtocolGateway.feed_byte
(gateway.py): the receiver resynchronizes on the 0xA5 0x5A header, reads the
declared data_len, and validates version/CRC through decode_outer_frame before
returning a frame. Corrupt or over-limit frames are dropped and scanning
continues at the next boundary.

pyserial is imported lazily inside __init__ so this module stays importable
(and unit-testable with mocks) on hosts without the optional dependency;
constructing the link without pyserial raises ValueError with an install hint.
"""

from __future__ import annotations

from electrical_control.protocol import (
    CRC_LEN,
    HEADER_0,
    HEADER_1,
    HEADER_LEN,
    PayloadError,
    decode_outer_frame,
)

# Defensive receive-side bound: a hostile or glitched data_len field (for
# example 0xFFFF) must never make the receiver wait for a frame that can never
# arrive. A declared payload length above this is treated as garbage and the
# scanner resynchronizes at the next header. The frozen wire format is
# unchanged; this is a local safety limit only.
MAX_PAYLOAD_LEN = 512

# Bytes requested per receive() poll. receive() never blocks longer than the
# configured timeout and returns at most one frame; a partial read simply stays
# in the internal buffer until a later poll completes it.
_READ_SIZE = 1024


class PySerialLink:
    """Real UART SerialLink over pyserial.

    Baud 115200 8N1 is the frozen STM32 USART2 configuration (firmware
    main.c huart2); the port name is a deployment configuration.
    """

    def __init__(self, port: str, *, baudrate: int = 115200, timeout: float = 0.05) -> None:
        try:
            import serial
        except ImportError as exc:
            raise ValueError(
                "PySerialLink requires the optional 'pyserial' package; "
                "install it in the target environment with: pip install pyserial"
            ) from exc
        self._ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=timeout,
        )
        self._rx: bytearray = bytearray()
        self._closed = False

    def send(self, frame: bytes) -> None:
        """Write one raw outer frame to the wire, unchanged."""
        self._ser.write(bytes(frame))

    def receive(self) -> bytes | None:
        """Return one complete validated outer frame, or None.

        Reads whatever the port currently has (bounded by the configured
        timeout), resynchronizes on the frame header, and returns the first
        frame that passes decode_outer_frame. Corrupt or over-limit frames are
        discarded and scanning continues at the next boundary; None is returned
        when no complete valid frame is buffered yet.
        """
        if self._closed:
            return None
        chunk = self._ser.read(_READ_SIZE)
        if chunk:
            self._rx.extend(chunk)
        return self._extract_frame()

    def close(self) -> None:
        """Release the serial port; idempotent."""
        if self._closed:
            return
        self._closed = True
        self._ser.close()

    def _set_serial_for_test(self, ser) -> None:
        """Test-only hook: replace the serial port with a mock object."""
        self._ser = ser

    def _extract_frame(self) -> bytes | None:
        """Scan the internal buffer for one valid frame (feed_byte semantics)."""
        rx = self._rx
        while True:
            if len(rx) < 2:
                return None
            if rx[0] != HEADER_0:
                rx.pop(0)
                continue
            if rx[1] != HEADER_1:
                rx.pop(0)
                continue
            if len(rx) < HEADER_LEN:
                return None
            data_len = int.from_bytes(rx[10:12], "big")
            if data_len > MAX_PAYLOAD_LEN:
                # Over-limit declared length: drop the header byte and resync.
                rx.pop(0)
                continue
            total = HEADER_LEN + data_len + CRC_LEN
            if len(rx) < total:
                return None
            raw = bytes(rx[:total])
            del rx[:total]
            try:
                decode_outer_frame(raw)
            except PayloadError:
                # Corrupt frame already consumed; keep scanning for the next
                # valid header/frame remaining in the buffer.
                continue
            return raw


__all__ = ["MAX_PAYLOAD_LEN", "PySerialLink"]
