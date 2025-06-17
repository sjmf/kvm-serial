from unittest.mock import patch
from kvm_serial.backend.keyboard import KeyboardListener
from tests._utilities import MockSerial, mock_serial


class TestKeyboard:
    @patch("serial.Serial", MockSerial)
    def test_keyboard_listener(self, mock_serial):
        listener = KeyboardListener(mock_serial)

    # TODO: Implement further tests
