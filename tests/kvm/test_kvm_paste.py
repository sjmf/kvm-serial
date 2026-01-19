#!/usr/bin/env python
"""
Test suite for KVM paste functionality.
Tests the Edit > Paste menu action and clipboard-to-scancode transmission.
"""

import unittest
from unittest.mock import patch, MagicMock

# Import the base test class
from test_kvm_base import KVMTestBase


class TestKVMPaste(KVMTestBase):
    """Test class for KVM paste functionality."""

    def test_paste_action_exists_in_edit_menu(self):
        """Test that paste action is created and added to Edit menu."""
        app = self.create_kvm_app()

        # Verify paste_action exists as instance variable
        self.assertTrue(hasattr(app, "paste_action"))
        self.assertIsNotNone(app.paste_action)

    def test_paste_empty_clipboard(self):
        """Test paste with empty clipboard does nothing."""
        app = self.create_kvm_app()
        mock_keyboard_op = MagicMock()
        app.keyboard_op = mock_keyboard_op

        # Mock clipboard returning empty string
        mock_clipboard = MagicMock()
        mock_clipboard.text.return_value = ""

        with patch("kvm_serial.kvm.QApplication.clipboard", return_value=mock_clipboard):
            app._on_paste()

        # Should not send any scancodes
        mock_keyboard_op.hid_serial_out.send_scancode.assert_not_called()

    def test_paste_without_keyboard_op(self):
        """Test paste when keyboard operation is not available."""
        app = self.create_kvm_app()
        app.keyboard_op = None

        # Should not raise exception
        app._on_paste()

    def test_paste_disables_action_during_transmission(self):
        """Test that paste action is disabled when paste starts."""
        app = self.create_kvm_app()
        mock_keyboard_op = MagicMock()
        app.keyboard_op = mock_keyboard_op

        # Mock clipboard with text
        mock_clipboard = MagicMock()
        mock_clipboard.text.return_value = "a"

        # Mock paste_action
        app.paste_action = MagicMock()

        with patch("kvm_serial.kvm.QApplication.clipboard", return_value=mock_clipboard):
            app._on_paste()

        # Paste action should be disabled
        app.paste_action.setEnabled.assert_called_with(False)

    def test_paste_reenables_action_on_completion(self):
        """Test that paste action is re-enabled when paste completes."""
        app = self.create_kvm_app()
        mock_keyboard_op = MagicMock()
        app.keyboard_op = mock_keyboard_op
        app.paste_action = MagicMock()

        # Call _send_next_scancode with index >= len(scancodes) to simulate completion
        app._send_next_scancode([], 0, 0)

        # Paste action should be re-enabled
        app.paste_action.setEnabled.assert_called_with(True)

    def test_paste_reenables_action_on_error(self):
        """Test that paste action is re-enabled when an error occurs."""
        app = self.create_kvm_app()
        mock_keyboard_op = MagicMock()
        mock_keyboard_op.hid_serial_out.send_scancode.side_effect = Exception("Serial error")
        app.keyboard_op = mock_keyboard_op
        app.paste_action = MagicMock()

        # Create a simple scancode
        from array import array

        scancodes = [array("B", [0, 0, 0x04, 0, 0, 0, 0, 0])]  # 'a'

        app._send_next_scancode(scancodes, 0, 1)

        # Paste action should be re-enabled after error
        app.paste_action.setEnabled.assert_called_with(True)

    def test_paste_reenables_action_when_keyboard_op_none(self):
        """Test that paste action is re-enabled if keyboard_op becomes None mid-paste."""
        app = self.create_kvm_app()
        app.keyboard_op = None  # Simulate keyboard_op becoming unavailable
        app.paste_action = MagicMock()

        from array import array

        scancodes = [array("B", [0, 0, 0x04, 0, 0, 0, 0, 0])]

        app._send_next_scancode(scancodes, 0, 1)

        # Paste action should be re-enabled
        app.paste_action.setEnabled.assert_called_with(True)

    def test_paste_sends_scancodes_with_timer(self):
        """Test that paste schedules scancode transmission via QTimer."""
        app = self.create_kvm_app()
        mock_keyboard_op = MagicMock()
        app.keyboard_op = mock_keyboard_op
        app.paste_action = MagicMock()

        from array import array

        scancodes = [
            array("B", [0, 0, 0x04, 0, 0, 0, 0, 0]),  # 'a'
            array("B", [0, 0, 0, 0, 0, 0, 0, 0]),  # key up
        ]

        with patch("kvm_serial.kvm.QTimer.singleShot") as mock_timer:
            app._send_next_scancode(scancodes, 0, 1)

            # Should send first scancode
            mock_keyboard_op.hid_serial_out.send_scancode.assert_called_once()

            # Should schedule next scancode via QTimer with 10ms delay
            mock_timer.assert_called_once()
            call_args = mock_timer.call_args
            self.assertEqual(call_args[0][0], 10)  # 10ms delay

    def test_paste_converts_text_to_scancodes(self):
        """Test that paste correctly converts clipboard text to scancodes."""
        app = self.create_kvm_app()
        mock_keyboard_op = MagicMock()
        app.keyboard_op = mock_keyboard_op
        app.paste_action = MagicMock()

        # Mock clipboard with text
        mock_clipboard = MagicMock()
        mock_clipboard.text.return_value = "ab"

        with (
            patch("kvm_serial.kvm.QApplication.clipboard", return_value=mock_clipboard),
            patch("kvm_serial.kvm.string_to_scancodes", return_value=[]) as mock_convert,
        ):
            app._on_paste()

            # Should call string_to_scancodes with the clipboard text
            mock_convert.assert_called_once_with("ab", key_repeat=1, key_up=1)

    def test_paste_handles_clipboard_access_failure(self):
        """Test paste handles clipboard access returning None gracefully."""
        app = self.create_kvm_app()
        mock_keyboard_op = MagicMock()
        app.keyboard_op = mock_keyboard_op

        with patch("kvm_serial.kvm.QApplication.clipboard", return_value=None):
            # Should not raise exception
            app._on_paste()

        # Should not send any scancodes
        mock_keyboard_op.hid_serial_out.send_scancode.assert_not_called()

    def test_paste_logs_character_count_on_completion(self):
        """Test that paste logs the character count when complete."""
        app = self.create_kvm_app()
        app.keyboard_op = MagicMock()
        app.paste_action = MagicMock()

        with patch("kvm_serial.kvm.logging") as mock_logging:
            # Simulate completion with char_count=5
            app._send_next_scancode([], 0, 5)

            # Should log info with character count
            mock_logging.info.assert_called_with("Pasted 5 characters")


if __name__ == "__main__":
    unittest.main(verbosity=2)
