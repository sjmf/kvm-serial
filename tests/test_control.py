import pytest
from unittest.mock import patch, MagicMock
import signal
import sys

# Pynput does not work headless (e.g. in Github Actions runner); stub it before import.
SYS_MODULES_PATCH = {
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
            from kvm_serial.backend import keyboard as kb_mod
            from kvm_serial.backend import mouse as mouse_mod

            with (
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
        # CH9329 is the default; --ch9350 is opt-in.
        assert not args.ch9350
        assert args.ch9350_state == 2

    @patch("sys.argv", ["control.py", "/dev/ttyUSB0"])
    def test_build_comm_cls_defaults_to_ch9329(self):
        """Without --ch9350, the comm class defaults to CH9329Comm."""
        from kvm_serial.control import _build_comm_cls, parse_args
        from kvm_serial.utils.ch9329 import CH9329Comm

        assert _build_comm_cls(parse_args()) is CH9329Comm

    @patch("sys.argv", ["control.py", "/dev/ttyUSB0", "--ch9329"])
    def test_explicit_ch9329_flag_yields_ch9329(self):
        """--ch9329 declares the default explicitly; same class, same behaviour."""
        from kvm_serial.control import _build_comm_cls, parse_args
        from kvm_serial.utils.ch9329 import CH9329Comm

        args = parse_args()
        assert args.ch9329
        assert not args.ch9350
        assert _build_comm_cls(args) is CH9329Comm

    @patch("sys.argv", ["control.py", "/dev/ttyUSB0", "--ch9329", "--ch9350"])
    def test_protocol_flags_are_mutually_exclusive(self):
        """--ch9329 and --ch9350 cannot both be passed."""
        from kvm_serial.control import parse_args

        with pytest.raises(SystemExit):
            parse_args()

    @patch("sys.argv", ["control.py", "/dev/ttyUSB0", "--ch9350", "--ch9350-state", "3"])
    def test_build_comm_cls_ch9350(self):
        """With --ch9350, the factory yields a CH9350Comm in the requested state."""
        from kvm_serial.control import _build_comm_cls, parse_args
        from kvm_serial.utils.ch9350 import CH9350Comm
        from tests._utilities import MockSerial

        factory = _build_comm_cls(parse_args())
        assert factory is not None
        comm = factory(MockSerial())
        assert isinstance(comm, CH9350Comm)
        assert comm.state == 3

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
