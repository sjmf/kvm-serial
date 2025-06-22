import sys
import pytest
from unittest.mock import patch, MagicMock
from collections import namedtuple
from tests._utilities import MockSerial, mock_serial


@pytest.fixture
def mouse_mocks():
    # Define a simple Monitor namedtuple for mocking get_monitors
    Monitor = namedtuple("Monitor", ["x", "y", "width", "height", "is_primary"])
    primary_monitor = Monitor(x=0, y=0, width=1920, height=1080, is_primary=True)
    return {
        "serial": MagicMock(),
        "screeninfo": MagicMock(),
        "screeninfo.getmonitors": MagicMock(return_value=[primary_monitor]),
        "pynput.mouse": MagicMock(),
        "pynput.mouse.Button": MagicMock(),
        "pynput.mouse.Listener": MagicMock(),
    }


# Some modules must be patched before importing (see test_control.py)
@patch("serial.Serial", MockSerial)
class TestMouse:

    # Mock modules which include Pynput imports before importing
    # These DO NOT WORK headless, i.e. in Github Actions runner
    @patch("kvm_serial.backend.mouse.DataComm")
    def test_mouse_listener(self, mock_datacomm, mock_serial, mouse_mocks):
        """Test basic MouseListener initialization"""

        with patch.dict(sys.modules, mouse_mocks):
            from kvm_serial.backend.mouse import MouseListener

            listener = MouseListener(mock_serial)
            mock_datacomm.assert_called_once_with(mock_serial)

    @patch("kvm_serial.backend.mouse.Listener")
    def test_run_calls_thread_start_and_join(self, mock_listener_cls, mock_serial, mouse_mocks):
        """
        Test that MouseListener.run(), start(), and stop() call correct Listener thread methods.
        Mocks:
            - pynput.mouse.Listener: To track start, join, and stop calls
        Asserts:
            - thread.start(), thread.join(), and thread.stop() are called as expected
        """
        with patch.dict(sys.modules, mouse_mocks):
            from kvm_serial.backend.mouse import MouseListener

            mock_thread = MagicMock()
            mock_listener_cls.return_value = mock_thread

            listener = MouseListener(mock_serial)
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
            mock_listener_cls.reset_mock()
