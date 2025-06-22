from tests._utilities import MockSerial, mock_serial
from unittest.mock import MagicMock, patch
from typing import List
from array import array
import logging
from curses import error as curses_error
from kvm_serial.backend.implementations.cursesop import CursesOp, MODIFIER_CODES, CONTROL_CHARACTERS


class MockTerminal(MagicMock):
    """Mock class for curses term"""

    def __init__(self):
        super().__init__()
        self.nodelay = MagicMock(return_value=None)
        self.clear = MagicMock(return_value=None)
        self.keypad = MagicMock(return_value=None)
        self.addstr = MagicMock(return_value=None)
        self._keys_to_return = []
        self.getkey = MagicMock(side_effect=self._getkey_impl)

    def _getkey_impl(self):
        """Simulate key input"""
        if not self._keys_to_return:
            raise curses_error("no input")
        return self._keys_to_return.pop(0)

    def set_keys(self, keys: List[str | bytes]):
        """Set up a sequence of keys to be returned"""
        self._keys_to_return = list(keys)


@patch("serial.Serial", MockSerial)
class TestCursesOperation:
    @patch("kvm_serial.backend.implementations.cursesop.curses.wrapper")
    def test_cursesop_instantiation(self, mock_curses, mock_serial):
        op = CursesOp(mock_serial)
        assert op.name == "curses"
        mock_curses.return_value = True
        op.run()

    @patch("kvm_serial.backend.implementations.cursesop.curses.raw")
    @patch("kvm_serial.backend.implementations.cursesop.curses.napms")
    def test_cursesop_input_loop(self, mock_napms, mock_raw, mock_serial):
        op = CursesOp(mock_serial)
        term = MockTerminal()

        # Patch _parse_key to return True on first iteration, then False
        with patch.object(CursesOp, "_parse_key") as patched:
            patched.side_effect = [True, False]  # Iterator
            op._input_loop(term)
            assert patched.call_count == 2

        # Verify terminal was properly initialized
        term.nodelay.assert_called()
        term.clear.assert_called()
        term.keypad.assert_called()
        term.addstr.assert_called()

    def test_cursesop_parse_key_read_terminal(self, mock_serial):
        """Test sending MODIFIER_CODES (strings) to hid_serial_out"""
        op = CursesOp(mock_serial)
        term = MockTerminal()

        # Check the verbose debug log on line 111
        old_level = logging.root.level
        logging.root.level = logging.DEBUG

        # Iterate through the modifiers list
        for code in MODIFIER_CODES:
            term.reset_mock()
            term.set_keys([code])
            op._parse_key(term)

            term.getkey.assert_called()
            assert op.sc == array("B", [0, 0, MODIFIER_CODES[code], 0, 0, 0, 0, 0])

        logging.root.level = old_level

        # Test a single key
        term.set_keys(["KEY_HOME"])
        op._parse_key(term)
        term.getkey.assert_called()
        assert op.sc == array("B", [0, 0, 0x4A, 0, 0, 0, 0, 0])

    def test_cursesop_parse_key_send_existing_scancode(self, mock_serial):
        """Send a scancode, and check object state afterwards"""
        op = CursesOp(mock_serial)
        term = MockTerminal()
        op.hid_serial_out = MagicMock()

        # Scancode for letter 'a'
        scancode = array("B", [0x02, 0, 0x04, 0, 0, 0, 0, 0])
        op.sc = scancode
        returnval = op._parse_key(term)

        assert op.sc == None
        assert returnval == True
        op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))
        op.hid_serial_out.release.assert_called_once()

    @patch("kvm_serial.backend.implementations.cursesop.curses.napms")
    def test_cursesop_no_input(self, mock_napms, mock_serial):
        op = CursesOp(mock_serial)
        term = MockTerminal()
        op.hid_serial_out = MagicMock()

        returnval = op._parse_key(term)

        assert returnval == True
        mock_napms.assert_called_with(100)
        mock_napms.assert_called_once()

    @patch("kvm_serial.backend.implementations.cursesop.ascii_to_scancode")
    def test_cursesop_parse_key_single_ascii(self, mock_ascii, mock_serial):
        """Send a scancode, and check object state afterwards"""
        op = CursesOp(mock_serial)
        term = MockTerminal()
        op.hid_serial_out = MagicMock()

        # Scancode for letter 'a'
        key = "A"
        scancode = array("B", [0x02, 0, 0x04, 0, 0, 0, 0, 0])
        term.set_keys([key])
        mock_ascii.return_value = scancode

        returnval = op._parse_key(term)

        assert returnval == True
        assert op.sc == scancode
        mock_ascii.assert_called_with(key)
        term.addstr.assert_called_once()

    @patch("kvm_serial.backend.implementations.cursesop.build_scancode")
    def test_cursesop_parse_key_control_characters(self, mock_build, mock_serial):
        """Send a control character, and check object state afterwards"""
        op = CursesOp(mock_serial)
        term = MockTerminal()
        op.hid_serial_out = MagicMock()

        # Also hit the verbose debug log on line 146 in this test, as a bonus
        old_level = logging.root.level
        logging.root.level = logging.DEBUG

        # Test ^Q
        key = b"\x11"
        term.set_keys([key])

        returnval = op._parse_key(term)
        assert returnval == True
        mock_build.assert_called_with(CONTROL_CHARACTERS[ord(key)], 0x1)

        logging.root.level = old_level

        # Test ESC
        key = b"\x1b"
        term.set_keys([key])

        returnval = op._parse_key(term)
        assert returnval == False
        mock_build.assert_called_with(CONTROL_CHARACTERS[ord(key)], 0x1)

    def test_cursesop_parse_key_errors(self, mock_serial):
        """Test various errors which can be raised are handled correctly"""

        op = CursesOp(mock_serial)
        term = MockTerminal()
        op.hid_serial_out = MagicMock()

        # Test addwstr (L160)
        term.getkey.side_effect = curses_error("addwstr")
        returnval = op._parse_key(term)
        term.clear.assert_called_once()
        assert returnval == True
        op.sc = None

        # Test logging the error otherwise
        term.getkey.reset_mock()
        term.getkey.side_effect = curses_error("something-else")
        returnval = op._parse_key(term)
        term.addstr.assert_called_once()
        term.clear.assert_called_once()
        assert returnval == True
        op.sc = None

        # Test KeyError handling
        term.addstr.reset_mock()
        term.getkey.reset_mock()
        term.getkey.side_effect = None
        term.getkey.return_value = "nonexistent_key"
        with patch.dict(MODIFIER_CODES, {}, clear=True):
            returnval = op._parse_key(term)
            term.addstr.assert_called()
            assert "Ordinal missing" in str(term.addstr.call_args_list[0])
            assert returnval == True

        # Test ValueError handling
        term.addstr.reset_mock()
        term.getkey.reset_mock()
        term.getkey.return_value = "A"
        with patch(
            "kvm_serial.backend.implementations.cursesop.ascii_to_scancode", side_effect=ValueError
        ):
            returnval = op._parse_key(term)
            term.addstr.assert_called()
            assert returnval == True

        # Test KeyboardInterrupt handling does not break
        term.getkey.side_effect = KeyboardInterrupt
        returnval = op._parse_key(term)
        assert returnval == True

    def test_legacy_main_curses(self, mock_serial):
        """
        Test that main_curses instantiates CursesOp, calls run, and returns None.
        Mocks:
            - CursesOp: Patched so instantiation and run can be tracked
        Asserts:
            - CursesOp instantiated with the correct argument
            - run() called once
            - main_curses returns None
        """
        from kvm_serial.backend.implementations.cursesop import main_curses

        with patch("kvm_serial.backend.implementations.cursesop.CursesOp") as mock_op:
            mock_op.return_value.run.return_value = None
            assert main_curses(mock_serial) is None
            mock_op.assert_called_once_with(mock_serial)
            mock_op.return_value.run.assert_called_once()
