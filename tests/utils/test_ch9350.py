import pytest
from unittest.mock import patch
from kvm_serial.utils.ch9350 import CH9350Comm

from tests._utilities import MockSerial, mock_serial


class TestCH9350Comm:
    """
    Test suite for CH9350Comm — verifies CH9350L wire-level packet framing
    in working states 2, 3, and 4.

    State 0/1 (paired-mode descriptor handshake) is not yet implemented and
    will get its own test coverage when it lands.
    """

    @patch("serial.Serial", MockSerial)
    def test_init_rejects_unsupported_state(self, mock_serial):
        """Constructor refuses states outside the implemented range."""
        for unsupported in (0, 1, 5, -1):
            with pytest.raises(ValueError):
                CH9350Comm(mock_serial, state=unsupported)

    @patch("serial.Serial", MockSerial)
    def test_send_scancode_wire_format(self, mock_serial):
        """
        Keyboard frame is identical across states 2/3/4: HEADER + 0x01 +
        the 8-byte HID boot report. Verify on each state, plus length
        rejection and release().
        """
        # Scancode for letter 'a' (USB HID code 0x04 in the third byte).
        scancode = bytes((0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00))
        expected = b"\x57\xab\x01\x00\x00\x04\x00\x00\x00\x00\x00"

        for state in (2, 3, 4):
            dc = CH9350Comm(mock_serial, state=state)
            mock_serial.write.reset_mock()

            assert dc.send_scancode(scancode) is True
            mock_serial.write.assert_called_once_with(expected)
            mock_serial.write.reset_mock()

            # release() emits the all-zeros HID report.
            assert dc.release() is True
            mock_serial.write.assert_called_once_with(
                b"\x57\xab\x01\x00\x00\x00\x00\x00\x00\x00\x00"
            )
            mock_serial.write.reset_mock()

            # Short input is rejected without writing.
            assert dc.send_scancode(b"\x00\x00") is False
            mock_serial.write.assert_not_called()

    @patch("serial.Serial", MockSerial)
    def test_state2_relative_wire_format(self, mock_serial):
        """
        State 2 emits 7-byte 0x02 frames:
            HEADER + 0x02 + btn + dx + dy + wheel
        dx/dy/wheel are 1-byte signed; out-of-range values clamp to ±127.
        """
        dc = CH9350Comm(mock_serial, state=2)

        dc.send_mouse_relative(0, 5, -3, 1)
        mock_serial.write.assert_called_once_with(b"\x57\xab\x02\x00\x05\xfd\x01")
        mock_serial.write.reset_mock()

        # Out-of-range values clamp: -200 → -127 (0x81), 200 → 127 (0x7F).
        dc.send_mouse_relative(0x01, -200, 200, -200)
        mock_serial.write.assert_called_once_with(b"\x57\xab\x02\x01\x81\x7f\x81")

    @patch("serial.Serial", MockSerial)
    def test_state2_absolute_translates_to_relative_delta(self, mock_serial):
        """
        State 2 has no absolute path on the wire. send_mouse_absolute calls
        emit relative deltas computed against the previous absolute call.
        First call's prior position defaults to (0, 0).
        """
        dc = CH9350Comm(mock_serial, state=2)

        # First absolute call: delta from origin → dx=10, dy=20.
        dc.send_mouse_absolute(0, 10, 20, 1920, 1080)
        mock_serial.write.assert_called_once_with(b"\x57\xab\x02\x00\x0a\x14\x00")
        mock_serial.write.reset_mock()

        # Subsequent call: delta from (10,20) → (15,22) is dx=5, dy=2.
        dc.send_mouse_absolute(0, 15, 22, 1920, 1080)
        mock_serial.write.assert_called_once_with(b"\x57\xab\x02\x00\x05\x02\x00")

    @patch("serial.Serial", MockSerial)
    def test_state3_absolute_wire_format(self, mock_serial):
        """
        States 3/4 emit 10-byte 0x04 frames:
            HEADER + 0x04 + 0x01 + btn + xL xH + yL yH + wheel
        x and y scale to the chip's unsigned 16-bit space (0..0xFFFF).
        """
        dc = CH9350Comm(mock_serial, state=3)

        # Centre of a 1920x1080 surface scales to 0x7FFF in both axes.
        dc.send_mouse_absolute(0, 960, 540, 1920, 1080)
        mock_serial.write.assert_called_once_with(b"\x57\xab\x04\x01\x00\xff\x7f\xff\x7f\x00")
        mock_serial.write.reset_mock()

        # Origin → (0, 0).
        dc.send_mouse_absolute(0, 0, 0, 1920, 1080)
        mock_serial.write.assert_called_once_with(b"\x57\xab\x04\x01\x00\x00\x00\x00\x00\x00")
        mock_serial.write.reset_mock()

        # Bottom-right corner → (0xFFFF, 0xFFFF).
        dc.send_mouse_absolute(0, 1920, 1080, 1920, 1080)
        mock_serial.write.assert_called_once_with(b"\x57\xab\x04\x01\x00\xff\xff\xff\xff\x00")

    @patch("serial.Serial", MockSerial)
    def test_state3_relative_re_emits_last_position(self, mock_serial):
        """
        State 3/4: send_mouse_relative carries no positional info on the
        wire. We re-emit the last known absolute position with the new
        button/wheel state — that's how clicks and scroll events reach the
        target via the absolute-only frame.
        """
        dc = CH9350Comm(mock_serial, state=3)

        # No prior absolute call: last position is (0, 0).
        dc.send_mouse_relative(0x01, 0, 0, 0)
        mock_serial.write.assert_called_once_with(b"\x57\xab\x04\x01\x01\x00\x00\x00\x00\x00")
        mock_serial.write.reset_mock()

        # Set the cursor to centre, then a button-only click re-uses that
        # position with the new button byte.
        dc.send_mouse_absolute(0, 960, 540, 1920, 1080)
        mock_serial.write.reset_mock()

        dc.send_mouse_relative(0x01, 0, 0, 0)
        mock_serial.write.assert_called_once_with(b"\x57\xab\x04\x01\x01\xff\x7f\xff\x7f\x00")
        mock_serial.write.reset_mock()

        # Scroll event: same position, wheel byte set.
        dc.send_mouse_relative(0, 0, 0, 1)
        mock_serial.write.assert_called_once_with(b"\x57\xab\x04\x01\x00\xff\x7f\xff\x7f\x01")

    @patch("serial.Serial", MockSerial)
    def test_state4_wire_identical_to_state3(self, mock_serial):
        """
        States 3 and 4 are wire-identical from the LC's perspective; the
        difference is purely in what the UC advertises on USB to the target
        host (HID Mouse vs HID Digitizers, selected by dipswitch).
        """
        dc3 = CH9350Comm(mock_serial, state=3)
        dc4 = CH9350Comm(mock_serial, state=4)

        dc3.send_mouse_absolute(0, 960, 540, 1920, 1080)
        state3_bytes = mock_serial.write.call_args[0][0]
        mock_serial.write.reset_mock()

        dc4.send_mouse_absolute(0, 960, 540, 1920, 1080)
        state4_bytes = mock_serial.write.call_args[0][0]

        assert state3_bytes == state4_bytes
