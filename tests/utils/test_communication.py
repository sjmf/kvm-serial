import pytest
import termios
from unittest.mock import patch
from kvm_serial.utils.communication import DataComm, list_serial_ports

from tests._utilities import MockSerial, mock_serial


class TestDataComm:
    """Test Suite for DataComm class"""

    @patch("serial.Serial", MockSerial)
    def test_init(self, mock_serial):
        """Test initialization and basic operations of DataComm.

        Tests:
        1. Proper initialization with mock serial port
        2. Sending a single character ('a') scancode
        3. Direct scancode sending
        4. Key release functionality

        Verifies correct packet formation including headers, address, command,
        data length, and checksum for each method called.
        """

        mock_serial.port = "/dev/ttyUSB0"
        mock_serial.is_open = True
        mock_serial.baudrate = 9600

        dc = DataComm(mock_serial)

        assert dc.port == mock_serial

        # Scancode for letter 'a'
        char_to_send = bytes((0x0, 0x0, 0x4, 0x0, 0x0, 0x0, 0x0, 0x0))

        # Assert the output contains:
        # Header: 0x57 0xAB; Address: 0x00; Command 0x02;
        # Data length 0x08; Data packet (as above hex: 0000 4000 0000 0000)
        # Checksum 0x10
        dc.send(char_to_send)
        mock_serial.write.assert_called_once_with(
            b"\x57\xab\x00\x02\x08\x00\x00\x04\x00\x00\x00\x00\x00\x10"
        )
        mock_serial.write.reset_mock()

        dc.send_scancode(char_to_send)
        mock_serial.write.assert_called_once_with(
            b"\x57\xab\x00\x02\x08\x00\x00\x04\x00\x00\x00\x00\x00\x10"
        )
        mock_serial.write.reset_mock()

        dc.release()
        mock_serial.write.assert_called_once_with(
            b"\x57\xab\x00\x02\x08\x00\x00\x00\x00\x00\x00\x00\x00\x0c"
        )
        mock_serial.write.reset_mock()

    @patch("serial.Serial", MockSerial)
    def test_send_scancode_invalid_length(self, mock_serial):
        """Test error handling for invalid scancode length.

        Verifies:
        1. Sending a scancode that's too short returns False
        2. No write operation is performed on the serial port
        """
        dc = DataComm(mock_serial)
        result = dc.send_scancode(bytes([0x0, 0x0]))  # Too short
        assert result is False
        mock_serial.write.assert_not_called()

    @patch("serial.Serial", MockSerial)
    @pytest.mark.parametrize("packet_size", [1, 8, 100, 255, 512])  # >255 results in OverflowError
    def test_packet_sizes(self, packet_size, mock_serial):
        """Test handling of different packet sizes.

        Args:
            packet_size: Size of the packet to test (1, 8, 100, or 255 bytes)
            mock_serial: Mock serial port fixture

        Verify that DataComm can handle various packet sizes up to 255 bytes.
        Larger sizes result in OverflowError.
        """
        dc = DataComm(mock_serial)
        data = b"x" * packet_size

        if packet_size < 256:
            dc.send(data)
            mock_serial.write.assert_called_once()
        else:
            with pytest.raises(OverflowError):
                dc.send(data)

    # TODO: fix to correctly use mock.
    @pytest.mark.skip("Broken: serial.Serial imported; fix to use mock.")
    @patch("kvm_serial.utils.communication.glob.glob")
    @patch("serial.Serial", MockSerial)
    @patch("kvm_serial.utils.communication.sys.platform", "darwin")
    def test_list_serial_ports_osx(self, mock_glob):
        """Test serial port enumeration on macOS/OSX.

        Verifies re-ordering functionality (usbserial devices come last)
        """

        mock_glob.return_value = ["/dev/cu.usbserial-1234", "/dev/cu.Bluetooth-123"]
        ports = list_serial_ports()
        # Should return ports with those matching cu.usbserial* last.
        assert len(ports) == 2
        assert ports == ["/dev/cu.Bluetooth-123", "/dev/cu.usbserial-1234"]

    # TODO: fix to correctly use mock.
    @pytest.mark.skip("Broken: serial.Serial imported; fix to use mock.")
    @patch("kvm_serial.utils.communication.glob.glob")
    @patch("serial.Serial", MockSerial)
    @patch("kvm_serial.utils.communication.sys.platform", "linux")
    def test_list_serial_ports_linux(self, mock_glob):
        """Test serial port enumeration on Linux.

        Tests detection of various Linux serial devices:
        - /dev/ttyUSB* (USB-Serial adapters)
        - /dev/ttyACM* (USB ACM devices)
        - /dev/ttyS* (Built-in serial ports)
        """
        mock_glob.return_value = ["/dev/ttyUSB0", "/dev/ttyACM0", "/dev/ttyS0"]
        ports = list_serial_ports()
        assert ports == mock_glob.return_value

    # TODO: fix to correctly use mock.
    @pytest.mark.skip("Broken: serial.Serial imported; fix to use mock.")
    @patch("serial.Serial", MockSerial)
    @patch("kvm_serial.utils.communication.sys.platform", "win32")
    def test_list_serial_ports_windows(self, mock_serial):
        """Test serial port enumeration on Windows.

        Tests COM port detection by:
        1. Simulating available ports (COM1, COM3)
        2. Simulating unavailable ports (COM2)
        3. Verifying correct port enumeration and ordering

        Uses side_effect to control port availability through SerialException.
        """

        # Pretend COM1 and COM3 exist, but not COM2
        _unpatched_init = MockSerial.__init__

        def mock_serial_init(self, port=None):
            from serial import SerialException

            if port not in ["COM1", "COM3"]:
                raise SerialException(f"Could not open port {port}")
            _unpatched_init(self, port)

        mock_serial.side_effect = mock_serial_init

        with patch.object(MockSerial, "__init__", mock_serial_init):
            ports = list_serial_ports()
            assert ports == ["COM1", "COM3"]
            assert "COM2" not in ports
            assert len(ports) == 2

    @patch("kvm_serial.utils.communication.sys.platform", "sunos")
    def test_list_serial_ports_unsupported_platform(self):
        """Test handling of unsupported platform

        Ensure that "Unsupported platform" is raised for the patched platform string
        """
        with pytest.raises(EnvironmentError) as exc_info:
            list_serial_ports()
        assert "Unsupported platform" in str(exc_info.value)

    @patch("serial.Serial", MockSerial)
    def test_packet_format_error(self, mock_serial):
        """Test ValueError is correctly raised on L40 when called with a bad header"""
        dc = DataComm(mock_serial)

        # Error with packet format
        char_to_send = bytes((0x0))
        with pytest.raises(ValueError) as exc_info:
            dc.send(char_to_send, head=char_to_send)
            assert "DataComm packet header MUST have" in str(exc_info.value)

    # TODO: fix to correctly use mock.
    @pytest.mark.skip("Broken: serial.Serial imported; fix to use mock.")
    @patch("kvm_serial.utils.communication.serial.Serial")
    @patch("kvm_serial.utils.communication.glob.glob")
    @patch("kvm_serial.utils.communication.sys.platform", "linux")
    def test_exceptions(self, mock_glob, mock_serial):
        """Test exceptions are raised when they should be:
        #L116 - termios.error
        #L119 - Exception
        """
        mock_glob.return_value = ["/dev/ttyUSB0"]

        # Test termios error case
        mock_serial.side_effect = termios.error("Simulated termios error")
        ports = list_serial_ports()
        # Verify port is still added despite termios error
        assert ports == ["/dev/ttyUSB0"]

        mock_serial.reset_mock()
        mock_serial.side_effect = Exception("Simulated critical error")
        with pytest.raises(Exception) as exc_info:
            list_serial_ports()
        assert "Simulated critical error" in str(exc_info.value)
