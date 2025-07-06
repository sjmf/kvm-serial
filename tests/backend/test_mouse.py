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

        with (
            patch.dict("sys.modules", sys_modules_patch),
            patch("kvm_serial.backend.mouse.DataComm") as mock_datacomm,
        ):
            from kvm_serial.backend.mouse import MouseListener

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
        with (
            patch.dict("sys.modules", sys_modules_patch),
            patch("kvm_serial.backend.mouse.Listener") as mock_thread,
        ):
            from kvm_serial.backend.mouse import MouseListener

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
        Test MouseListener.on_move sends the correct data to comm.send and returns True.
        Mocks:
            - DataComm: To track send calls
        Asserts:
            - comm.send is called with the expected data and cmd
            - on_move returns True
        """

        # Calculate expected dx, dy in a helper function
        def calculate_expected_data(x, y, width, height):
            dx = int((4096 * x) // width)
            dy = int((4096 * y) // height)
            if dx < 0:
                dx = abs(4096 + dx)
            if dy < 0:
                dy = abs(4096 + dy)
            expected_data = bytearray(b"\x02\x00")
            expected_data += dx.to_bytes(2, "little")
            expected_data += dy.to_bytes(2, "little")
            return expected_data[:7] if len(expected_data) > 7 else expected_data.ljust(7, b"\x00")

        with (
            patch.dict("sys.modules", sys_modules_patch),
            patch("kvm_serial.backend.mouse.DataComm") as mock_comm,
        ):
            from kvm_serial.backend.mouse import MouseListener

            # Set up a MouseListener with known screen size
            listener = MouseListener(mock_serial)
            listener.comm = mock_comm
            listener.width = 1920
            listener.height = 1080

            # Case 1: Center of the screen (positive dx/dy)
            x, y = 960, 540
            result = listener.on_move(x, y)
            expected_data = calculate_expected_data(x, y, listener.width, listener.height)
            mock_comm.send.assert_called_once_with(expected_data, cmd=b"\x04")
            assert result is True
            mock_comm.send.reset_mock()

            # Case 2: Negative dx (monitor to the left)
            x_neg, y_neg = -100, 540
            result_neg = listener.on_move(x_neg, y_neg)
            expected_data_neg = calculate_expected_data(
                x_neg, y_neg, listener.width, listener.height
            )
            mock_comm.send.assert_called_once_with(expected_data_neg, cmd=b"\x04")
            assert result_neg is True
            mock_comm.send.reset_mock()

            # Case 3: Negative dy (monitor above)
            x_neg2, y_neg2 = 960, -100
            result_neg2 = listener.on_move(x_neg2, y_neg2)
            expected_data_neg2 = calculate_expected_data(
                x_neg2, y_neg2, listener.width, listener.height
            )
            mock_comm.send.assert_called_once_with(expected_data_neg2, cmd=b"\x04")
            assert result_neg2 is True
            mock_comm.send.reset_mock()

            # Case 4: Both dx and dy negative (monitor above and left)
            x_neg3, y_neg3 = -100, -100
            result_neg3 = listener.on_move(x_neg3, y_neg3)
            expected_data_neg3 = calculate_expected_data(
                x_neg3, y_neg3, listener.width, listener.height
            )
            mock_comm.send.assert_called_once_with(expected_data_neg3, cmd=b"\x04")
            assert result_neg3 is True
            mock_comm.send.reset_mock()

    def test_on_click(self, mock_serial, sys_modules_patch):
        """
        Test MouseListener.on_click sends correct data for button press/release and returns True.
        Mocks:
            - DataComm: To track send calls
        Asserts:
            - comm.send is called with expected data and cmd for press and release
            - on_click returns True
        """
        with (
            patch.dict("sys.modules", sys_modules_patch),
            patch("kvm_serial.backend.mouse.DataComm") as mock_comm,
        ):
            from kvm_serial.backend.mouse import MouseListener

            listener = MouseListener(mock_serial)

            listener.comm = mock_comm
            listener.width = 1920
            listener.height = 1080

            # Mock button values
            left_button = MagicMock()
            right_button = MagicMock()
            # Patch control_chars to accept our mock buttons
            listener.control_chars = {
                left_button: b"\x01",
                right_button: b"\x02",
            }
            # Test left button press
            result_press = listener.on_click(100, 200, left_button, True)
            expected_data_press = bytearray(b"\x01\x01\x00\x00\x00")
            mock_comm.send.assert_called_once_with(expected_data_press, cmd=b"\x05")
            assert result_press is True
            mock_comm.send.reset_mock()
            # Test left button release
            result_release = listener.on_click(100, 200, left_button, False)
            expected_data_release = bytearray(b"\x01\x00\x00\x00\x00")
            mock_comm.send.assert_called_once_with(expected_data_release, cmd=b"\x05")
            assert result_release is True
            mock_comm.send.reset_mock()
            # Test right button press
            result_press_r = listener.on_click(100, 200, right_button, True)
            expected_data_press_r = bytearray(b"\x01\x02\x00\x00\x00")
            mock_comm.send.assert_called_once_with(expected_data_press_r, cmd=b"\x05")
            assert result_press_r is True
            mock_comm.send.reset_mock()
            # Test right button release
            result_release_r = listener.on_click(100, 200, right_button, False)
            expected_data_release_r = bytearray(b"\x01\x00\x00\x00\x00")
            mock_comm.send.assert_called_once_with(expected_data_release_r, cmd=b"\x05")
            assert result_release_r is True
            mock_comm.send.reset_mock()

    def test_on_scroll(self, mock_serial, sys_modules_patch):
        """
        Test MouseListener.on_scroll sends correct data for scroll events and returns True.
        Mocks:
            - DataComm: To track send calls
        Asserts:
            - comm.send is called with expected data and cmd for scroll up/down/left/right
            - on_scroll returns True
        """
        with (
            patch.dict("sys.modules", sys_modules_patch),
            patch("kvm_serial.backend.mouse.DataComm") as mock_comm,
        ):
            from kvm_serial.backend.mouse import MouseListener

            listener = MouseListener(mock_serial)
            listener.comm = mock_comm
            listener.width = 1920
            listener.height = 1080

            # Test scroll up
            result_up = listener.on_scroll(100, 200, 0, 1)
            expected_data_up = bytearray(b"\x01\x00\x00\x00\x01")
            mock_comm.send.assert_called_once_with(expected_data_up, cmd=b"\x05")
            assert result_up is True
            mock_comm.send.reset_mock()
            # Test scroll down
            result_down = listener.on_scroll(100, 200, 0, -1)
            expected_data_down = bytearray(b"\x01\x00\x00\xff\xff")
            mock_comm.send.assert_called_once_with(expected_data_down, cmd=b"\x05")
            assert result_down is True
            mock_comm.send.reset_mock()
            # Test scroll right
            result_right = listener.on_scroll(100, 200, 1, 0)
            expected_data_right = bytearray(b"\x01\x00\x01\x00\x00")
            mock_comm.send.assert_called_once_with(expected_data_right, cmd=b"\x05")
            assert result_right is True
            mock_comm.send.reset_mock()
            # Test scroll left
            result_left = listener.on_scroll(100, 200, -1, 0)
            expected_data_left = bytearray(b"\x01\xff\xff\x00\x00")
            mock_comm.send.assert_called_once_with(expected_data_left, cmd=b"\x05")
            assert result_left is True
            mock_comm.send.reset_mock()


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
        with (
            patch.dict("sys.modules", sys_modules_patch),
            patch("kvm_serial.backend.mouse.Serial") as mock_serial_cls,
            patch("kvm_serial.backend.mouse.MouseListener") as mock_listener_cls,
        ):
            mock_listener_instance = MagicMock()
            mock_thread = MagicMock()
            # Simulate thread.is_alive() True once, then False
            mock_thread.is_alive.side_effect = [True, False]
            mock_listener_instance.thread = mock_thread
            mock_listener_cls.return_value = mock_listener_instance

            mock_parse_args.return_value = mock_args

            serial_instance = mock_serial_cls.return_value

            # Patching done, import the class:
            from kvm_serial.backend.mouse import mouse_main

            mouse_main()

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
        with (
            patch.dict("sys.modules", sys_modules_patch),
            patch("kvm_serial.backend.mouse.Serial") as mock_serial_cls,
            patch("kvm_serial.backend.mouse.MouseListener") as mock_mouse_listener_cls,
        ):
            mock_parse_args.return_value = mock_args

            # Prepare mock Serial and MouseListener
            mock_serial = MagicMock()
            mock_serial_cls.return_value = mock_serial
            mock_listener = MagicMock()
            # Patch start to raise KeyboardInterrupt
            mock_listener.start.side_effect = KeyboardInterrupt
            mock_mouse_listener_cls.return_value = mock_listener

            # Patching done, import the class:
            from kvm_serial.backend.mouse import mouse_main

            # Should not raise, should handle KeyboardInterrupt
            mouse_main()

        # Serial and MouseListener should be called as before
        mock_serial_cls.assert_called_once_with("/dev/ttyUSB0", 115200)
        mock_mouse_listener_cls.assert_called_once_with(mock_serial, block=True)
        mock_listener.start.assert_called_once()
        mock_listener.stop.assert_called_once()
        # No join calls expected since start raises
        assert mock_listener.thread.join.call_count == 0
