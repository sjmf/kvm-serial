import sys
import pytest
from unittest.mock import patch, MagicMock
from tests._utilities import MockSerial, mock_serial
from array import array


class MockKeyCode:
    """Class which pretends to be a pynput KeyCode"""

    def __init__(self, char: str = ""):
        self.char = char


# Do NOT import either kvm_serial.backend.implementations.pynputop, or pynput here.
# These NEED to be patched by @patch.dict, to prevent pynput from being imported.
# Some modules must also be patched before importing (see test_control.py)
PYNPUT_MOCKS = {
    "pynput": MagicMock(),
    "pynput.keyboard": MagicMock(),
    "pynput.keyboard.Key": MagicMock(),
    "pynput.keyboard.KeyCode": MagicMock(),
    "pynput.keyboard.Listener": MagicMock(),
}


@patch.dict(sys.modules, PYNPUT_MOCKS)
@patch("serial.Serial", MockSerial)
class TestPynputOperation:

    @patch.dict(sys.modules, PYNPUT_MOCKS)
    def setup_method(self, test_method):
        # configure self.attribute
        from kvm_serial.backend.implementations.pynputop import MODIFIER_TO_VALUE, KEYS_WITH_CODES

        # Extract representations of keys object to a new dict to access them by name
        # This can be indexed by e.g. ['Key.ctrl']
        # type: ignore is because using the internal MagicMock function causes a pylance warning
        self.modifier_keys = {
            ".".join(key._extract_mock_name().split(".")[2:]): key  # type: ignore
            for key in MODIFIER_TO_VALUE.keys()
        }
        self.nonalpha_keys = {
            ".".join(key._extract_mock_name().split(".")[2:]): key  # type: ignore
            for key in KEYS_WITH_CODES.keys()
        }

    @pytest.fixture
    @patch.dict(sys.modules, PYNPUT_MOCKS)
    def op(self, mock_serial):
        from kvm_serial.backend.implementations.pynputop import PynputOp

        op = PynputOp(mock_serial)
        op.hid_serial_out = MagicMock()
        return op

    def test_pynputop_name_property(self, op):
        """Test that the name property returns 'pynput'"""
        assert op.name == "pynput"

    def test_pynputop_run(self, op):
        """Test the 'run' method on PynputOp object"""

        # I don't know if this is the "right" way to do this, but, it's a convenient way
        #   to access the MagicMock from the PYNPUT_MOCKS sys.modules patch.dict above.
        # Plus, eh, it works.
        from pynput.keyboard import Listener
        from typing import cast

        mock_listener = cast(MagicMock, Listener)
        listener_instance = MagicMock()
        mock_listener.return_value.__enter__.return_value = listener_instance
        listener_instance.join.return_value = None

        op.run()
        listener_instance.join.assert_called_once()

    def test_pynputop_on_press_modifier(self, op):
        """Test modifiers (e.g. ctrl, alt) passed to on_press"""

        # Test keypresses, being careful to reset the modifier_map afterwards.
        op.on_press(self.modifier_keys["alt"])
        scancode = array("B", [0x04, 0, 0, 0, 0, 0, 0, 0])
        op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))
        op.modifier_map = {}  # Reset keymap

        op.on_press(self.modifier_keys["ctrl"])
        scancode = array("B", [0x01, 0, 0, 0, 0, 0, 0, 0])
        op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))
        op.modifier_map = {}

        op.on_press(self.modifier_keys["ctrl"])
        op.on_press(self.modifier_keys["alt"])
        op.on_press(self.modifier_keys["shift_l"])
        scancode = array("B", [0x01 | 0x02 | 0x04, 0, 0, 0, 0, 0, 0, 0])
        op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))

    def test_pynputop_on_press_syskeys(self, op):
        """Test system keys with codes are parsed correctly"""
        from kvm_serial.backend.implementations.pynputop import KEYS_WITH_CODES

        op.on_press(self.nonalpha_keys["enter"])
        scancode = array("B", [0, 0, 0x28, 0, 0, 0, 0, 0])
        op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))

        op.modifier_map = {}
        test_multiple = ["f1", "f2", "f3", "end", "tab"]
        scancode = array("B", [0, 0, 0xFF, 0, 0, 0, 0, 0])
        for k in test_multiple:
            op.on_press(self.nonalpha_keys[k])
            code = KEYS_WITH_CODES[self.nonalpha_keys[k]]
            scancode[2] = code
            op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))

    def test_pynputop_on_press_alphanumeric(self, op):
        """Test pressing single characters"""
        from kvm_serial.utils.utils import ascii_to_scancode, merge_scancodes

        # Test single characters
        for char in ["a", "l", "k", "q", "z"]:
            op.on_press(MockKeyCode(char=char))
            scancode = ascii_to_scancode(char)
            op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))

        # Test capitals (shift held)
        op.on_press(self.modifier_keys["shift_l"])
        shiftcode = array("B", [0x02, 0, 0, 0, 0, 0, 0, 0])
        for char in ["b", "t", "w", "u", "k"]:
            op.on_press(MockKeyCode(char=char))
            scancode = merge_scancodes([shiftcode, ascii_to_scancode(char)])
            op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))

    def test_pynputop_on_press_complex(self, op):
        """Complex PynputOp test case:
        Test presses, releases, and presses of syskeys and modifiers all together
        """
        from kvm_serial.utils.utils import ascii_to_scancode, merge_scancodes

        # Press shift_l, then 'a', then ctrl, then 'b', then release shift_l, then press 'c'
        shift = self.modifier_keys["shift_l"]
        ctrl = self.modifier_keys["ctrl"]
        enter = self.nonalpha_keys["enter"]
        tab = self.nonalpha_keys["tab"]

        # Press shift
        op.on_press(shift)
        shiftcode = array("B", [0x02, 0, 0, 0, 0, 0, 0, 0])
        assert shift in op.modifier_map

        # Press 'a' with shift held
        op.on_press(MockKeyCode(char="a"))
        scancode = merge_scancodes([shiftcode, ascii_to_scancode("a")])
        op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))

        # Press ctrl (now shift+ctrl held)
        op.on_press(ctrl)
        ctrl_shift = array("B", [0x02 | 0x01, 0, 0, 0, 0, 0, 0, 0])
        assert ctrl in op.modifier_map

        # Press 'b' with shift+ctrl held
        op.on_press(MockKeyCode(char="b"))
        scancode = merge_scancodes([ctrl_shift, ascii_to_scancode("b")])
        op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))

        # Press enter (system key)
        op.on_press(enter)
        # Should use the ctrl+shift modifier map and enter code
        scancode = merge_scancodes([ctrl_shift, array("B", [0, 0, 0x28, 0, 0, 0, 0, 0])])
        op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))

        # Release shift
        op.on_release(shift)
        assert shift not in op.modifier_map
        assert ctrl in op.modifier_map

        # Now only ctrl held
        ctrl_only = array("B", [0x01, 0, 0, 0, 0, 0, 0, 0])
        # Press tab with ctrl held
        op.on_press(tab)
        scancode = merge_scancodes([ctrl_only, array("B", [0, 0, 0x2B, 0, 0, 0, 0, 0])])
        op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))

        # Release ctrl
        op.on_release(ctrl)
        assert ctrl not in op.modifier_map
        # Press 'c' (no modifiers)
        op.on_press(MockKeyCode(char="c"))
        scancode = ascii_to_scancode("c")
        op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))

    def test_pynputop_unknown_key(self, op, caplog):
        """Test passing a key that is not a key to on_press
        The string "Key not found" should be printed to stderr
        """
        with caplog.at_level("ERROR"):
            op.on_press("I_AM_NOT_A_REAL_KEY")
        assert "Key not found" in caplog.text

    def test_pynputop_on_release(self, op):
        """Test function of on_release function:
        Set up a series of presses, and a release
        Only the released key should be removed from the modifier map
        """
        op.on_release(MockKeyCode(char="a"))
        op.hid_serial_out.release.assert_called()

    def test_pynpyutop_exit_on_ctrl_esc(self, op):
        from pynput.keyboard import Listener

        class MockStopException(Exception):
            pass

        # Patch StopException to be a real Exception for the test
        with patch.object(Listener, "StopException", MockStopException):
            with pytest.raises(MockStopException):
                op.on_press(self.modifier_keys["ctrl"])
                op.on_press(self.nonalpha_keys["esc"])
                op.on_release(self.nonalpha_keys["esc"])

    def test_legacy_main_pynput(self, mock_serial):
        """
        Test that main_pynput instantiates PynputOp, calls run, and returns None.
        Mocks:
            - PynputOp: Patched so instantiation and run can be tracked
        Asserts:
            - PynputOp instantiated with the correct argument
            - run() called once
            - main_pynput returns None
        """
        from kvm_serial.backend.implementations.pynputop import main_pynput

        with patch("kvm_serial.backend.implementations.pynputop.PynputOp") as mock_op:
            mock_op.return_value.run.return_value = None
            assert main_pynput(mock_serial) is None
            mock_op.assert_called_once_with(mock_serial)
            mock_op.return_value.run.assert_called_once()
