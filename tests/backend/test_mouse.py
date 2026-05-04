import pytest
from unittest.mock import patch, MagicMock
from collections import namedtuple
from tests._utilities import MockSerial, mock_serial


@pytest.fixture
def sys_modules_patch():
    # Define a simple Monitor namedtuple for mocking get_monitors
    Monitor = namedtuple("Monitor", ["x", "y", "width", "height", "is_primary"])
    primary_monitor = Monitor(x=0, y=0, width=1920, height=1080, is_primary=True)

    # Mock modules which include Pynput imports before importing
    # These DO NOT WORK headless, i.e. in Github Actions runner
    return {
        "serial": MagicMock(),
        "screeninfo": MagicMock(),
        "screeninfo.getmonitors": MagicMock(return_value=[primary_monitor]),
        "pynput": MagicMock(),
        "pynput.mouse": MagicMock(),
        "pynput.mouse.Button": MagicMock(),
        "pynput.mouse.Listener": MagicMock(),
    }


# Some modules must be patched before importing (see test_control.py)
@patch("serial.Serial", MockSerial)
class TestMouse:

    def test_mouse_listener(self, mock_serial, sys_modules_patch):
        """Test basic MouseListener initialization"""

        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.implementations import baseop as baseop_mod
            from kvm_serial.backend.mouse import MouseListener

            with patch.object(baseop_mod, "CH9329Comm") as mock_datacomm:
                MouseListener(mock_serial)
                mock_datacomm.assert_called_once_with(mock_serial)

    def test_thread_calls(self, mock_serial, sys_modules_patch):
        """
        Test that MouseListener.run(), start(), and stop() call correct Listener thread methods.
        Mocks:
            - pynput.mouse.Listener: To track start, join, and stop calls
        Asserts:
            - thread.start(), thread.join(), and thread.stop() are called as expected
        """
        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend import mouse as mouse_mod
            from kvm_serial.backend.mouse import MouseListener

            mock_thread = MagicMock()
            listener = MouseListener(mock_serial)
            listener.thread = mock_thread

            listener.run()
            mock_thread.start.assert_called_once()
            mock_thread.join.assert_called_once()
            mock_thread.reset_mock()

            listener.start()
            mock_thread.start.assert_called_once()
            mock_thread.join.assert_not_called()
            mock_thread.reset_mock()

            listener.stop()
            mock_thread.stop.assert_called_once()
            mock_thread.join.assert_called_once()
            mock_thread.reset_mock()

    def test_on_move(self, mock_serial, sys_modules_patch):
        """
        Test MouseListener.on_move forwards positional events to
        send_mouse_absolute with the listener's screen dimensions and returns
        True. Wire-level scaling and negative-coordinate wrapping live in
        CH9329Comm — verified in tests/utils/test_communication.py.
        """
        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.implementations import baseop as baseop_mod
            from kvm_serial.backend.mouse import MouseListener

            with patch.object(baseop_mod, "CH9329Comm") as mock_comm:
                listener = MouseListener(mock_serial)
                listener.op.hid_serial_out = mock_comm
                listener._width = 1920
                listener._height = 1080

                result = listener.on_move(960, 540)
                mock_comm.send_mouse_absolute.assert_called_once_with(0, 960, 540, 1920, 1080)
                assert result is True

    def test_on_click(self, mock_serial, sys_modules_patch):
        """
        Test MouseListener.on_click forwards press/release events to
        send_mouse_relative with the right button mask and zero motion.
        """
        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.implementations import baseop as baseop_mod
            from kvm_serial.backend.mouse import MouseListener
            from kvm_serial.backend.implementations.mouseop import MouseButton

            with patch.object(baseop_mod, "CH9329Comm") as mock_comm:
                listener = MouseListener(mock_serial)
                listener.op.hid_serial_out = mock_comm
                listener._width = 1920
                listener._height = 1080

                left_button = MagicMock()
                right_button = MagicMock()
                listener.pynput_button_mapping = {  # type: ignore
                    left_button: MouseButton.LEFT,
                    right_button: MouseButton.RIGHT,
                }

                # (button, down, expected_button_byte)
                cases = [
                    (left_button, True, 0x01),
                    (left_button, False, 0x00),
                    (right_button, True, 0x02),
                    (right_button, False, 0x00),
                ]
                for button, down, expected_byte in cases:
                    result = listener.on_click(100, 200, button, down)
                    mock_comm.send_mouse_relative.assert_called_once_with(expected_byte, 0, 0, 0)
                    assert result is True
                    mock_comm.send_mouse_relative.reset_mock()

    def test_on_scroll(self, mock_serial, sys_modules_patch):
        """
        Test MouseListener.on_scroll forwards vertical scroll deltas as the
        wheel argument to send_mouse_relative; horizontal dx is dropped
        (CH9329's relative-mouse frame has no horizontal wheel axis).
        """
        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.implementations import baseop as baseop_mod
            from kvm_serial.backend.mouse import MouseListener

            with patch.object(baseop_mod, "CH9329Comm") as mock_comm:
                listener = MouseListener(mock_serial)
                listener.op.hid_serial_out = mock_comm
                listener._width = 1920
                listener._height = 1080

                # (dx, dy, expected_wheel) — dx is intentionally discarded.
                cases = [
                    (0, 1, 1),
                    (0, -1, -1),
                    (1, 0, 0),
                    (-1, 0, 0),
                ]
                for dx, dy, expected_wheel in cases:
                    result = listener.on_scroll(100, 200, dx, dy)
                    mock_comm.send_mouse_relative.assert_called_once_with(0, 0, 0, expected_wheel)
                    assert result is True
                    mock_comm.send_mouse_relative.reset_mock()


