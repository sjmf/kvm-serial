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
    """
    Tests the PyUSBOp class
    """

    @pytest.fixture
    def mock_keyboard_device(self):
        """
        Creates and returns a mock USB keyboard device for testing purposes.
        The returned mock device simulates a USB HID keyboard with the following properties:
        - Vendor ID: 0xDEAD
        - Product ID: 0xBEEF
        - Device class, subclass, and protocol set to 0x00
        - Contains one interface representing a HID keyboard (class 0x03, subclass 0x01, protocol 0x01)
        - The interface includes a single IN interrupt endpoint (address 0x81, max packet size 8)
        - Kernel driver methods (`is_kernel_driver_active`, `detach_kernel_driver`, `attach_kernel_driver`) are mocked
        Returns:
            DummyDevice: A mock USB keyboard device object suitable for use in unit tests.
        """

        class DummyDevice:
            def __init__(self):
                self.idVendor = 0xDEAD
                self.idProduct = 0xBEEF
                self.bDeviceClass = 0x00
                self.bDeviceSubClass = 0x00
                self.bDeviceProtocol = 0x00
                self.interfaces = []
                self._active_configuration = []

                self.is_kernel_driver_active = MagicMock(return_value=True)
                self.detach_kernel_driver = MagicMock()
                self.attach_kernel_driver = MagicMock()

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
        """
        Fixture that creates and configures a PyUSBOp instance for testing.
        Args:
            mock_serial: Mocked serial interface to be passed to PyUSBOp.
            mock_keyboard_device: Mocked keyboard USB device with interfaces and endpoints.
        Returns:
            PyUSBOp: Configured PyUSBOp instance ready for use in tests.
        """

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
        """
        Test the `get_usb_endpoints` function to ensure it correctly discovers
        and returns USB endpoint information. This test mocks the USB device discovery process
        and endpoint/interface selection to simulate a keyboard device.

        It verifies that:
        - The function returns a dictionary with the expected device key.
        - The endpoint, device, and interface number are correctly extracted and returned.
        - The underlying USB library functions are called as expected.
        """
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
        """
        Tests that get_usb_endpoints raises the correct exception when no USB backend is available.
        Mocks the usb.core.find method to simulate a backend error and ensures that it propagates
        """
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
        """
        Test that get_usb_endpoints returns an empty dictionary when no USB devices are found.
        Patches usb.core.find to return None, simulating the absence of connected devices.
        Verifies the function returns an empty dict.
        """
        from kvm_serial.backend.implementations.pyusbop import get_usb_endpoints
        import usb.core

        with patch.object(usb.core, "find", return_value=None):
            endpoints = get_usb_endpoints()
            assert endpoints == {}

    def test_get_usb_endpoints_device_exceptions(self, caplog):
        """
        Test the `get_usb_endpoints` function to ensure exception
        handling where raised by USB devices.

        Verifies that:
          - Devices raising `AttributeError` or `TypeError` during configuration retrieval
             are skipped, and an appropriate info log message is recorded.
          - Devices raising `usb.core.USBError` (mocked here) are handled, and an error
             log message is recorded.
          - The function returns an empty dictionary when all devices raise exceptions.
          - Logging is performed at the correct levels for each exception type.

        The test uses mock device classes to simulate each exception scenario and asserts
        both the return value and the presence of expected log messages in `caplog`.
        """
        from kvm_serial.backend.implementations.pyusbop import get_usb_endpoints
        import usb.core

        class MockUSBError(Exception):
            errno = -1

        # Device that raises AttributeError
        class AttrErrorDevice:
            def get_active_configuration(self):
                raise AttributeError("mock attr error")

        # Device that raises TypeError
        class TypeErrorDevice:
            def get_active_configuration(self):
                raise TypeError("mock type error")

        # Device that raises usb.core.USBError
        class USBErrorDevice:
            manufacturer = "Test"
            product = "Device"

            def get_active_configuration(self):
                raise MockUSBError("mock usb error")

        devices = [AttrErrorDevice(), TypeErrorDevice(), USBErrorDevice()]
        with (
            patch.object(usb.core, "find", return_value=devices),
            patch.object(usb.core, "USBError", MockUSBError),
        ):
            with caplog.at_level("INFO"):
                endpoints = get_usb_endpoints()
            assert endpoints == {}
            # Should log info for AttributeError and TypeError
            assert any(
                "Skipping non-device or non-interface object" in record.message
                for record in caplog.records
            )
            # Should log error for USBError
            assert any(
                "USB error while processing device" in record.message for record in caplog.records
            )

    def test_pyusbop_sleep_interval(self, op):
        """
        Test that _sleep_interval calls the callback with correct args and enforces the interval.
        Ensures timing and callback behavior are correct.
        """
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
        """
        Test _parse_key with mocked endpoint and scancode_to_ascii
        Patches scancode_to_ascii to return 'a', and mocks endpoint read to return a scancode
         representing the key

        Assert:
        - The scancode_to_ascii utility is called to get the charater
        - _parse_key method returns True when a valid key is parsed.
        - The scancode_to_ascii function is called twice during the process.
        - The hid_serial_out.send_scancode method is called once with the correct scancode.
        - The call count for scancode_to_ascii is reset after the test.
        """
        from kvm_serial.utils.utils import scancode_to_ascii as mock_ascii

        # Patch scancode_to_ascii to return 'a'
        mock_ascii.return_value = "a"

        # Mock endpoint
        mock_endpoint = mock_keyboard_device.interfaces[0].endpoints[0]

        # Simulate endpoint.read returning a scancode array
        scancode = [0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00]  # 'a' key
        mock_endpoint.read.return_value = scancode

        assert op._parse_key(mock_endpoint) is True

        mock_endpoint.read.assert_called_once_with(mock_endpoint.wMaxPacketSize, timeout=100)
        assert mock_ascii.call_count == 2
        op.hid_serial_out.send_scancode.assert_called_once_with(scancode)

        # Reset the call_count for mock_ascii after the test
        mock_ascii.reset_mock()

    def test_parse_key_usb_error(self, mock_keyboard_device, op):
        """
        Test the behavior of _parse_key when USB endpoint read raises a USBError.

        Verifies:
        1. When a general usb.core.USBError is raised during endpoint.read,
            the exception is propagated by _parse_key.
        2. When the USBError has errno 60 (indicating a timeout),
            _parse_key returns True to signal that the loop should continue.
        """
        import usb.core

        class MockUSBError(Exception):
            errno = -1

        # Set up the endpoint to raise our MockUSBError
        mock_endpoint = mock_keyboard_device.interfaces[0].endpoints[0]
        mock_endpoint.read.side_effect = MockUSBError("mock error")

        with patch.object(usb.core, "USBError", MockUSBError):
            # On a general error, the class should raise the exception:
            with pytest.raises(MockUSBError):
                op._parse_key(mock_endpoint)

            # On error 60, it should return True to continue the loop
            mock_endpoint.read.side_effect.errno = 60
            assert op._parse_key(mock_endpoint) is True

    def test_parse_key_exit_combos(self, mock_keyboard_device, op, caplog):
        """
        Test `_parse_key` handles Ctrl+C and Ctrl+ESC key combinations.

        This test simulates USB keyboard input by providing scancodes to the mocked endpoint.
        Verifies:
          - When Ctrl+C is pressed: method returns True, logs a warning, and passes the scancode through.
          - When Ctrl+ESC is pressed: the method returns False, logs an exit warning, and does not continue processing.
          - The correct number of calls are made to scancode_to_ascii and serial output.
        """
        from kvm_serial.utils.utils import scancode_to_ascii as mock_ascii

        # Ctrl+C scancode: [0x01, ..., 0x06, ...]
        scancode = [0x01, 0x00, 0x06, 0x00, 0x00, 0x00, 0x00, 0x00]
        mock_endpoint = mock_keyboard_device.interfaces[0].endpoints[0]
        mock_endpoint.read.return_value = scancode

        with caplog.at_level("WARNING"):
            op.debounce = None
            assert op._parse_key(mock_endpoint) is True
            assert any(
                "Ctrl+C passed through. Use Ctrl+ESC to exit!" in record.message
                for record in caplog.records
            )

            # Verify that the method continued after Ctrl+C
            mock_endpoint.read.assert_called_once_with(mock_endpoint.wMaxPacketSize, timeout=100)
            assert mock_ascii.call_count == 2
            op.hid_serial_out.send_scancode.assert_called_once_with(scancode)

            mock_ascii.reset_mock()
            caplog.clear()
            scancode[2] = 0x29
            mock_endpoint.read.return_value = scancode
            assert op._parse_key(mock_endpoint) is False
            assert any(
                "Ctrl+ESC escape sequence detected! Exiting..." in record.message
                for record in caplog.records
            )
            assert mock_ascii.call_count == 1

        # Reset the call_count for mock_ascii after the test
        mock_ascii.reset_mock()

    def test_parse_key_invalid_scancode(self, mock_keyboard_device, op):
        """Test _parse_key with an unmapped scancode (scancode_to_ascii returns None).

        Verifies when an invalid scancode is read:
         - Endpoint still read as expected
         - _parse_key returns True to continue loop
         - scancode_to_ascii called (patched to return None as if KeyError raised)
         - unmodified scancode sent anyway
        """
        from kvm_serial.utils.utils import scancode_to_ascii as mock_ascii

        # Use a scancode that is not mapped (e.g., 0xFF)
        scancode = [0x00, 0x00, 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00]
        mock_endpoint = mock_keyboard_device.interfaces[0].endpoints[0]
        mock_endpoint.read.return_value = scancode

        mock_ascii.return_value = None

        op.debounce = None
        result = op._parse_key(mock_endpoint)
        assert result is True
        mock_endpoint.read.assert_called_once_with(mock_endpoint.wMaxPacketSize, timeout=100)
        assert mock_ascii.call_count == 2
        op.hid_serial_out.send_scancode.assert_called_once_with(scancode)

        # Reset the call_count for mock_ascii after the test
        mock_ascii.reset_mock()

    def test_run(self, mock_keyboard_device, op):
        """
        Test the normal execution of PyUSBOp.run() with a simulated USB keyboard device

        Verifies:
        - endpoint read returns the mock scancode
        - _parse_key is called twice: once returning True (continue), then False (break)
        - Kernel driver methods called as expected
        - usb.util.dispose_resources is called to clean up resources after loop broken
        - Correct number of key parsing attempts are made
        """
        import usb.util

        # Patch endpoint.read to simulate a single keypress, then stop
        scancode = [0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00]
        mock_endpoint = mock_keyboard_device.interfaces[0].endpoints[0]
        mock_endpoint.read.return_value = scancode

        # Patch _parse_key to return False after first call (to break loop)
        op._parse_key = MagicMock(side_effect=[True, False])
        # Patch is_kernel_driver_active and detach_kernel_driver

        # Patch usb.util.dispose_resources
        with patch.object(usb.util, "dispose_resources") as mock_dispose:
            op.run()
            mock_keyboard_device.is_kernel_driver_active.assert_called_once_with(0)
            mock_keyboard_device.detach_kernel_driver.assert_called_once_with(0)
            mock_keyboard_device.attach_kernel_driver.assert_called_once_with(0)
            mock_dispose.assert_called_once_with(mock_keyboard_device)
            assert op._parse_key.call_count == 2

    def test_run_detach_kernel_driver_usb_error(self, mock_keyboard_device, op, caplog):
        """
        Test PyUSBOp.run() when detaching the kernel driver raises a usb.core.USBError.

        Simulates the scenario where detaching the kernel driver from a USB device fails
        with a USBError (e.g., due to insufficient permissions).

        Verifies:
        - is_kernel_driver_active, detach_kernel_driver, called on the mock keyboard
        - usb.util.dispose_resources called to clean up resources
        - Appropriate error messages are logged at the ERROR level
        """
        import usb.util

        class MockUSBError(Exception):
            errno = 13

        op._parse_key = MagicMock(side_effect=False)
        mock_keyboard_device.detach_kernel_driver.side_effect = MockUSBError("mock error")

        with (
            patch.object(usb.core, "USBError", MockUSBError),
            patch.object(usb.util, "dispose_resources") as mock_dispose,
            caplog.at_level("ERROR"),
        ):
            op.run()
            mock_keyboard_device.is_kernel_driver_active.assert_called_once_with(0)
            mock_keyboard_device.detach_kernel_driver.assert_called_once_with(0)
            mock_dispose.assert_called_once_with(mock_keyboard_device)
            # Check error logs
            assert any("mock error" in record.message for record in caplog.records)
            assert any(
                "This script does not seem to be running as superuser." in record.message
                for record in caplog.records
            )
