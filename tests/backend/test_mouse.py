from unittest.mock import patch, MagicMock
from tests._utilities import MockSerial, mock_serial

# Mock modules which include Pynput imports before importing
# These DO NOT WORK headless, i.e. in Github Actions runner
with( 
    patch("kvm_serial.backend.mouse.Button", MagicMock()),
    patch("kvm_serial.backend.mouse.Listener", MagicMock()),
):
    from kvm_serial.backend.mouse import MouseListener


class TestMouse:
    @patch("kvm_serial.backend.mouse.Button")
    @patch("kvm_serial.backend.mouse.Listener")
    @patch("serial.Serial", MockSerial)
    @patch("kvm_serial.backend.mouse.DataComm")
    def test_mouse_listener(self, mock_datacomm, mock_serial, mock_button):
        """Test basic MouseListener initialization"""
        # Ensure DataComm mock is properly configured
        mock_datacomm.return_value = MagicMock()

        listener = MouseListener(mock_serial)

        # Verify DataComm was initialized with our mock serial
        mock_datacomm.assert_called_once_with(mock_serial)
