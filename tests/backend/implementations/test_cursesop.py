from pytest import fixture
from tests._utilities import MockSerial, mock_serial
from unittest.mock import MagicMock, patch
from typing import List
from array import array
import logging

CLASS_PATH = "kvm_serial.backend.implementations.cursesop"


class MockCursesError(Exception):
    """A mock error for curses.error"""


class MockTerminal(MagicMock):
    """Mock class for curses mock_term"""

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
            raise MockCursesError("no input")
        return self._keys_to_return.pop(0)

    def set_keys(self, keys: List[str | bytes]):
        """Set up a sequence of keys to be returned"""
        self._keys_to_return = list(keys)


@fixture
def sys_modules_patch():
    curses = MagicMock()
    curses.error = MockCursesError
    return {
        "curses": curses,
        "serial": MagicMock(),
    }


@fixture
def mock_term():
    """Get a mock terminal for testing curses"""
    return MockTerminal()


@patch("serial.Serial", MockSerial)
class TestCursesOperation:

    def _get_op_unsafe(self, mock_ser):
        """
        UNSAFE method to get CursesOp implementation
        Use fixture if in doubt.
        """
        from kvm_serial.backend.implementations.cursesop import CursesOp

        op = CursesOp(mock_ser)
        op.hid_serial_out = MagicMock()
        return op

    @fixture
    def op(self, mock_serial, sys_modules_patch):
        with (
            patch.dict("sys.modules", sys_modules_patch),
            patch("kvm_serial.utils.ascii_to_scancode") as mock_ascii,
            patch("kvm_serial.utils.scancode_to_ascii") as mock_scancode,
            patch("kvm_serial.utils.build_scancode") as mock_build,
        ):
            op = self._get_op_unsafe(mock_serial)

            # Store the mocked utils on the op object (a hack!)
            # We *have* to patch kvm_serial.utils here, as it's next to impossible to patch later
            setattr(op, "_mock_ascii", mock_ascii)
            setattr(op, "_mock_scancode", mock_scancode)
            setattr(op, "_mock_build", mock_build)

            return op

    def test_cursesop_instantiation(self, op, sys_modules_patch):
        with (
            patch.dict("sys.modules", sys_modules_patch),
            patch(f"{CLASS_PATH}.curses.wrapper") as mock_curses,
        ):
            assert op.name == "curses"
            mock_curses.return_value = True
            op.run()

    def test_cursesop_input_loop(self, op, sys_modules_patch, mock_term):
        with patch.dict("sys.modules", sys_modules_patch):

            # Patch _parse_key to return True on first iteration, then False
            with patch.object(op, "_parse_key") as patched:
                patched.side_effect = [True, False]  # Iterator
                op._input_loop(mock_term)
                assert patched.call_count == 2

            # Verify terminal was properly initialized
            mock_term.nodelay.assert_called()
            mock_term.clear.assert_called()
            mock_term.keypad.assert_called()
            mock_term.addstr.assert_called()

    def test_cursesop_parse_key_read_terminal(self, op, sys_modules_patch, mock_term):
        """Test sending MODIFIER_CODES (strings) to hid_serial_out"""

        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.implementations.cursesop import MODIFIER_CODES

            # Check the verbose debug log on line 111
            old_level = logging.root.level
            logging.root.level = logging.DEBUG

            # Iterate through the modifiers list
            for code in MODIFIER_CODES:
                mock_term.reset_mock()
                mock_term.set_keys([code])
                scancode = array("B", [0, 0, MODIFIER_CODES[code], 0, 0, 0, 0, 0])
                op._mock_build.return_value = scancode

                op._parse_key(mock_term)

                mock_term.getkey.assert_called()
                assert op.sc == scancode

            logging.root.level = old_level

            # Test a single key
            scancode = array("B", [0, 0, 0x4A, 0, 0, 0, 0, 0])
            mock_term.set_keys(["KEY_HOME"])
            op._mock_build.return_value = scancode
            op._parse_key(mock_term)
            mock_term.getkey.assert_called()
            assert op.sc == scancode

    def test_cursesop_parse_key_send_existing_scancode(self, op, sys_modules_patch, mock_term):
        """Send a scancode, and check object state afterwards"""
        with patch.dict("sys.modules", sys_modules_patch):
            # terminal has *no keys set* (no mock_term.set_keys(['a'])) for this test
            # Scancode for letter 'a'
            scancode = array("B", [0, 0, 0x04, 0, 0, 0, 0, 0])
            op.sc = scancode
            returnval = op._parse_key(mock_term)

            assert op.sc == None
            assert returnval == True
            op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))
            op.hid_serial_out.release.assert_called_once()

    def test_cursesop_no_input(self, op, sys_modules_patch, mock_term):
        with (
            patch.dict("sys.modules", sys_modules_patch),
            patch(f"{CLASS_PATH}.curses.napms") as mock_napms,
        ):
            returnval = op._parse_key(mock_term)

            assert returnval == True
            mock_napms.assert_called_with(100)
            mock_napms.assert_called_once()

    def test_cursesop_parse_key_single_ascii(self, op, sys_modules_patch, mock_term):
        """Send a scancode, and check object state afterwards"""

        key = "a"
        scancode = array("B", [0, 0, 0x04, 0, 0, 0, 0, 0])

        with patch.dict("sys.modules", sys_modules_patch):
            mock_term.set_keys([key])
            op._mock_ascii.return_value = scancode
            op._mock_build.return_value = scancode
            returnval = op._parse_key(mock_term)

            assert returnval == True
            assert op.sc == scancode
            mock_term.addstr.assert_called_once()
            op._mock_ascii.assert_called_with(key)

    def test_cursesop_parse_key_control_characters(self, op, sys_modules_patch, mock_term):
        """Send a control character, and check object state afterwards"""
        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.implementations.cursesop import CONTROL_CHARACTERS

            # Also hit the verbose debug log on line 146 in this test, as a bonus
            old_level = logging.root.level
            logging.root.level = logging.DEBUG

            # Test ^Q
            key = b"\x11"
            mock_term.set_keys([key])

            returnval = op._parse_key(mock_term)
            assert returnval == True
            op._mock_build.assert_called_with(CONTROL_CHARACTERS[ord(key)], 0x1)

            logging.root.level = old_level

            # Test ESC
            key = b"\x1b"
            mock_term.set_keys([key])

            returnval = op._parse_key(mock_term)
            assert returnval == False
            op._mock_build.assert_called_with(CONTROL_CHARACTERS[ord(key)], 0x1)

    def test_cursesop_parse_key_errors(self, op, sys_modules_patch, mock_term):
        """Test various errors which can be raised are handled correctly"""
        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.implementations.cursesop import MODIFIER_CODES

            # Test addwstr (L160)
            mock_term.getkey.side_effect = MockCursesError("addwstr")
            returnval = op._parse_key(mock_term)
            mock_term.clear.assert_called_once()
            assert returnval == True
            op.sc = None

            # Test logging the error otherwise
            mock_term.getkey.reset_mock()
            mock_term.getkey.side_effect = MockCursesError("something-else")
            returnval = op._parse_key(mock_term)
            mock_term.addstr.assert_called_once()
            mock_term.clear.assert_called_once()
            assert returnval == True
            op.sc = None

            # Test KeyError handling
            mock_term.addstr.reset_mock()
            mock_term.getkey.reset_mock()
            mock_term.getkey.side_effect = None
            mock_term.getkey.return_value = "nonexistent_key"
            with patch.dict(MODIFIER_CODES, {}, clear=True):
                returnval = op._parse_key(mock_term)
                mock_term.addstr.assert_called()
                assert "Ordinal missing" in str(mock_term.addstr.call_args_list[0])
                assert returnval == True

            # Test ValueError handling
            mock_term.addstr.reset_mock()
            mock_term.getkey.reset_mock()
            mock_term.getkey.return_value = "A"

            op._mock_ascii.side_effect = ValueError
            returnval = op._parse_key(mock_term)
            op._mock_ascii.side_effect = None
            mock_term.addstr.assert_called()
            assert returnval == True

            # Test KeyboardInterrupt handling does not break
            mock_term.getkey.side_effect = KeyboardInterrupt
            returnval = op._parse_key(mock_term)
            assert returnval == True

    def test_legacy_main_curses(self, sys_modules_patch, mock_serial):
        """
        Test that main_curses instantiates CursesOp, calls run, and returns None.
        Mocks:
            - CursesOp: Patched so instantiation and run can be tracked
        Asserts:
            - CursesOp instantiated with the correct argument
            - run() called once
            - main_curses returns None
        """
        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.implementations import cursesop as cursesop_mod

            with patch.object(cursesop_mod, "CursesOp") as mock_op:
                mock_op.return_value.run.return_value = None
                assert cursesop_mod.main_curses(mock_serial) is None
                mock_op.assert_called_once_with(mock_serial)
                mock_op.return_value.run.assert_called_once()
