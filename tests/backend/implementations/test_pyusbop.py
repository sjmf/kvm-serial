from pytest import fixture, raises
from unittest.mock import patch, MagicMock
from tests._utilities import MockSerial, mock_serial


# Mock usb.core and related classes to prevent actual USB operations
@fixture
def sys_modules_patch():
    return {
        "usb": MagicMock(),
        "usb.core": MagicMock(),
        "usb.util": MagicMock(),
    }


CLASS_PATH = "kvm_serial.backend.implementations.pyusbop"


class MockNoBackendError(Exception):
    """A mock exception for testing NoBackendError"""


class MockUSBError(Exception):
    """A mock exception for testing USBError"""

    errno = -1


class BaseErrorDevice:
    """A base device for error-raising USB devices"""

    def __init__(self, name="ErrorDevice"):
        self.name = name

    manufacturer = "Test"
    product = "Device"


class AttrErrorDevice(BaseErrorDevice):
    """Device that raises AttributeError"""

    def get_active_configuration(self):
        raise AttributeError("mock attr error")


class TypeErrorDevice(BaseErrorDevice):
    """Device that raises TypeError"""

    def get_active_configuration(self):
        raise TypeError("mock type error")


class USBErrorDevice(BaseErrorDevice):
    """Device that raises usb.core.USBError"""

    def get_active_configuration(self):
        raise MockUSBError("mock usb error")


