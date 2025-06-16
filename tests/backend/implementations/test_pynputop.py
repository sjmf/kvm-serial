import sys
from unittest.mock import patch, MagicMock
from tests._utilities import MockSerial, mock_serial

# Some modules must be patched before importing (see test_control.py)
@patch.dict(sys.modules, {
    'pynput.keyboard.Key': MagicMock(),
    'pynput.keyboard.KeyCode': MagicMock(),
    'pynput.keyboard.Listener': MagicMock()
})
@patch("serial.Serial", MockSerial)
class TestPynputOperation:
    def test_name_property(self, mock_serial):
        from kvm_serial.backend.implementations.pynputop import PynputOp
        """Test that the name property returns 'pynput'"""
        op = PynputOp(mock_serial)
        assert op.name == "pynput"
