import sys
from unittest.mock import patch, MagicMock
from collections import namedtuple
from tests._utilities import MockSerial, mock_serial

# Define a simple Monitor namedtuple for mocking get_monitors
Monitor = namedtuple("Monitor", ["x", "y", "width", "height", "is_primary"])

# Some modules must be patched before importing (see test_control.py)
@patch.dict(sys.modules, {
    'screeninfo': MagicMock(),
    'pynput.mouse': MagicMock(),
    'pynput.mouse.Button': MagicMock(),
    'pynput.mouse.Listener': MagicMock(),
})
@patch("kvm_serial.backend.mouse.get_monitors", return_value=[
    Monitor(x=0,y=0,width=1920,height=1080,is_primary=True)
])
class TestMouse:

    # Mock modules which include Pynput imports before importing
    # These DO NOT WORK headless, i.e. in Github Actions runner
    @patch("serial.Serial", MockSerial)
    @patch("kvm_serial.backend.mouse.DataComm")
    def test_mouse_listener(self, mock_datacomm, mock_serial):
        """Test basic MouseListener initialization"""
        from kvm_serial.backend.mouse import MouseListener
        
        listener = MouseListener(mock_serial)
        print(mock_datacomm.call_args_list)
        mock_datacomm.assert_called_once_with(mock_serial)
