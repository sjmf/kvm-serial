import pytest
from unittest.mock import patch, MagicMock
import signal
import sys


# Some modules must be patched before importing, e.g.:
#   Pynput, which DOES NOT WORK headless, i.e. in Github Actions runner;
#   Numpy, which must not be re-imported
#   CV2, which complains of an "AttributeError: module 'cv2.dnn' has no attribute 'DictValue'"
SYS_MODULES_PATCH = {
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
}


class TestControl:

    @pytest.fixture(autouse=True)
    def setup_backend_mocks(self):
        """Patch backend modules using patch.object to avoid string-based
        patch resolution failures when kvm_serial.backend is pre-loaded
        in sys.modules (cross-group test pollution)."""
        with patch.dict(sys.modules, SYS_MODULES_PATCH):
            from kvm_serial.backend import video as video_mod
            from kvm_serial.backend import keyboard as kb_mod
            from kvm_serial.backend import mouse as mouse_mod

            with (
                patch.object(video_mod, "CaptureDevice"),
                patch.object(kb_mod, "KeyboardListener"),
                patch.object(mouse_mod, "MouseListener"),
            ):
                yield

    @patch("sys.argv", ["control.py", "/dev/ttyUSB0"])
    def test_parse_args_default_values(self):
        from kvm_serial.control import parse_args

        """Test parse_args with default values"""
        args = parse_args()
        assert args.port == "/dev/ttyUSB0"
        assert args.baud == 9600
        assert args.mode == "curses"
        assert not args.verbose
        assert not args.mouse
        assert not args.video

    def test_stop_threads(self):
        """Test stop_threads function with mock objects"""
        pass  # TODO: Implement test with mock MouseListener, CaptureDevice, and KeyboardListener

    @patch("sys.exit")
    def test_signal_handler_exit(self, mock_exit):
        from kvm_serial.control import signal_handler_exit

        """Test signal_handler_exit function"""
        signal_handler_exit(signal.SIGINT, None)
        mock_exit.assert_called_once_with(0)

    def test_signal_handler_ignore(self, caplog):
        from kvm_serial.control import signal_handler_ignore

        """Test signal_handler_ignore function"""
        with caplog.at_level("DEBUG"):
            signal_handler_ignore(signal.SIGINT, None)
            assert "Ignoring Ctrl+C" in caplog.text

    def test_main(self):
        """Test main function basic execution"""
        pass  # TODO: Implement test with mocked dependencies

    # TODO: Implement further tests
