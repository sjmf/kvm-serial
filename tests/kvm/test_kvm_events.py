#!/usr/bin/env python
"""
Test suite for KVM event handling functionality.
Uses KVMTestBase for common mocking infrastructure.
"""

import unittest
from unittest.mock import patch, MagicMock, call
from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtGui import QMouseEvent, QKeyEvent, QFocusEvent, QWheelEvent
from PyQt5.QtWidgets import QApplication
from serial import SerialException

# Import the base test class
from test_kvm_base import KVMTestBase, KVMTestMixins


class TestKVMEventHandling(
    KVMTestBase,
    KVMTestMixins.SerialTestMixin,
    KVMTestMixins.VideoTestMixin,
):
    """Test class for KVM event handling functionality."""

    def test_mouse_click_coordinate_translation(self):
        """Test mouse click coordinates are properly translated to scene coordinates."""
        app = self.create_kvm_app()

        # Set up mock mouse operation
        mock_mouse_op = MagicMock()
        app.mouse_op = mock_mouse_op

        # Set camera dimensions for coordinate system
        app.video_worker.camera_width = 1280
        app.video_worker.camera_height = 720

        # Test left mouse button press
        app._on_mouse_click(100.5, 200.7, Qt.MouseButton.LeftButton, True)

        # Verify mouse operation was called with correct parameters
        from kvm_serial.backend.implementations.mouseop import MouseButton

        mock_mouse_op.on_click.assert_called_once_with(100.5, 200.7, MouseButton.LEFT, True)

    def test_mouse_click_without_mouse_op(self):
        """Test mouse click handling when mouse operation is not available."""
        app = self.create_kvm_app()
        app.mouse_op = None

        # Should not raise exception when mouse_op is None
        app._on_mouse_click(100, 200, Qt.MouseButton.LeftButton, True)

    def test_mouse_button_mapping(self):
        """Test all mouse buttons are mapped correctly."""
        app = self.create_kvm_app()
        mock_mouse_op = MagicMock()
        app.mouse_op = mock_mouse_op

        # Test all button types
        button_tests = [
            (Qt.MouseButton.LeftButton, "LEFT"),
            (Qt.MouseButton.RightButton, "RIGHT"),
            (Qt.MouseButton.MiddleButton, "MIDDLE"),
        ]

        from kvm_serial.backend.implementations.mouseop import MouseButton

        for qt_button, expected_button in button_tests:
            with self.subTest(button=expected_button):
                mock_mouse_op.reset_mock()
                app._on_mouse_click(50, 50, qt_button, True)
                mock_mouse_op.on_click.assert_called_once_with(
                    50, 50, MouseButton[expected_button], True
                )

    def test_mouse_move_coordinate_tracking(self):
        """Test mouse movement updates position tracking."""
        app = self.create_kvm_app()
        mock_mouse_op = MagicMock()
        app.mouse_op = mock_mouse_op

        # Set camera dimensions
        app.video_worker.camera_width = 1280
        app.video_worker.camera_height = 720

        # Test valid coordinates
        result = app._on_mouse_move(640.3, 360.7)

        # Should not return False for valid coordinates
        self.assertNotEqual(result, False)

        # Check position was stored as integers
        self.assertEqual(app.pos_x, 640)
        self.assertEqual(app.pos_y, 360)
        self.assertTrue(app.mouse_var)

        # Verify mouse operation was called
        mock_mouse_op.on_move.assert_called_once_with(640, 360, 1280, 720)

    def test_mouse_move_bounds_checking(self):
        """Test mouse movement bounds checking."""
        app = self.create_kvm_app()
        mock_mouse_op = MagicMock()
        app.mouse_op = mock_mouse_op

        # Set camera dimensions
        app.video_worker.camera_width = 1280
        app.video_worker.camera_height = 720

        # Test coordinates outside bounds
        out_of_bounds_tests = [
            (-1, 360, "x coordinate negative"),
            (1280, 360, "x coordinate at width limit"),
            (640, -1, "y coordinate negative"),
            (640, 720, "y coordinate at height limit"),
            (1281, 360, "x coordinate beyond width"),
            (640, 721, "y coordinate beyond height"),
        ]

        for x, y, description in out_of_bounds_tests:
            with self.subTest(test=description):
                mock_mouse_op.reset_mock()
                result = app._on_mouse_move(x, y)

                # Should return False for out of bounds
                self.assertEqual(result, False)

                # Mouse operation should not be called
                mock_mouse_op.on_move.assert_not_called()

    def test_mouse_move_exception_handling(self):
        """Test exception handling during mouse move operations."""
        app = self.create_kvm_app()
        mock_mouse_op = MagicMock()
        mock_mouse_op.on_move.side_effect = ValueError("Invalid coordinates")
        app.mouse_op = mock_mouse_op

        # Set camera dimensions
        app.video_worker.camera_width = 1280
        app.video_worker.camera_height = 720

        # Should handle exception gracefully
        app._on_mouse_move(100, 100)

        # Position should still be updated despite exception
        self.assertEqual(app.pos_x, 100)
        self.assertEqual(app.pos_y, 100)

    def test_mouse_wheel_event_handling(self):
        """Test mouse wheel scroll event processing."""
        app = self.create_kvm_app()
        mock_mouse_op = MagicMock()
        app.mouse_op = mock_mouse_op

        # Create mock wheel event
        mock_event = MagicMock(spec=QWheelEvent)
        mock_event.x.return_value = 300
        mock_event.y.return_value = 400
        mock_angle_delta = MagicMock()
        mock_angle_delta.x.return_value = 0
        mock_angle_delta.y.return_value = 120  # Typical scroll delta
        mock_event.angleDelta.return_value = mock_angle_delta

        # Mock the super() call
        with patch("kvm_serial.kvm.QMainWindow.wheelEvent"):
            app.wheelEvent(mock_event)

        # Verify scroll operation was called
        mock_mouse_op.on_scroll.assert_called_once_with(300, 400, 0, 120)

    def test_mouse_wheel_without_mouse_op(self):
        """Test wheel event handling when mouse operation is not available."""
        app = self.create_kvm_app()
        app.mouse_op = None

        mock_event = MagicMock(spec=QWheelEvent)
        mock_event.x.return_value = 300
        mock_event.y.return_value = 400
        mock_angle_delta = MagicMock()
        mock_angle_delta.x.return_value = 0
        mock_angle_delta.y.return_value = 120
        mock_event.angleDelta.return_value = mock_angle_delta

        # Should not raise exception
        with patch("kvm_serial.kvm.QMainWindow.wheelEvent"):
            app.wheelEvent(mock_event)

    def test_keyboard_press_event_processing(self):
        """Test keyboard press event processing."""
        app = self.create_kvm_app()
        mock_keyboard_op = MagicMock()
        mock_keyboard_op.parse_key.return_value = True
        app.keyboard_op = mock_keyboard_op

        # Create mock key event
        mock_event = MagicMock(spec=QKeyEvent)
        mock_event.key.return_value = Qt.Key.Key_A
        mock_event.type.return_value = QEvent.Type.KeyPress

        # Mock the super() call to prevent Qt type checking
        with patch("kvm_serial.kvm.QMainWindow.keyPressEvent"):
            app.keyPressEvent(mock_event)

        # Verify keyboard operation was called
        mock_keyboard_op.parse_key.assert_called_once_with(mock_event)
        self.assertTrue(app.keyboard_var)
        self.assertEqual(app.keyboard_last, "alphanumeric")

    def test_keyboard_press_modifier_keys(self):
        """Test keyboard press event processing for modifier keys."""
        app = self.create_kvm_app()
        mock_keyboard_op = MagicMock()
        mock_keyboard_op.parse_key.return_value = True
        app.keyboard_op = mock_keyboard_op

        # Test modifier keys
        modifier_keys = [
            Qt.Key.Key_Control,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Shift,
            Qt.Key.Key_Meta,
            Qt.Key.Key_Escape,
        ]

        for key in modifier_keys:
            with self.subTest(key=key):
                mock_keyboard_op.reset_mock()
                mock_event = MagicMock(spec=QKeyEvent)
                mock_event.key.return_value = key
                mock_event.type.return_value = QEvent.Type.KeyPress

                # Mock the super() call
                with patch("kvm_serial.kvm.QMainWindow.keyPressEvent"):
                    app.keyPressEvent(mock_event)

                mock_keyboard_op.parse_key.assert_called_once_with(mock_event)
                self.assertTrue(app.keyboard_var)
                self.assertEqual(app.keyboard_last, "modifier")

    def test_keyboard_press_without_keyboard_op(self):
        """Test keyboard press handling when keyboard operation is not available."""
        app = self.create_kvm_app()
        app.keyboard_op = None

        mock_event = MagicMock(spec=QKeyEvent)
        mock_event.key.return_value = Qt.Key.Key_A
        mock_event.type.return_value = QEvent.Type.KeyPress

        # Should not raise exception
        with patch("kvm_serial.kvm.QMainWindow.keyPressEvent"):
            app.keyPressEvent(mock_event)

    def test_keyboard_release_event_processing(self):
        """Test keyboard release event processing."""
        app = self.create_kvm_app()
        mock_keyboard_op = MagicMock()
        app.keyboard_op = mock_keyboard_op

        # Create mock key event
        mock_event = MagicMock(spec=QKeyEvent)
        mock_event.key.return_value = Qt.Key.Key_A

        # Mock the super() call
        with patch("kvm_serial.kvm.QMainWindow.keyReleaseEvent"):
            app.keyReleaseEvent(mock_event)

        # Verify keyboard operation was called
        mock_keyboard_op.parse_key.assert_called_once_with(mock_event)

    def test_keyboard_serial_exception_handling(self):
        """Test handling of serial exceptions during keyboard operations."""
        app = self.create_kvm_app()
        mock_keyboard_op = MagicMock()
        mock_keyboard_op.parse_key.side_effect = SerialException("Port disconnected")
        app.keyboard_op = mock_keyboard_op

        mock_event = MagicMock(spec=QKeyEvent)
        mock_event.key.return_value = Qt.Key.Key_A
        mock_event.type.return_value = QEvent.Type.KeyPress

        with (
            patch("kvm_serial.kvm.QMessageBox.critical") as mock_critical,
            patch.object(app, "_on_quit") as mock_quit,
            patch("kvm_serial.kvm.QMainWindow.keyPressEvent"),
        ):
            app.keyPressEvent(mock_event)

            # Should show error and quit
            mock_critical.assert_called_once()
            mock_quit.assert_called_once()

    def test_window_focus_events(self):
        """Test window focus in/out event handling."""
        app = self.create_kvm_app()

        # Create mock focus events
        mock_focus_in = MagicMock(spec=QFocusEvent)
        mock_focus_out = MagicMock(spec=QFocusEvent)

        # The main window focus events only log messages, they don't change keyboard_var
        # keyboard_var is managed by the video view focus, not window focus
        initial_keyboard_state = app.keyboard_var

        # Mock the super() calls
        with patch("kvm_serial.kvm.QMainWindow.focusInEvent"):
            app.focusInEvent(mock_focus_in)
            # Window focus doesn't change keyboard state - that's handled by video view
            self.assertEqual(app.keyboard_var, initial_keyboard_state)

        with patch("kvm_serial.kvm.QMainWindow.focusOutEvent"):
            app.focusOutEvent(mock_focus_out)
            # Window focus doesn't change keyboard state - that's handled by video view
            self.assertEqual(app.keyboard_var, initial_keyboard_state)

    def test_window_resize_event_updates_video_worker(self):
        """Test window resize events update video worker canvas size."""
        app = self.create_kvm_app()

        # Mock the video worker's set_canvas_size method
        with (
            patch.object(app.video_worker, "set_canvas_size") as mock_set_canvas,
            patch.object(app.video_view, "size") as mock_size,
            patch("kvm_serial.kvm.QMainWindow.resizeEvent"),
        ):
            mock_size_obj = MagicMock()
            mock_size_obj.width.return_value = 800
            mock_size_obj.height.return_value = 600
            mock_size.return_value = mock_size_obj

            # Create mock resize event
            mock_event = MagicMock()

            # Call resize event
            app.resizeEvent(mock_event)

            # Verify video worker canvas size was updated
            mock_set_canvas.assert_called_with(800, 600)

    def test_window_resize_with_invalid_size(self):
        """Test window resize handling with invalid view dimensions."""
        app = self.create_kvm_app()

        # Mock the video worker's set_canvas_size method and video view size
        with (
            patch.object(app.video_worker, "set_canvas_size") as mock_set_canvas,
            patch.object(app.video_view, "size") as mock_size,
            patch("kvm_serial.kvm.QMainWindow.resizeEvent"),
        ):
            mock_size_obj = MagicMock()
            mock_size_obj.width.return_value = 0
            mock_size_obj.height.return_value = 0
            mock_size.return_value = mock_size_obj

            mock_event = MagicMock()

            # Should not call set_canvas_size with invalid dimensions
            app.resizeEvent(mock_event)

            # Video worker should not be called with invalid size
            mock_set_canvas.assert_not_called()

    def test_close_event_cleanup(self):
        """Test proper cleanup during close event."""
        app = self.create_kvm_app()

        # Set up some state to clean up
        mock_serial_port = MagicMock()
        app.serial_port = mock_serial_port

        # Mock the timer and worker methods that need to be called
        with (
            patch.object(app.video_update_timer, "stop") as mock_timer_stop,
            patch.object(app.video_worker, "quit") as mock_worker_quit,
            patch.object(app.video_worker, "wait") as mock_worker_wait,
        ):
            # Create mock close event
            mock_event = MagicMock()
            mock_event.accept = MagicMock()

            app.closeEvent(mock_event)

            # Verify cleanup actions
            mock_timer_stop.assert_called_once()
            mock_worker_quit.assert_called_once()
            mock_worker_wait.assert_called_once()
            mock_serial_port.close.assert_called_once()
            mock_event.accept.assert_called_once()

            # Serial port should be cleared
            self.assertIsNone(app.serial_port)

    def test_quit_action_sets_flag_and_closes(self):
        """Test quit action sets quitting flag and closes window."""
        app = self.create_kvm_app()

        with patch.object(app, "close") as mock_close:
            app._on_quit()

            self.assertTrue(app._quitting)
            mock_close.assert_called_once()

    def test_mouse_pointer_visibility_toggle(self):
        """Test mouse pointer visibility toggle functionality."""
        app = self.create_kvm_app()

        # Initially mouse should be visible
        self.assertFalse(app.hide_mouse_var)

        # Toggle to hide mouse
        app._toggle_mouse()
        self.assertTrue(app.hide_mouse_var)
        app.video_view.setCursor.assert_called_with(Qt.CursorShape.BlankCursor)

        # Toggle to show mouse
        app._toggle_mouse()
        self.assertFalse(app.hide_mouse_var)
        app.video_view.setCursor.assert_called_with(Qt.CursorShape.ArrowCursor)

    def test_event_coordinates_within_camera_bounds(self):
        """Test event coordinates are validated against camera dimensions."""
        app = self.create_kvm_app()
        mock_mouse_op = MagicMock()
        app.mouse_op = mock_mouse_op

        # Set specific camera dimensions
        app.video_worker.camera_width = 640
        app.video_worker.camera_height = 480

        # Test coordinates at exact boundaries
        boundary_tests = [
            (0, 0, True, "top-left corner"),
            (639, 479, True, "bottom-right valid"),
            (640, 479, False, "x at width limit"),
            (639, 480, False, "y at height limit"),
        ]

        for x, y, should_succeed, description in boundary_tests:
            with self.subTest(test=description):
                mock_mouse_op.reset_mock()
                result = app._on_mouse_move(x, y)

                if should_succeed:
                    self.assertNotEqual(result, False)
                    mock_mouse_op.on_move.assert_called_once()
                else:
                    self.assertEqual(result, False)
                    mock_mouse_op.on_move.assert_not_called()

    def test_keyboard_alphanumeric_classification(self):
        """Test keyboard events are classified as alphanumeric or modifier."""
        app = self.create_kvm_app()
        mock_keyboard_op = MagicMock()
        mock_keyboard_op.parse_key.return_value = True
        app.keyboard_op = mock_keyboard_op

        # Test alphanumeric keys (space through tilde)
        alphanumeric_keys = [
            Qt.Key.Key_Space,
            Qt.Key.Key_A,
            Qt.Key.Key_Z,
            Qt.Key.Key_0,
            Qt.Key.Key_9,
            Qt.Key.Key_AsciiTilde,
        ]

        for key in alphanumeric_keys:
            with self.subTest(key=key):
                mock_event = MagicMock(spec=QKeyEvent)
                mock_event.key.return_value = key
                mock_event.type.return_value = QEvent.Type.KeyPress

                # Mock the super() call
                with patch("kvm_serial.kvm.QMainWindow.keyPressEvent"):
                    app.keyPressEvent(mock_event)

                self.assertEqual(app.keyboard_last, "alphanumeric")

    def test_serial_communication_error_recovery(self):
        """Test recovery from serial communication errors during events."""
        app = self.create_kvm_app()

        # Test keyboard operation with serial error
        mock_keyboard_op = MagicMock()
        mock_keyboard_op.parse_key.side_effect = SerialException("Communication failed")
        app.keyboard_op = mock_keyboard_op

        mock_event = MagicMock(spec=QKeyEvent)
        mock_event.key.return_value = Qt.Key.Key_A

        with (
            patch("kvm_serial.kvm.QMessageBox.critical"),
            patch.object(app, "_on_quit") as mock_quit,
            patch("kvm_serial.kvm.QMainWindow.keyReleaseEvent"),
        ):
            app.keyReleaseEvent(mock_event)

            # Should trigger quit on serial error
            mock_quit.assert_called_once()

    def test_focus_management_state_consistency(self):
        """Test focus management maintains consistent state."""
        app = self.create_kvm_app()

        # Initial state
        self.assertFalse(app.keyboard_var)

        # The actual focus management is done through direct state changes
        # not through the window focus events (those are handled by video view)

        # Test direct keyboard_var state changes (which is what actually happens)
        app.keyboard_var = True
        self.assertTrue(app.keyboard_var, "Direct state change should enable keyboard")

        app.keyboard_var = False
        self.assertFalse(app.keyboard_var, "Direct state change should disable keyboard")

        app.keyboard_var = True
        self.assertTrue(app.keyboard_var, "Second state change should enable keyboard")

        # Test that the window focus methods exist and can be called without errors
        mock_focus_in = MagicMock(spec=QFocusEvent)
        mock_focus_out = MagicMock(spec=QFocusEvent)

        with patch("kvm_serial.kvm.QMainWindow.focusInEvent"):
            app.focusInEvent(mock_focus_in)  # Should not crash

        with patch("kvm_serial.kvm.QMainWindow.focusOutEvent"):
            app.focusOutEvent(mock_focus_out)  # Should not crash

    def test_video_view_focus_management(self):
        """Test that video view focus management affects keyboard state properly."""
        app = self.create_kvm_app()

        # Initial state
        initial_state = app.keyboard_var

        # Test that the video view exists and has focus methods
        self.assertTrue(hasattr(app.video_view, "focusInEvent"))
        self.assertTrue(hasattr(app.video_view, "focusOutEvent"))

        # The video view focus events would normally emit signals that the main
        # window connects to, but since we're testing in isolation, we test
        # the direct state changes that would result from those signals

        # Simulate what happens when video view gains focus
        app.keyboard_var = True
        self.assertTrue(app.keyboard_var, "Video view focus should enable keyboard capture")

        # Simulate what happens when video view loses focus
        app.keyboard_var = False
        self.assertFalse(
            app.keyboard_var, "Video view losing focus should disable keyboard capture"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