@patch("serial.Serial", MockSerial)
class TestPyUSBOperation:
    """
    Tests the PyUSBOp class
    """

    @fixture
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

    def _get_op_unsafe(self, mock_ser: MagicMock, mock_kb: MagicMock):
        """
        UNSAFE method to get op. Use only intentionally, with patch guards.
        Use op fixture otherwise
        """
        from kvm_serial.backend.implementations.pyusbop import PyUSBOp

        op = PyUSBOp(mock_ser)
        op.hid_serial_out = MagicMock()
        op.hid_serial_out.send_scancode.return_value = True

        mock_endpoint = mock_kb.interfaces[0].endpoints[0]
        op.usb_endpoints = {"dead:beef": (mock_endpoint, mock_kb, 0)}

        return op

    @fixture
    def op(self, mock_serial, mock_keyboard_device, sys_modules_patch):
        """
        Fixture that creates and configures a PyUSBOp instance for testing.
        Args:
            mock_serial: Mocked serial interface to be passed to PyUSBOp.
            mock_keyboard_device: Mocked keyboard USB device with interfaces and endpoints.
        Returns:
            PyUSBOp: Configured PyUSBOp instance ready for use in tests.
        """
        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.implementations import pyusbop as pyusbop_mod

            with patch.object(pyusbop_mod, "get_usb_endpoints", return_value={}):
                return self._get_op_unsafe(mock_serial, mock_keyboard_device)

    def test_pyusbop_name_property(self, op):
        """Test that the name property returns 'usb'"""
        assert op.name == "usb"

    def test_get_usb_endpoints(self, mock_keyboard_device, sys_modules_patch):
        """
        Test the `get_usb_endpoints` function to ensure it correctly discovers
        and returns USB endpoint information. This test mocks the USB device discovery process
        and endpoint/interface selection to simulate a keyboard device.

        It verifies that:
        - The function returns a dictionary with the expected device key.
        - The endpoint, device, and interface number are correctly extracted and returned.
        - The underlying USB library functions are called as expected.
        """
        mock_intf = mock_keyboard_device.interfaces[0]
        mock_endp = mock_keyboard_device.interfaces[0].endpoints[0]

        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.implementations import pyusbop as pyusbop_mod

            with (
                patch.object(
                    pyusbop_mod, "usb_core_find", return_value=[mock_keyboard_device]
                ) as find,
                patch.object(
                    pyusbop_mod, "find_descriptor", side_effect=[mock_intf, mock_endp]
                ) as f_desc,
                patch.object(pyusbop_mod, "endpoint_direction", return_value=0x80),
                patch.object(pyusbop_mod, "endpoint_type", return_value=0x03),
            ):
                endpoints = pyusbop_mod.get_usb_endpoints()
                assert len(endpoints) == 1
                device_key = "dead:beef"
                assert device_key in endpoints
                endpoint, device, interface_number = endpoints[device_key]
                assert endpoint == mock_keyboard_device.interfaces[0].endpoints[0]
                assert device == mock_keyboard_device
                assert interface_number == 0

                # Verify that find_descriptor was called correctly
                find.assert_called_once_with(find_all=True)
                assert f_desc.call_count == 2

    def test_get_usb_endpoints_no_backend_error(self, sys_modules_patch):
        """
        Tests that get_usb_endpoints raises the correct exception when no USB backend is available.
        Mocks the usb.core.find method to simulate a backend error and ensures that it propagates
        """

        with (
            patch("sys.modules", sys_modules_patch),
            patch(f"{CLASS_PATH}.usb_core_find", side_effect=MockNoBackendError("test")),
            patch(f"{CLASS_PATH}.NoBackendError", MockNoBackendError),
            raises(MockNoBackendError),
        ):
            from kvm_serial.backend.implementations.pyusbop import get_usb_endpoints

            get_usb_endpoints()

    def test_get_usb_endpoints_devices_none(self, sys_modules_patch):
        """
        Test that get_usb_endpoints returns an empty dictionary when no USB devices are found.
        Patches usb.core.find to return None, simulating the absence of connected devices.
        Verifies the function returns an empty dict.
        """
        with (
            patch("sys.modules", sys_modules_patch),
            patch(f"{CLASS_PATH}.usb_core_find", return_value=None),
        ):
            from kvm_serial.backend.implementations.pyusbop import get_usb_endpoints

            endpoints = get_usb_endpoints()
            assert endpoints == {}

    def test_get_usb_endpoints_device_exceptions(self, caplog, sys_modules_patch):
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

        devices = [AttrErrorDevice(), TypeErrorDevice(), USBErrorDevice()]
        with (
            patch.dict("sys.modules", sys_modules_patch),
            patch(f"{CLASS_PATH}.usb_core_find", return_value=devices),
            patch(f"{CLASS_PATH}.USBError", MockUSBError),
            caplog.at_level("INFO"),
        ):
            from kvm_serial.backend.implementations.pyusbop import get_usb_endpoints

            endpoints = get_usb_endpoints()
            assert endpoints == {}

            # Should log info for AttributeError and TypeError
            for device in devices[:2]:
                assert any(
                    f"Skipping non-device or non-interface object: <{__name__}.{type(device).__name__} object"
                    in record.message
                    for record in caplog.records
                )

            # Should log error for USBError
            assert any(
                "USB error while processing device: 'Test Device" in record.message
                for record in caplog.records
            )

    def test_pyusbop_sleep_interval(self, op, sys_modules_patch):
        """
        Test that _sleep_interval calls the callback with correct args and enforces the interval.
        Ensures timing and callback behavior are correct.
        """
        with patch.dict("sys.modules", sys_modules_patch):
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

    def test_parse_key(self, mock_keyboard_device, mock_serial, sys_modules_patch):
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
        with (
            patch.dict("sys.modules", sys_modules_patch),
            patch(f"{CLASS_PATH}.scancode_to_ascii") as mock_ascii,
        ):
            # Patch scancode_to_ascii to return 'a'
            mock_ascii.return_value = "a"

            # Mock endpoint
            mock_endpoint = mock_keyboard_device.interfaces[0].endpoints[0]

            # Simulate endpoint.read returning a scancode array
            scancode = [0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00]  # 'a' key
            mock_endpoint.read.return_value = scancode

            # Retrieve op WITHIN mock_ascii patch scope, else patch fails due to prior instantiation
            op = self._get_op_unsafe(mock_serial, mock_keyboard_device)

            assert op._parse_key(mock_endpoint) is True

            mock_endpoint.read.assert_called_once_with(mock_endpoint.wMaxPacketSize, timeout=100)
            mock_ascii.assert_called_once_with(scancode)
            op.hid_serial_out.send_scancode.assert_called_once_with(scancode)

            # Reset the call_count for mock_ascii after the test
            mock_ascii.reset_mock()

    def test_parse_key_usb_error(self, mock_keyboard_device, mock_serial, sys_modules_patch):
        """
        Test the behavior of _parse_key when USB endpoint read raises a USBError.

        Verifies:
        1. When a general usb.core.USBError is raised during endpoint.read,
            the exception is propagated by _parse_key.
        2. When the USBError has errno 60 (indicating a timeout),
            _parse_key returns True to signal that the loop should continue.
        """
        with (
            patch.dict("sys.modules", sys_modules_patch),
            patch(f"{CLASS_PATH}.USBError", MockUSBError),
        ):
            # Set up the endpoint to raise our MockUSBError
            mock_endpoint = mock_keyboard_device.interfaces[0].endpoints[0]
            mock_endpoint.read.side_effect = MockUSBError("mock error")

            # Retrieve op WITHIN mock_ascii patch scope, else patch fails due to prior instantiation
            op = self._get_op_unsafe(mock_serial, mock_keyboard_device)

            # On a general error, the class should raise the exception:
            with raises(MockUSBError):
                op._parse_key(mock_endpoint)

            # On error 60, it should return True to continue the loop
            mock_endpoint.read.side_effect.errno = 60
            assert op._parse_key(mock_endpoint) is True

    def test_parse_key_exit_combos(
        self, mock_keyboard_device, mock_serial, caplog, sys_modules_patch
    ):
        """
        Test `_parse_key` handles Ctrl+C and Ctrl+ESC key combinations.

        This test simulates USB keyboard input by providing scancodes to the mocked endpoint.
        Verifies:
          - When Ctrl+C is pressed: method returns True, logs a warning, and passes the scancode through.
          - When Ctrl+ESC is pressed: the method returns False, logs an exit warning, and does not continue processing.
          - The correct number of calls are made to scancode_to_ascii and serial output.
        """
        with (
            patch.dict("sys.modules", sys_modules_patch),
            patch(f"{CLASS_PATH}.scancode_to_ascii") as mock_ascii,
            caplog.at_level("WARNING"),
        ):
            # Ctrl+C scancode: [0x01, ..., 0x06, ...]
            scancode = [0x01, 0x00, 0x06, 0x00, 0x00, 0x00, 0x00, 0x00]
            mock_endpoint = mock_keyboard_device.interfaces[0].endpoints[0]
            mock_endpoint.read.return_value = scancode

            # Retrieve op WITHIN mock_ascii patch scope, else patch fails due to prior instantiation
            op = self._get_op_unsafe(mock_serial, mock_keyboard_device)

            op.debounce = None
            assert op._parse_key(mock_endpoint) is True
            assert any(
                "Ctrl+C passed through. Use Ctrl+ESC to exit!" in record.message
                for record in caplog.records
            )

            # Verify that the method continued after Ctrl+C
            mock_endpoint.read.assert_called_once_with(mock_endpoint.wMaxPacketSize, timeout=100)
            mock_ascii.assert_called_once_with(scancode)
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
            mock_ascii.assert_not_called()

    def test_parse_key_invalid_scancode(self, mock_keyboard_device, mock_serial, sys_modules_patch):
        """Test _parse_key with an unmapped scancode (scancode_to_ascii returns None).

        Verifies when an invalid scancode is read:
         - Endpoint still read as expected
         - _parse_key returns True to continue loop
         - scancode_to_ascii called (patched to return None as if KeyError raised)
         - unmodified scancode sent anyway
        """
        with (
            patch.dict("sys.modules", sys_modules_patch),
            patch(f"{CLASS_PATH}.scancode_to_ascii") as mock_ascii,
        ):
            # Use a scancode that is not mapped (e.g., 0xFF)
            scancode = [0x00, 0x00, 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00]
            mock_endpoint = mock_keyboard_device.interfaces[0].endpoints[0]
            mock_endpoint.read.return_value = scancode
            mock_ascii.return_value = None

            # Retrieve op WITHIN mock_ascii patch scope, else patch fails due to prior instantiation
            op = self._get_op_unsafe(mock_serial, mock_keyboard_device)
            op.debounce = None

            assert op._parse_key(mock_endpoint) is True

        mock_endpoint.read.assert_called_once_with(mock_endpoint.wMaxPacketSize, timeout=100)
        mock_ascii.assert_called_once_with(scancode)
        op.hid_serial_out.send_scancode.assert_called_once_with(scancode)

    def test_run(self, mock_keyboard_device, mock_serial, sys_modules_patch):
        """
        Test the normal execution of PyUSBOp.run() with a simulated USB keyboard device

        Verifies:
        - endpoint read returns the mock scancode
        - _parse_key is called twice: once returning True (continue), then False (break)
        - Kernel driver methods called as expected
        - usb.util.dispose_resources is called to clean up resources after loop broken
        - Correct number of key parsing attempts are made
        """
        with (
            patch.dict("sys.modules", sys_modules_patch),
            patch(f"{CLASS_PATH}.USBError", MockUSBError),
            patch(f"{CLASS_PATH}.dispose_resources") as mock_dispose,
        ):
            # Patch endpoint.read to simulate a single keypress, then stop
            scancode = [0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00]
            mock_endpoint = mock_keyboard_device.interfaces[0].endpoints[0]
            mock_endpoint.read.return_value = scancode

            # Retrieve op WITHIN mock_ascii patch scope, else patch fails due to prior instantiation
            op = self._get_op_unsafe(mock_serial, mock_keyboard_device)

            # Patch _parse_key to return False after first call (to break loop)
            op._parse_key = MagicMock(side_effect=[True, False])

            op.run()

        mock_keyboard_device.is_kernel_driver_active.assert_called_once_with(0)
        mock_keyboard_device.detach_kernel_driver.assert_called_once_with(0)
        mock_keyboard_device.attach_kernel_driver.assert_called_once_with(0)
        mock_dispose.assert_called_once_with(mock_keyboard_device)
        assert op._parse_key.call_count == 2

    def test_run_detach_kernel_driver_usb_error(
        self, mock_keyboard_device, mock_serial, caplog, sys_modules_patch
    ):
        """
        Test PyUSBOp.run() when detaching the kernel driver raises a usb.core.USBError.

        Simulates the scenario where detaching the kernel driver from a USB device fails
        with a USBError (e.g., due to insufficient permissions).

        Verifies:
        - is_kernel_driver_active, detach_kernel_driver, called on the mock keyboard
        - usb.util.dispose_resources called to clean up resources
        - Appropriate error messages are logged at the ERROR level
        """
        with (
            patch.dict("sys.modules", sys_modules_patch),
            patch(f"{CLASS_PATH}.dispose_resources") as mock_dispose,
            patch(f"{CLASS_PATH}.USBError", MockUSBError),
            caplog.at_level("ERROR", logger=f"{CLASS_PATH}"),
        ):
            # Retrieve op WITHIN mock_ascii patch scope, else patch fails due to prior instantiation
            op = self._get_op_unsafe(mock_serial, mock_keyboard_device)
            op._parse_key = MagicMock(side_effect=False)
            mock_keyboard_device.detach_kernel_driver.side_effect = MockUSBError("mock error")
            mock_keyboard_device.detach_kernel_driver.side_effect.errno = 13

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

    def test_legacy_main_usb(self, mock_serial, sys_modules_patch):
        """
        Test that main_usb instantiates PyUSBOp, calls run, and returns None.
        Mocks:
            - PyUSBOp: Patched so instantiation and run can be tracked
        Asserts:
            - PyUSBOp instantiated with the correct argument
            - run() called once
            - main_usb returns None
        """
        with (
            patch.dict("sys.modules", sys_modules_patch),
            patch(f"{CLASS_PATH}.PyUSBOp") as mock_op,
        ):
            from kvm_serial.backend.implementations.pyusbop import main_usb

            mock_op.return_value.run.return_value = None
            assert main_usb(mock_serial) is None
            mock_op.assert_called_once_with(mock_serial)
            mock_op.return_value.run.assert_called_once()
