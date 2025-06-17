from unittest.mock import patch, MagicMock
import signal
import sys


# Some modules must be patched before importing, e.g.:
#   Pynput, which DOES NOT WORK headless, i.e. in Github Actions runner;
#   Numpy, which must not be re-imported
#   CV2, which complains of an "AttributeError: module 'cv2.dnn' has no attribute 'DictValue'"
@patch.dict(
    sys.modules,
    {
        "cv2": MagicMock(),
        "numpy": MagicMock(),
        "tkinter": MagicMock(),
        "pynput.mouse": MagicMock(),
        "pynput.keyboard": MagicMock(),
        "pynput.mouse.Button": MagicMock(),
        "pynput.mouse.Listener": MagicMock(),
        "pynput.keyboard.Key": MagicMock(),
        "pynput.keyboard.KeyCode": MagicMock(),
        "pynput.keyboard.Listener": MagicMock(),
    },
)
@patch("kvm_serial.backend.mouse.MouseListener")
@patch("kvm_serial.backend.keyboard.KeyboardListener")
@patch("kvm_serial.backend.video.CaptureDevice")
class TestControl:

    @patch("sys.argv", ["control.py", "/dev/ttyUSB0"])
    def test_parse_args_default_values(self, mock_capture, mock_keyboard, mock_mouse):
        from kvm_serial.control import parse_args

        """Test parse_args with default values"""
        args = parse_args()
        assert args.port == "/dev/ttyUSB0"
        assert args.baud == 9600
        assert args.mode == "curses"
        assert not args.verbose
        assert not args.mouse
        assert not args.video

    def test_stop_threads(self, mock_capture, mock_keyboard, mock_mouse):
        """Test stop_threads function with mock objects"""
        pass  # TODO: Implement test with mock MouseListener, CaptureDevice, and KeyboardListener

    @patch("sys.exit")
    def test_signal_handler_exit(self, mock_exit, mock_capture, mock_keyboard, mock_mouse):
        from kvm_serial.control import signal_handler_exit

        """Test signal_handler_exit function"""
        signal_handler_exit(signal.SIGINT, None)
        mock_exit.assert_called_once_with(0)

    def test_signal_handler_ignore(self, mock_capture, mock_keyboard, mock_mouse, caplog):
        from kvm_serial.control import signal_handler_ignore

        """Test signal_handler_ignore function"""
        with caplog.at_level("DEBUG"):
            signal_handler_ignore(signal.SIGINT, None)
            assert "Ignoring Ctrl+C" in caplog.text

    def test_main(self, mock_capture, mock_keyboard, mock_mouse):
        """Test main function basic execution"""
        pass  # TODO: Implement test with mocked dependencies

    # TODO: Implement further tests
