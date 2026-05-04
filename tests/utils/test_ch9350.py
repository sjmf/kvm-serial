import pytest
from unittest.mock import patch
from kvm_serial.utils.ch9350 import (
    CH9350Comm,
    DEFAULT_KBD_PID,
    DEFAULT_MOUSE_PID,
    HEADER,
    _parse_frames,
)

from tests._utilities import MockSerial, mock_serial


class TestCH9350Comm:
    """
    Test suite for CH9350Comm — verifies CH9350L wire-level packet framing
    across all four working states. State 1 is reached internally via the
    state-0 handshake and is not user-selectable from the constructor.
    """

    @patch("serial.Serial", MockSerial)
    def test_init_rejects_unsupported_state(self, mock_serial):
        """Constructor refuses states outside the supported range; state 1
        is rejected because it's reached via the state-0 handshake, not
        user-selectable."""
        for unsupported in (1, 5, -1):
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

    # ----------------------------------------------------- state 0/1 builders

    @patch("serial.Serial", MockSerial)
    def test_state0_kbd_frame_format(self, mock_serial):
        """
        State 0 keyboard frame:
            HEADER + 0x88 + LEN + SER + RID + [mod rsvd k0..k5] + CTR + CTRSUM
        Per-frame counter starts at 0 and increments; CTRSUM = (CTR + sum(hid)) & 0xFF.
        """
        dc = CH9350Comm(mock_serial, state=0)

        # First send: 'a' (0x04) with LSHIFT (0x02). hid sum = 0x01+0x02+0+0x04 = 7.
        dc.send_scancode(bytes([0x02, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00]))
        mock_serial.write.assert_called_once_with(
            b"\x57\xab\x88\x0c\x13\x01\x02\x00\x04\x00\x00\x00\x00\x00\x00\x07"
        )
        mock_serial.write.reset_mock()

        # Second send: same scancode, but CTR=1 → CTRSUM=(1+7)&0xFF=0x08.
        dc.send_scancode(bytes([0x02, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00]))
        mock_serial.write.assert_called_once_with(
            b"\x57\xab\x88\x0c\x13\x01\x02\x00\x04\x00\x00\x00\x00\x00\x01\x08"
        )

    @patch("serial.Serial", MockSerial)
    def test_state1_kbd_cmd_byte_only_difference(self, mock_serial):
        """State 1 keyboard frames differ from state 0 only in the cmd byte
        (0x83 vs 0x88) — payload, SER, CTR are unchanged."""
        dc = CH9350Comm(mock_serial, state=0)
        dc.state = CH9350Comm.STATE_1  # simulate post-handshake transition

        dc.send_scancode(bytes([0x02, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00]))
        mock_serial.write.assert_called_once_with(
            b"\x57\xab\x83\x0c\x13\x01\x02\x00\x04\x00\x00\x00\x00\x00\x00\x07"
        )

    @patch("serial.Serial", MockSerial)
    def test_state0_mouse_frame_format(self, mock_serial):
        """
        State 0 relative mouse frame:
            HEADER + 0x88 + LEN + SER + RID + [btn dx dy wheel] + CTR + CTRSUM
        """
        dc = CH9350Comm(mock_serial, state=0)
        dc.send_mouse_relative(0x01, 5, -3, 1)
        # data sum: 0x01 + 0x01 + 0x05 + 0xFD + 0x01 = 0x105 & 0xFF = 0x05
        mock_serial.write.assert_called_once_with(
            b"\x57\xab\x88\x08\x22\x01\x01\x05\xfd\x01\x00\x05"
        )

    @patch("serial.Serial", MockSerial)
    def test_device_connect_frame_format(self, mock_serial):
        """0x81 frame: HEADER + 0x81 + PORT + LEN(LE) + DESC + PID + CHK."""
        dc = CH9350Comm(mock_serial, state=0)
        # CHK = (sum(desc) + sum(pid)) & 0xFF = (0xab + 0xcd + 0x01 + 0x02) & 0xFF = 0x7b
        frame = dc._build_device_connect_frame(b"\xab\xcd", port_id=0x00, device_pid=b"\x01\x02")
        assert frame == b"\x57\xab\x81\x00\x02\x00\xab\xcd\x01\x02\x7b"

    @patch("serial.Serial", MockSerial)
    def test_device_connect_frame_rejects_bad_pid(self, mock_serial):
        dc = CH9350Comm(mock_serial, state=0)
        with pytest.raises(ValueError):
            dc._build_device_connect_frame(b"\xab", port_id=0x00, device_pid=b"\x01")

    def test_parse_frames_basic(self):
        """_parse_frames extracts complete (cmd, payload) tuples, leaves
        partials in the buffer, and surfaces pre-header bytes as cmd=-1."""
        # Single complete 0x12 keep-alive (8-byte payload).
        buf = bytearray(HEADER + b"\x12" + b"\x40\x00\x03\x15\x00\x07\xac\x20")
        frames, remaining = _parse_frames(buf)
        assert frames == [(0x12, b"\x40\x00\x03\x15\x00\x07\xac\x20")]
        assert remaining == bytearray()

        # Pre-header noise + a 0x86 frame (no payload).
        buf = bytearray(b"\xff\x00" + HEADER + b"\x86")
        frames, remaining = _parse_frames(buf)
        assert frames == [(-1, b"\xff\x00"), (0x86, b"")]
        assert remaining == bytearray()

        # 0x88 length-prefixed: payload[0]=LEN means total payload = 1+LEN.
        buf = bytearray(HEADER + b"\x88\x04\xaa\xbb\xcc\xdd")
        frames, remaining = _parse_frames(buf)
        assert frames == [(0x88, b"\x04\xaa\xbb\xcc\xdd")]
        assert remaining == bytearray()

        # Partial frame: header + cmd + incomplete payload — leave in buffer.
        buf = bytearray(HEADER + b"\x12\x40\x00")
        frames, remaining = _parse_frames(buf)
        assert frames == []
        assert remaining == bytearray(HEADER + b"\x12\x40\x00")

    @patch("serial.Serial", MockSerial)
    def test_handle_frame_pid_ack_transitions_to_state1(self, mock_serial):
        """When the UC's 0x12 reflects every announced PID, _handle_frame
        moves state 0 → state 1 and sets _uc_seen."""
        dc = CH9350Comm(mock_serial, state=0)
        assert dc.state == CH9350Comm.STATE_0
        assert not dc._uc_seen.is_set()

        # Payload with both PIDs matching the defaults → all-acked.
        payload = DEFAULT_MOUSE_PID + DEFAULT_KBD_PID + b"\x00\x07\xac\x20"
        dc._handle_frame(0x12, payload)

        assert dc._uc_seen.is_set()
        assert dc.state == CH9350Comm.STATE_1
        assert dc._uc_p1 == DEFAULT_MOUSE_PID
        assert dc._uc_p2 == DEFAULT_KBD_PID

    @patch("serial.Serial", MockSerial)
    def test_handle_frame_pid_drop_triggers_reattach(self, mock_serial):
        """In state 1, a 0x12 with cleared PIDs (target-side replug) drops
        us back to state 0 and signals _reattach_needed."""
        dc = CH9350Comm(mock_serial, state=0)
        # Bring us up to state 1 with full ack.
        dc._handle_frame(0x12, DEFAULT_MOUSE_PID + DEFAULT_KBD_PID + b"\x00\x07\xac\x20")
        assert dc.state == CH9350Comm.STATE_1
        assert not dc._reattach_needed.is_set()

        # UC clears PIDs to 00 00 → STATUS drops → reattach.
        dc._handle_frame(0x12, b"\x00\x00\x00\x00\x00\x04\xac\x20")
        assert dc.state == CH9350Comm.STATE_0
        assert dc._reattach_needed.is_set()

    @patch("serial.Serial", MockSerial)
    def test_handle_frame_ignores_short_or_irrelevant(self, mock_serial):
        """Non-0x12 frames and short 0x12 payloads are ignored (no state
        change, no exceptions)."""
        dc = CH9350Comm(mock_serial, state=0)

        dc._handle_frame(0x82, b"\xa3")  # heartbeat — ignored
        dc._handle_frame(0x12, b"\x00\x00")  # too short for PIDs
        assert dc.state == CH9350Comm.STATE_0
        assert not dc._uc_seen.is_set()

    @patch("serial.Serial", MockSerial)
    def test_init_rejects_bad_pid_length(self, mock_serial):
        """PIDs must be exactly 2 bytes."""
        with pytest.raises(ValueError):
            CH9350Comm(mock_serial, state=0, mouse_pid=b"\x40")
        with pytest.raises(ValueError):
            CH9350Comm(mock_serial, state=0, kbd_pid=b"\x03\x15\x00")

    @patch("serial.Serial", MockSerial)
    def test_start_stop_no_op_for_simple_states(self, mock_serial):
        """States 2/3/4 don't need a handshake, so start()/stop() do nothing."""
        for state in (2, 3, 4):
            dc = CH9350Comm(mock_serial, state=state)
            dc.start()  # no thread spawned
            assert dc._rx_thread is None
            assert dc._tx_thread is None
            dc.stop()  # no-op
