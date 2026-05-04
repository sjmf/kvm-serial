import pytest
import termios
from unittest.mock import patch
from kvm_serial.utils.communication import list_serial_ports

from tests._utilities import MockSerial, mock_serial


class TestListSerialPorts:
    """Test suite for the cross-platform list_serial_ports() helper.

    All tests in this suite are currently skipped — they predate the move to
    pyserial's list_ports API and need rewriting to mock that surface rather
    than the prior glob-based enumeration. Kept in place as a TODO marker.
    """

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
