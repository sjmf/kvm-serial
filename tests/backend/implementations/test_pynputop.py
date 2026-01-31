import pytest
from unittest.mock import patch, MagicMock
from tests._utilities import MockSerial, mock_serial
from array import array


# Do NOT import either kvm_serial.backend.implementations.pynputop, or pynput here.
# These NEED to be patched by @patch.dict, to prevent pynput from being imported.
# Some modules must also be patched before importing (see test_control.py)
@pytest.fixture
def sys_modules_patch():
    return {
        "pynput": MagicMock(),
        "pynput.keyboard": MagicMock(),
        "pynput.keyboard.Key": MagicMock(),
        "pynput.keyboard.KeyCode": MagicMock(),
        "pynput.keyboard.Listener": MagicMock(),
    }


class MockStopException(Exception):
    """Class used to patch StopException"""


class MockKeyCode:
    """Class which pretends to be a pynput KeyCode"""

    def __init__(self, char: str = ""):
        self.char = char


@patch("serial.Serial", MockSerial)
class TestPynputOperation:

    @pytest.fixture
    def key_maps(self, sys_modules_patch):
        """Fixture to provide modifier_keys, nonalpha_keys, MODIFIER_TO_VALUE, and KEYS_WITH_CODES."""
        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.implementations.pynputop import (
                MODIFIER_TO_VALUE,
                KEYS_WITH_CODES,
            )

            # Extract representations of keys object to a new dict to access them by name
            # This can be indexed by e.g. ['Key.ctrl']
            # type: ignore is because using the internal MagicMock function causes a pylance warning
            modifier_keys = {
                ".".join(key._extract_mock_name().split(".")[2:]): key  # type: ignore
                for key in MODIFIER_TO_VALUE.keys()
            }
            nonalpha_keys = {
                ".".join(key._extract_mock_name().split(".")[2:]): key  # type: ignore
                for key in KEYS_WITH_CODES.keys()
            }
            return {
                "modifier_keys": modifier_keys,
                "nonalpha_keys": nonalpha_keys,
                "MODIFIER_TO_VALUE": MODIFIER_TO_VALUE,
                "KEYS_WITH_CODES": KEYS_WITH_CODES,
            }

    @pytest.fixture
    def op(self, mock_serial, sys_modules_patch):
        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.implementations.pynputop import PynputOp

            op = PynputOp(mock_serial)
            op.hid_serial_out = MagicMock()
            return op

    def test_pynputop_name_property(self, op):
        """Test that the name property returns 'pynput'"""
        assert op.name == "pynput"

    def test_pynputop_run(self, op, sys_modules_patch):
        """Test the 'run' method on PynputOp object"""

        # I don't know if this is the "right" way to do this, but, it's a convenient way
        #   to access the MagicMock from the PYNPUT_MOCKS sys.modules patch.dict above.
        # Plus, eh, it works.
        with patch("sys.modules", sys_modules_patch):
            from pynput.keyboard import Listener
            from typing import cast

            mock_listener = cast(MagicMock, Listener)
            listener_instance = MagicMock()
            mock_listener.return_value.__enter__.return_value = listener_instance
            listener_instance.join.return_value = None

            op.run()
            listener_instance.join.assert_called_once()

    def test_pynputop_on_press_modifier(self, op, key_maps):
        """Test modifiers (e.g. ctrl, alt) passed to on_press"""

        # Test keypresses, being careful to reset the modifier_map afterwards.
        modifier_keys = key_maps["modifier_keys"]
        op.on_press(modifier_keys["alt"])
        scancode = array("B", [0x04, 0, 0, 0, 0, 0, 0, 0])
        op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))
        op.modifier_map = {}  # Reset keymap

        op.on_press(modifier_keys["ctrl"])
        scancode = array("B", [0x01, 0, 0, 0, 0, 0, 0, 0])
        op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))
        op.modifier_map = {}

        op.on_press(modifier_keys["ctrl"])
        op.on_press(modifier_keys["alt"])
        op.on_press(modifier_keys["shift_l"])
        scancode = array("B", [0x01 | 0x02 | 0x04, 0, 0, 0, 0, 0, 0, 0])
        op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))

    def test_pynputop_on_press_syskeys(self, op, key_maps):
        """Test system keys with codes are parsed correctly"""
        nonalpha_keys = key_maps["nonalpha_keys"]
        KEYS_WITH_CODES = key_maps["KEYS_WITH_CODES"]
        op.on_press(nonalpha_keys["enter"])
        scancode = array("B", [0, 0, 0x28, 0, 0, 0, 0, 0])
        op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))

        op.modifier_map = {}
        test_multiple = ["f1", "f2", "f3", "end", "tab"]
        scancode = array("B", [0, 0, 0xFF, 0, 0, 0, 0, 0])
        for k in test_multiple:
            op.on_press(nonalpha_keys[k])
            code = KEYS_WITH_CODES[nonalpha_keys[k]]
            scancode[2] = code
            op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))

    def test_pynputop_on_press_alphanumeric(self, op, key_maps, sys_modules_patch):
        """Test pressing single characters"""
        with patch("sys.modules", sys_modules_patch):
            from kvm_serial.utils import ascii_to_scancode, merge_scancodes

            modifier_keys = key_maps["modifier_keys"]
            # Test single characters
            for char in ["a", "l", "k", "q", "z"]:
                op.on_press(MockKeyCode(char=char))
                scancode = ascii_to_scancode(char)
                op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))

            # Test capitals (shift held)
            op.on_press(modifier_keys["shift_l"])
            shiftcode = array("B", [0x02, 0, 0, 0, 0, 0, 0, 0])
            for char in ["b", "t", "w", "u", "k"]:
                op.on_press(MockKeyCode(char=char))
                scancode = merge_scancodes([shiftcode, ascii_to_scancode(char)])
                op.hid_serial_out.send_scancode.assert_called_with(bytes(scancode))

    def test_pynputop_on_press_complex(self, op, key_maps, sys_modules_patch):
        """
        Complex PynputOp test case:
        Test presses, releases, and presses of syskeys and modifiers all together
        """
        with patch("sys.modules", sys_modules_patch):
            from kvm_serial.utils import ascii_to_scancode, merge_scancodes

            modifier_keys = key_maps["modifier_keys"]
            nonalpha_keys = key_maps["nonalpha_keys"]
            # Press shift_l, then 'a', then ctrl, then 'b', then release shift_l, then press 'c'
            shift = modifier_keys["shift_l"]
            ctrl = modifier_keys["ctrl"]
            enter = nonalpha_keys["enter"]
            tab = nonalpha_keys["tab"]
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

    def test_pynpyutop_exit_on_ctrl_esc(self, op, sys_modules_patch, key_maps):
        with patch.dict("sys.modules", sys_modules_patch):
            from pynput.keyboard import Listener

            # Patch StopException to be a real Exception for the test
            with (
                patch.object(Listener, "StopException", MockStopException),
                pytest.raises(MockStopException),
            ):
                op.on_press(key_maps["modifier_keys"]["ctrl"])
                op.on_press(key_maps["nonalpha_keys"]["esc"])
                op.on_release(key_maps["nonalpha_keys"]["esc"])

    def test_legacy_main_pynput(self, mock_serial, sys_modules_patch):
        """
        Test that main_pynput instantiates PynputOp, calls run, and returns None.
        Mocks:
            - PynputOp: Patched so instantiation and run can be tracked
        Asserts:
            - PynputOp instantiated with the correct argument
            - run() called once
            - main_pynput returns None
        """
        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.implementations import pynputop as pynputop_mod

            with patch.object(pynputop_mod, "PynputOp") as mock_op:
                mock_op.return_value.run.return_value = None
                assert pynputop_mod.main_pynput(mock_serial) is None
                mock_op.assert_called_once_with(mock_serial)
                mock_op.return_value.run.assert_called_once()
