from tests._utilities import MockSerial, mock_serial
from unittest.mock import MagicMock, patch
import curses
from kvm_serial.backend.implementations.cursesop import CursesOp, MODIFIER_CODES


class MockTerminal:
    """Mock class for curses term"""

    def __init__(self):
        self.nodelay = MagicMock(return_value=None)
        self.clear = MagicMock(return_value=None)
        self.keypad = MagicMock(return_value=None)
        self.addstr = MagicMock(return_value=None)
        self._keys_to_return = []

    def getkey(self):
        """Simulate key input"""
        if not self._keys_to_return:
            raise curses.error("no input")
        return self._keys_to_return.pop(0)

    def set_keys(self, keys):
        """Set up a sequence of keys to be returned"""
        self._keys_to_return = list(keys)


class TestCursesOperation:
    @patch("serial.Serial", MockSerial)
    @patch("kvm_serial.backend.implementations.cursesop.curses.wrapper")
    def test_cursesop_instantiation(self, mock_curses, mock_serial):
        op = CursesOp(mock_serial)
        assert op.name == "curses"
        mock_curses.return_value = True
        op.run()

    @patch("serial.Serial", MockSerial)
    @patch("kvm_serial.backend.implementations.cursesop.curses.raw")
    @patch("kvm_serial.backend.implementations.cursesop.curses.napms")
    def test_cursesop_input_loop(self, mock_napms, mock_raw, mock_serial):
        op = CursesOp(mock_serial)
        term = MockTerminal()

        # Patch _parse_key to return False immediately
        with patch.object(CursesOp, "_parse_key", return_value=False):
            op._input_loop(term)

        # Verify terminal was properly initialized
        assert term.nodelay.called
        assert term.clear.called
        assert term.keypad.called
        assert term.addstr.called

    # TODO: Implement further tests