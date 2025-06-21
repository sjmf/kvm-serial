import sys
import pytest
from unittest.mock import patch, MagicMock
from tests._utilities import MockSerial

# Mock usb.core and related classes to prevent actual USB operations
PYUSB_MOCKS = {
    "usb": MagicMock(),
    "usb.util": MagicMock(),
    "usb.core": MagicMock(),
    "usb.core.Device": MagicMock(),
    "usb.core.Endpoint": MagicMock(),
    "usb.core.Interface": MagicMock(),
    "kvm_serial.utils.utils": MagicMock(),
}


@patch.dict("sys.modules", PYUSB_MOCKS)
@patch("serial.Serial", MockSerial)
class TestPyUSBOperation:

    @pytest.fixture
    def mock_keyboard_device(self):
        class DummyDevice:
            def __init__(self):
                self.idVendor = 0xDEAD
                self.idProduct = 0xBEEF
                self.bDeviceClass = 0x00
                self.bDeviceSubClass = 0x00
                self.bDeviceProtocol = 0x00
                self.interfaces = []
                self._active_configuration = []

            def get_active_configuration(self):
                return self._active_configuration

        mock_endpoint = MagicMock()
        mock_endpoint.bEndpointAddress = 0x81  # IN endpoint
        mock_endpoint.bmAttributes = 0x03  # Interrupt transfer
        mock_endpoint.wMaxPacketSize = 8

        mock_interface = MagicMock()
        mock_interface.endpoints = [mock_endpoint]
        mock_interface.bInterfaceNumber = 0
        mock_interface.bInterfaceClass = 0x03  # HID Class
        mock_interface.bInterfaceSubClass = 0x01  # Boot Interface
        mock_interface.bInterfaceProtocol = 0x01  # Keyboard

        mock_device = DummyDevice()
        mock_device.interfaces = [mock_interface]
        mock_device._active_configuration = [mock_interface]

        return mock_device

    @pytest.fixture
    @patch.dict(sys.modules, PYUSB_MOCKS)
    @patch("kvm_serial.backend.implementations.pyusbop.get_usb_endpoints", return_value={})
    def op(self, mock_serial, mock_keyboard_device):
        from kvm_serial.backend.implementations.pyusbop import PyUSBOp

        op = PyUSBOp(mock_serial)
        op.hid_serial_out = MagicMock()
        op.hid_serial_out.send_scancode.return_value = True

        mock_endpoint = mock_keyboard_device.interfaces[0].endpoints[0]
        op.usb_endpoints = {"dead:beef": (mock_endpoint, mock_keyboard_device, 0)}

        return op

    def test_pyusbop_name_property(self, op):
        """Test that the name property returns 'usb'"""
        assert op.name == "usb"

    def test_get_usb_endpoints(self, mock_keyboard_device):
        """Test get_usb_endpoints function"""
        from kvm_serial.backend.implementations.pyusbop import get_usb_endpoints
        import usb.core, usb.util

        mock_interface = mock_keyboard_device.interfaces[0]
        mock_endpoint = mock_interface.endpoints[0]

        with (
            patch.object(usb.core, "find", return_value=[mock_keyboard_device]),
            patch.object(usb.util, "endpoint_direction", return_value=0x80),
            patch.object(usb.util, "endpoint_type", return_value=0x03),
            patch.object(usb.util, "find_descriptor", side_effect=[mock_interface, mock_endpoint]),
        ):
            endpoints = get_usb_endpoints()
            assert len(endpoints) == 1
            device_key = "dead:beef"
            assert device_key in endpoints
            endpoint, device, interface_number = endpoints[device_key]
            assert endpoint == mock_endpoint
            assert device == mock_keyboard_device
            assert interface_number == 0

            # Verify that find_descriptor was called correctly
            usb.core.find.assert_called_once_with(find_all=True)

    def test_get_usb_endpoints_no_backend_error(self):
        """Test get_usb_endpoints raises NoBackendError if no backend is found"""
        from kvm_serial.backend.implementations.pyusbop import get_usb_endpoints
        import usb.core

        class MockNoBackendError(BaseException):
            pass

        with (
            patch.object(usb.core, "find", side_effect=MockNoBackendError),
            patch.object(usb.core, "NoBackendError", MockNoBackendError),
        ):
            with pytest.raises(MockNoBackendError):
                get_usb_endpoints()

    def test_get_usb_endpoints_devices_none(self):
        """Test get_usb_endpoints returns empty dict if no devices found"""
        from kvm_serial.backend.implementations.pyusbop import get_usb_endpoints
        import usb.core

        with patch.object(usb.core, "find", return_value=None):
            endpoints = get_usb_endpoints()
            assert endpoints == {}

    def test_pyusbop_sleep_interval(self, op):
        """Test that _sleep_interval calls the callback with correct args and enforces the interval."""
        import time

        return_value = 42
        interval = 0.05

        callback = MagicMock(return_value=return_value)
        start = time.time()
        result = op._sleep_interval(callback, interval, "ultimate_answer")
        elapsed = time.time() - start

        callback.assert_called_once_with("ultimate_answer")
        assert result == return_value
        assert elapsed >= interval

    def test_parse_key(self, mock_keyboard_device, op):
        """Test _parse_key with mocked endpoint and scancode_to_ascii."""
        from kvm_serial.utils.utils import scancode_to_ascii as mock_ascii

        # Patch scancode_to_ascii to return 'a'
        mock_ascii.return_value = "a"

        # Mock endpoint
        mock_interface = mock_keyboard_device.interfaces[0]
        mock_endpoint = mock_interface.endpoints[0]

        # Simulate endpoint.read returning a scancode array
        scancode = [0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00]  # 'a' key
        mock_endpoint.read.return_value = scancode

        result = op._parse_key(mock_endpoint)
        assert result is True

        mock_endpoint.read.assert_called_once_with(mock_endpoint.wMaxPacketSize, timeout=100)
        assert mock_ascii.call_count == 2
        op.hid_serial_out.send_scancode.assert_called_once_with(scancode)

    def test_parse_key_usb_error(self, mock_keyboard_device, op):
        """Test _parse_key when endpoint.read raises usb.core.USBError."""
        import usb.core

        class MockUSBError(BaseException):
            errno = -1

        # Set up the endpoint to raise our MockUSBError
        mock_interface = mock_keyboard_device.interfaces[0]
        mock_endpoint = mock_interface.endpoints[0]
        mock_endpoint.read.side_effect = MockUSBError("mock error")

        with patch.object(usb.core, "USBError", MockUSBError):
            # On a general error, the class should raise the exception:
            with pytest.raises(MockUSBError):
                op._parse_key(mock_endpoint)

            # On error 60, it should return True to continue the loop
            mock_endpoint.read.side_effect.errno = 60
            result = op._parse_key(mock_endpoint)
            assert result is True
