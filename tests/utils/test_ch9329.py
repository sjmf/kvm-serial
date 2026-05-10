import pytest
from unittest.mock import patch
from kvm_serial.utils.ch9329 import CH9329Comm

from tests._utilities import MockSerial, mock_serial


class TestCH9329Comm:
    """Test suite for CH9329Comm — verifies CH9329 wire-level packet framing."""

    @patch("serial.Serial", MockSerial)
    def test_init(self, mock_serial):
        """Test initialization and basic operations of CH9329Comm.

        Tests:
        1. Proper initialization with mock serial port
        2. Sending a single character ('a') scancode
        3. Direct scancode sending
        4. Key release functionality

        Verifies correct packet formation including headers, address, command,
        data length, and checksum for each method called.
        """

        mock_serial.port = "/dev/ttyUSB0"
        mock_serial.is_open = True
        mock_serial.baudrate = 9600

        dc = CH9329Comm(mock_serial)

        assert dc.port == mock_serial

        # Scancode for letter 'a'
        char_to_send = bytes((0x0, 0x0, 0x4, 0x0, 0x0, 0x0, 0x0, 0x0))

        # Assert the output contains:
        # Header: 0x57 0xAB; Address: 0x00; Command 0x02;
        # Data length 0x08; Data packet (as above hex: 0000 4000 0000 0000)
        # Checksum 0x10
        dc.send(char_to_send)
        mock_serial.write.assert_called_once_with(
            b"\x57\xab\x00\x02\x08\x00\x00\x04\x00\x00\x00\x00\x00\x10"
        )
        mock_serial.write.reset_mock()

        dc.send_scancode(char_to_send)
        mock_serial.write.assert_called_once_with(
            b"\x57\xab\x00\x02\x08\x00\x00\x04\x00\x00\x00\x00\x00\x10"
        )
        mock_serial.write.reset_mock()

        dc.release()
        mock_serial.write.assert_called_once_with(
            b"\x57\xab\x00\x02\x08\x00\x00\x00\x00\x00\x00\x00\x00\x0c"
        )
        mock_serial.write.reset_mock()

    @patch("serial.Serial", MockSerial)
    def test_send_scancode_invalid_length(self, mock_serial):
        """Test error handling for invalid scancode length.

        Verifies:
        1. Sending a scancode that's too short returns False
        2. No write operation is performed on the serial port
        """
        dc = CH9329Comm(mock_serial)
        result = dc.send_scancode(bytes([0x0, 0x0]))  # Too short
        assert result is False
        mock_serial.write.assert_not_called()

    @patch("serial.Serial", MockSerial)
    @pytest.mark.parametrize("packet_size", [1, 8, 100, 255, 512])  # >255 results in OverflowError
    def test_packet_sizes(self, packet_size, mock_serial):
        """Test handling of different packet sizes.

        Args:
            packet_size: Size of the packet to test (1, 8, 100, or 255 bytes)
            mock_serial: Mock serial port fixture

        Verify that CH9329Comm can handle various packet sizes up to 255 bytes.
        Larger sizes result in OverflowError.
        """
        dc = CH9329Comm(mock_serial)
        data = b"x" * packet_size

        if packet_size < 256:
            dc.send(data)
            mock_serial.write.assert_called_once()
        else:
            with pytest.raises(OverflowError):
                dc.send(data)

    @patch("serial.Serial", MockSerial)
    def test_send_mouse_absolute(self, mock_serial):
        """Verify the wire format for absolute mouse reports (cmd=0x04).

        Payload is 7 bytes: marker(0x02) + buttons + xL xH + yL yH + wheel.
        Source x/y are scaled into the chip's 12-bit absolute space (0..4095);
        negative source coordinates (multi-monitor setups) wrap via 4096+dx.
        """
        dc = CH9329Comm(mock_serial)

        # All four cases use a 1920x1080 source surface. Scaling: dx maps to
        # 0x800 at x=960, wraps to 0x0F2A at x=-100. dy maps to 0x800 at y=540,
        # wraps to 0x0E84 at y=-100.
        cases = [
            # (x, y, expected wire bytes)
            (960, 540, b"\x57\xab\x00\x04\x07\x02\x00\x00\x08\x00\x08\x00\x1f"),
            (-100, 540, b"\x57\xab\x00\x04\x07\x02\x00\x2a\x0f\x00\x08\x00\x50"),
            (960, -100, b"\x57\xab\x00\x04\x07\x02\x00\x00\x08\x84\x0e\x00\xa9"),
            (-100, -100, b"\x57\xab\x00\x04\x07\x02\x00\x2a\x0f\x84\x0e\x00\xda"),
        ]
        for x, y, expected in cases:
            dc.send_mouse_absolute(0, x, y, 1920, 1080)
            mock_serial.write.assert_called_once_with(expected)
            mock_serial.write.reset_mock()

    @patch("serial.Serial", MockSerial)
    def test_send_mouse_relative(self, mock_serial):
        """Verify the wire format for relative mouse reports (cmd=0x05).

        Payload is 5 bytes: marker(0x01) + buttons + dx + dy + wheel,
        with dx/dy/wheel as 1-byte signed values (-127..+127).
        """
        dc = CH9329Comm(mock_serial)

        # Left button down, +5 right, -3 up, wheel +1.
        dc.send_mouse_relative(0x01, 5, -3, 1)
        mock_serial.write.assert_called_once_with(b"\x57\xab\x00\x05\x05\x01\x01\x05\xfd\x01\x11")
        mock_serial.write.reset_mock()

        # Out-of-range deltas clamp to the signed-byte limits (±127), not wrap.
        dc.send_mouse_relative(0, 200, -200, 200)
        mock_serial.write.assert_called_once_with(b"\x57\xab\x00\x05\x05\x01\x00\x7f\x81\x7f\x8c")

    @patch("serial.Serial", MockSerial)
    def test_packet_format_error(self, mock_serial):
        """Test ValueError is correctly raised on L40 when called with a bad header"""
        dc = CH9329Comm(mock_serial)

        # Error with packet format
        char_to_send = bytes((0x0))
        with pytest.raises(ValueError) as exc_info:
            dc.send(char_to_send, head=char_to_send)
            assert "CH9329 packet header MUST have" in str(exc_info.value)