# ---
# Test for mouse_main
@patch("serial.Serial", MockSerial)
class TestMouseMain:
    @pytest.fixture
    def mock_args(self):
        args = MagicMock()
        args.port = "/dev/ttyUSB0"
        args.baud = 115200
        args.block = True
        return args

    @patch("argparse.ArgumentParser.parse_args")
    def test_mouse_main_basic(self, mock_parse_args, mock_args, mock_serial, sys_modules_patch):
        """
        Test mouse_main: mocks Serial and MouseListener, simulates thread loop and KeyboardInterrupt.
        """
        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend import mouse as mouse_mod

            with (
                patch.object(mouse_mod, "Serial") as mock_serial_cls,
                patch.object(mouse_mod, "MouseListener") as mock_listener_cls,
            ):
                mock_listener_instance = MagicMock()
                mock_thread = MagicMock()
                # Simulate thread.is_alive() True once, then False
                mock_thread.is_alive.side_effect = [True, False]
                mock_listener_instance.thread = mock_thread
                mock_listener_cls.return_value = mock_listener_instance

                mock_parse_args.return_value = mock_args

                serial_instance = mock_serial_cls.return_value

                mouse_mod.mouse_main()

                # Check Serial and MouseListener were called with correct args
                mock_serial_cls.assert_called_once_with("/dev/ttyUSB0", 115200)
                mock_listener_cls.assert_called_once_with(serial_instance, block=True)
                # MouseListener.start() should be called
                mock_listener_instance.start.assert_called_once()
                # MouseListener.thread.join should be called at least once
                assert mock_thread.join.call_count >= 1

    @patch("argparse.ArgumentParser.parse_args")
    def test_mouse_main_keyboardinterrupt_on_start(
        self, mock_parse_args, mock_args, sys_modules_patch
    ):
        """
        Test mouse_main: MouseListener.start raises KeyboardInterrupt, should exit gracefully.
        """
        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend import mouse as mouse_mod

            with (
                patch.object(mouse_mod, "Serial") as mock_serial_cls,
                patch.object(mouse_mod, "MouseListener") as mock_mouse_listener_cls,
            ):
                mock_parse_args.return_value = mock_args

                # Prepare mock Serial and MouseListener
                mock_serial = MagicMock()
                mock_serial_cls.return_value = mock_serial
                mock_listener = MagicMock()
                # Patch start to raise KeyboardInterrupt
                mock_listener.start.side_effect = KeyboardInterrupt
                mock_mouse_listener_cls.return_value = mock_listener

                # Should not raise, should handle KeyboardInterrupt
                mouse_mod.mouse_main()

                # Serial and MouseListener should be called as before
                mock_serial_cls.assert_called_once_with("/dev/ttyUSB0", 115200)
                mock_mouse_listener_cls.assert_called_once_with(mock_serial, block=True)
                mock_listener.start.assert_called_once()
                mock_listener.stop.assert_called_once()
                # No join calls expected since start raises
                assert mock_listener.thread.join.call_count == 0
