from unittest.mock import patch
from kvm_serial.backend.implementations.pyusb import PyUSBOp, get_usb_endpoints
from tests._utilities import MockSerial, mock_serial


class TestPyUSBOperation:
    @patch("serial.Serial", MockSerial)
    @patch("kvm_serial.backend.implementations.pyusb.get_usb_endpoints", return_value={})
    def test_name_property(self, mock_serial):
        """Test that the name property returns 'usb'"""
        op = PyUSBOp(mock_serial)
        assert op.name == "usb"

    # TODO: Implement further tests
