#!/usr/bin/env python
"""
Test suite for KVM screenshot functionality.
Tests the File > Take Screenshot menu action, clipboard copy, and file save.
"""

import unittest
from unittest.mock import patch, MagicMock

# Import the base test class
from test_kvm_base import KVMTestBase


class TestKVMScreenshot(KVMTestBase):
    """Test class for KVM screenshot functionality."""

    def test_screenshot_no_video_frame(self):
        """Test screenshot shows warning when no video frame is available."""
        app = self.create_kvm_app()

        # Simulate no pixmap set (pixmap() returns a null QPixmap)
        mock_pixmap = MagicMock()
        mock_pixmap.isNull.return_value = True
        app.video_pixmap_item = MagicMock()
        app.video_pixmap_item.pixmap.return_value = mock_pixmap

        with patch("kvm_serial.kvm.QMessageBox.warning") as mock_warning:
            app._take_screenshot()

            mock_warning.assert_called_once()
            args = mock_warning.call_args[0]
            self.assertIn("No video frame", args[2])

    def test_screenshot_no_pixmap_returns_none(self):
        """Test screenshot handles pixmap() returning None."""
        app = self.create_kvm_app()

        app.video_pixmap_item = MagicMock()
        app.video_pixmap_item.pixmap.return_value = None

        with patch("kvm_serial.kvm.QMessageBox.warning") as mock_warning:
            app._take_screenshot()

            mock_warning.assert_called_once()

    def test_screenshot_copies_to_clipboard(self):
        """Test that screenshot copies pixmap to clipboard."""
        app = self.create_kvm_app()

        mock_pixmap = MagicMock()
        mock_pixmap.isNull.return_value = False
        app.video_pixmap_item = MagicMock()
        app.video_pixmap_item.pixmap.return_value = mock_pixmap

        mock_clipboard = MagicMock()

        with (
            patch(
                "kvm_serial.kvm.QApplication.clipboard",
                return_value=mock_clipboard,
            ),
            patch(
                "kvm_serial.kvm.QFileDialog.getSaveFileName",
                return_value=("", ""),
            ),
            patch("kvm_serial.kvm.QMessageBox.information"),
        ):
            app._take_screenshot()

            mock_clipboard.setPixmap.assert_called_once_with(mock_pixmap)

    def test_screenshot_file_save_success(self):
        """Test screenshot saves to file and shows confirmation."""
        app = self.create_kvm_app()

        mock_pixmap = MagicMock()
        mock_pixmap.isNull.return_value = False
        mock_pixmap.save.return_value = True
        app.video_pixmap_item = MagicMock()
        app.video_pixmap_item.pixmap.return_value = mock_pixmap

        mock_clipboard = MagicMock()
        save_path = "/tmp/test_screenshot.png"

        with (
            patch(
                "kvm_serial.kvm.QApplication.clipboard",
                return_value=mock_clipboard,
            ),
            patch(
                "kvm_serial.kvm.QFileDialog.getSaveFileName",
                return_value=(save_path, "PNG Image (*.png)"),
            ),
            patch("kvm_serial.kvm.QMessageBox.information") as mock_info,
        ):
            app._take_screenshot()

            mock_pixmap.save.assert_called_once_with(save_path, "PNG")
            mock_info.assert_called_once()
            args = mock_info.call_args[0]
            self.assertIn(save_path, args[2])
            self.assertIn("clipboard", args[2])

    def test_screenshot_file_save_failure(self):
        """Test screenshot shows warning when file save fails."""
        app = self.create_kvm_app()

        mock_pixmap = MagicMock()
        mock_pixmap.isNull.return_value = False
        mock_pixmap.save.return_value = False
        app.video_pixmap_item = MagicMock()
        app.video_pixmap_item.pixmap.return_value = mock_pixmap

        mock_clipboard = MagicMock()
        save_path = "/invalid/path/screenshot.png"

        with (
            patch(
                "kvm_serial.kvm.QApplication.clipboard",
                return_value=mock_clipboard,
            ),
            patch(
                "kvm_serial.kvm.QFileDialog.getSaveFileName",
                return_value=(save_path, "PNG Image (*.png)"),
            ),
            patch("kvm_serial.kvm.QMessageBox.warning") as mock_warning,
        ):
            app._take_screenshot()

            mock_warning.assert_called_once()
            args = mock_warning.call_args[0]
            self.assertIn("Failed", args[2])
            self.assertIn("clipboard", args[2])

    def test_screenshot_dialog_cancelled(self):
        """Test screenshot copies to clipboard only when dialog is cancelled."""
        app = self.create_kvm_app()

        mock_pixmap = MagicMock()
        mock_pixmap.isNull.return_value = False
        app.video_pixmap_item = MagicMock()
        app.video_pixmap_item.pixmap.return_value = mock_pixmap

        mock_clipboard = MagicMock()

        with (
            patch(
                "kvm_serial.kvm.QApplication.clipboard",
                return_value=mock_clipboard,
            ),
            patch(
                "kvm_serial.kvm.QFileDialog.getSaveFileName",
                return_value=("", ""),
            ),
            patch("kvm_serial.kvm.QMessageBox.information") as mock_info,
        ):
            app._take_screenshot()

            # Should not attempt to save to file
            mock_pixmap.save.assert_not_called()

            # Should still copy to clipboard and inform user
            mock_clipboard.setPixmap.assert_called_once_with(mock_pixmap)
            mock_info.assert_called_once()
            args = mock_info.call_args[0]
            self.assertIn("clipboard", args[2])

    def test_screenshot_default_filename_format(self):
        """Test that the save dialog is opened with a timestamped default filename."""
        app = self.create_kvm_app()

        mock_pixmap = MagicMock()
        mock_pixmap.isNull.return_value = False
        app.video_pixmap_item = MagicMock()
        app.video_pixmap_item.pixmap.return_value = mock_pixmap

        with (
            patch("kvm_serial.kvm.QApplication.clipboard", return_value=MagicMock()),
            patch(
                "kvm_serial.kvm.QFileDialog.getSaveFileName",
                return_value=("", ""),
            ) as mock_dialog,
            patch("kvm_serial.kvm.QMessageBox.information"),
            patch(
                "kvm_serial.kvm.time.strftime", return_value="kvm_screenshot_20260204_120000.png"
            ),
        ):
            app._take_screenshot()

            mock_dialog.assert_called_once()
            call_args = mock_dialog.call_args[0]
            # Second positional arg is the dialog title
            self.assertEqual(call_args[1], "Save Screenshot")
            # Third positional arg is the default path
            self.assertIn("kvm_screenshot_20260204_120000.png", call_args[2])
            # Fourth positional arg is the file filter
            self.assertIn("PNG", call_args[3])

    def test_screenshot_clipboard_none(self):
        """Test screenshot handles clipboard returning None gracefully."""
        app = self.create_kvm_app()

        mock_pixmap = MagicMock()
        mock_pixmap.isNull.return_value = False
        app.video_pixmap_item = MagicMock()
        app.video_pixmap_item.pixmap.return_value = mock_pixmap

        with (
            patch("kvm_serial.kvm.QApplication.clipboard", return_value=None),
            patch(
                "kvm_serial.kvm.QFileDialog.getSaveFileName",
                return_value=("", ""),
            ),
            patch("kvm_serial.kvm.QMessageBox.information"),
        ):
            # Should not raise exception even with None clipboard
            app._take_screenshot()


if __name__ == "__main__":
    unittest.main(verbosity=2)
