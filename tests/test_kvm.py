from unittest.mock import patch, MagicMock
from kvm_serial.kvm import KVMGui
import sys

@patch("tkinter.Tk")
@patch.dict(sys.modules, {
    'cv2': MagicMock(),
    'numpy': MagicMock(),
    'tkinter': MagicMock(),
})
class TestKVM:
    def test_kvmgui_initial_values(self, mock_tk):
        """Test that KVMGui initializes with correct default values"""
        gui = KVMGui()

        # Test initial backend options
        assert gui.kb_backends == ["pynput", "curses", "tty", "usb"]
        assert gui.baud_rates == [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]

        # Test initial variable states
        assert gui.keyboard_var.get() is True
        assert gui.video_var.get() is True
        assert gui.mouse_var.get() is True
        assert gui.kb_backend_var.get() == "pynput"
        assert gui.baud_rate_var.get() == 9600
        assert gui.window_var.get() is False
        assert gui.verbose_var.get() is False

    def test_stop_subprocess(self, mock_tk):
        """Test subprocess termination"""
        gui = KVMGui()
        # Create a mock process
        mock_process = MagicMock()
        gui.process = mock_process

        gui.stop_subprocess()

        # Verify process was terminated
        mock_process.terminate.assert_called_once()

    def test_on_checkbox_changed(self, mock_tk):
        """Test checkbox state affects combobox state"""
        gui = KVMGui()
        mock_combo = MagicMock()
        mock_var = MagicMock()

        # Test enabled state
        mock_var.get.return_value = True
        gui._on_checkbox_changed(mock_var, mock_combo)
        mock_combo.config.assert_called_with(state="readonly")

        # Test disabled state
        mock_var.get.return_value = False
        gui._on_checkbox_changed(mock_var, mock_combo)
        mock_combo.config.assert_called_with(state="disabled")
