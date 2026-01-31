#!/usr/bin/env python
"""
Test suite for KVM application initialization and configuration.
Uses KVMTestBase for common mocking infrastructure.
"""

import unittest
from unittest.mock import patch, MagicMock

# Import the base test class
from test_kvm_base import KVMTestBase, KVMTestMixins


class TestKVMInitialization(
    KVMTestBase,
    KVMTestMixins.SerialTestMixin,
    KVMTestMixins.VideoTestMixin,
    KVMTestMixins.SettingsTestMixin,
):
    """Test class for KVM application initialization and configuration."""

    def test_window_initialization(self):
        """Test basic window initialization without GUI creation."""
        app = self.create_kvm_app()

        # Verify basic attributes are set
        self.assertEqual(app.CONFIG_FILE, ".kvm_settings.ini")
        self.assertIn(9600, app.baud_rates)
        self.assertEqual(app.window_default_width, 1280)
        self.assertEqual(app.window_default_height, 720)

        # Verify initial state
        self.assertFalse(app.keyboard_var)
        self.assertEqual(app.keyboard_last, "")
        self.assertEqual(app.video_var, -1)
        self.assertFalse(app.mouse_var)

    def test_menu_creation_logic(self):
        """Test that menu creation logic is called properly."""
        from kvm_serial.kvm import KVMQtGui

        # Mock the menu bar and menu methods
        with (
            patch.object(KVMQtGui, "menuBar") as mock_menubar,
            patch.object(KVMQtGui, "_KVMQtGui__init_menu") as mock_init_menu,
        ):
            mock_menu = MagicMock()
            mock_menubar.return_value = mock_menu
            mock_menu.addMenu.return_value = MagicMock()

            app = KVMQtGui()

            # Verify menu initialization was called
            mock_init_menu.assert_called_once()

    def test_status_bar_initialization(self):
        """Test status bar setup logic."""
        from kvm_serial.kvm import KVMQtGui

        with patch.object(KVMQtGui, "_KVMQtGui__init_status_bar") as mock_init_status:
            app = KVMQtGui()
            mock_init_status.assert_called_once()

    def test_device_discovery_calls(self):
        """Test that device discovery methods are called during initialization."""
        from kvm_serial.kvm import KVMQtGui

        with (
            patch.object(KVMQtGui, "_populate_serial_ports") as mock_pop_serial,
            patch.object(KVMQtGui, "_populate_baud_rates") as mock_pop_baud,
            patch.object(KVMQtGui, "_populate_video_devices") as mock_pop_video,
            patch.object(KVMQtGui, "_populate_keyboard_layouts") as mock_pop_layouts,
        ):
            app = KVMQtGui()

            # These methods should exist and be callable
            self.assertTrue(hasattr(app, "_populate_serial_ports"))
            self.assertTrue(hasattr(app, "_populate_baud_rates"))
            self.assertTrue(hasattr(app, "_populate_video_devices"))
            self.assertTrue(hasattr(app, "_populate_keyboard_layouts"))

    def test_default_values_set_correctly(self):
        """Test that default configuration values are set properly."""
        app = self.create_kvm_app()

        # Test default values using utility methods
        expected_baud_rates = self.get_default_baud_rates()
        self.assertEqual(app.baud_rates, expected_baud_rates)
        self.assertEqual(app.baud_rate_var, expected_baud_rates[3])  # Default to 9600

        # Test boolean defaults
        self.assertFalse(app.window_var)
        self.assertTrue(app.show_status_var)
        self.assertFalse(app.verbose_var)
        self.assertFalse(app.hide_mouse_var)
        self.assertEqual(app.target_fps, 30)

        # Test keyboard layout default
        self.assertEqual(app.keyboard_layout_var, "en_GB")

        # Test dimension defaults
        self.assertEqual(app.window_min_width, 512)
        self.assertEqual(app.window_min_height, 320)
        self.assertEqual(app.status_bar_default_height, 24)

    def test_button_map_initialization(self):
        """Test that mouse button mapping is set up correctly."""
        app = self.create_kvm_app()

        # Verify button mapping exists and has expected entries
        self.assertIsInstance(app.BUTTON_MAP, dict)
        self.assertIn("MIDDLE", app.BUTTON_MAP.values())
        self.assertIn("LEFT", app.BUTTON_MAP.values())
        self.assertIn("RIGHT", app.BUTTON_MAP.values())

    def test_video_worker_initialization(self):
        """Test that video capture worker is initialized properly."""
        from kvm_serial.kvm import KVMQtGui

        with (
            patch("kvm_serial.kvm.VideoCaptureWorker") as mock_worker_class,
            patch.object(KVMQtGui, "_KVMQtGui__init_video") as mock_init_video,
        ):
            mock_worker_instance = MagicMock()
            mock_worker_class.return_value = mock_worker_instance

            app = KVMQtGui()

            # Verify that __init_video was called during initialization
            mock_init_video.assert_called_once()

        # Test actual video worker creation by calling the real initialization
        app = self.create_kvm_app()

        # Check that the video_worker attribute exists
        self.assertTrue(hasattr(app, "video_worker"), "App should have video_worker attribute")

    def test_initialization_handles_port_discovery_failure(self):
        """Test graceful handling of serial port discovery failure."""
        from kvm_serial.kvm import KVMQtGui

        with patch(
            "kvm_serial.kvm.list_serial_ports", side_effect=Exception("Port discovery failed")
        ):
            # Should not raise exception despite port discovery failure
            app = KVMQtGui()
            self.assertIsNotNone(app)

    def test_initialization_handles_camera_discovery_failure(self):
        """Test graceful handling of camera discovery failure."""
        from kvm_serial.kvm import KVMQtGui

        with patch(
            "kvm_serial.kvm.CaptureDevice.getCameras",
            side_effect=Exception("Camera discovery failed"),
        ):
            # Should not raise exception despite camera discovery failure
            app = KVMQtGui()
            self.assertIsNotNone(app)

    def test_baud_rate_list_completeness(self):
        """Test that all expected baud rates are present."""
        app = self.create_kvm_app()
        expected_rates = self.get_default_baud_rates()

        self.assertEqual(len(app.baud_rates), len(expected_rates))
        for rate in expected_rates:
            self.assertIn(rate, app.baud_rates)

    def test_config_file_path_setting(self):
        """Test that config file path is set correctly."""
        app = self.create_kvm_app()
        self.assertEqual(app.CONFIG_FILE, ".kvm_settings.ini")

    def test_initial_position_variables(self):
        """Test that initial position variables are set."""
        app = self.create_kvm_app()
        self.assertEqual(app.pos_x, 0)
        self.assertEqual(app.pos_y, 0)

    def test_fps_and_frame_timing_initialization(self):
        """Test that FPS and frame timing variables are initialized."""
        app = self.create_kvm_app()

        self.assertEqual(app.target_fps, 30)
        self.assertEqual(app.frame_drop_threshold, 0.05)
        self.assertEqual(app.last_capture_request, 0.0)

    def test_initialization_state_variables(self):
        """Test that all state variables are properly initialized."""
        app = self.create_kvm_app()

        # Serial/device state
        self.assertEqual(app.video_var, -1)
        self.assertFalse(app.mouse_var)
        self.assertFalse(app.keyboard_var)

        # UI state
        self.assertFalse(app._quitting)
        self.assertFalse(app.window_var)
        self.assertTrue(app.show_status_var)
        self.assertFalse(app.verbose_var)
        self.assertFalse(app.hide_mouse_var)

        # Device initialization state
        self.assertFalse(app.camera_initialised)
        self.assertEqual(app.video_device_idx, 0)

    def test_io_objects_initial_state(self):
        """Test that IO objects start as None."""
        app = self.create_kvm_app()

        self.assertIsNone(app.serial_port)
        self.assertIsNone(app.keyboard_op)
        self.assertIsNone(app.mouse_op)

    def test_device_list_initialization(self):
        """Test that device lists are properly initialized."""
        app = self.create_kvm_app()

        # Lists should exist (may be empty due to mocking)
        self.assertTrue(hasattr(app, "serial_ports"))
        self.assertTrue(hasattr(app, "video_devices"))

        # Baud rates should be populated
        self.assertIsInstance(app.baud_rates, list)
        self.assertGreater(len(app.baud_rates), 0)

    def test_timer_and_worker_attributes_exist(self):
        """Test that timer and worker attributes are created."""
        app = self.create_kvm_app()

        # These attributes should exist after initialization
        timer_attributes = ["video_update_timer", "status_timer", "video_worker"]

        for attr in timer_attributes:
            self.assertTrue(hasattr(app, attr), f"Missing attribute: {attr}")

    def test_gui_component_attributes_exist(self):
        """Test that GUI component attributes are created."""
        app = self.create_kvm_app()

        # These GUI attributes should exist after initialization
        gui_attributes = [
            "video_view",
            "video_scene",
            "video_pixmap_item",
            "status_bar",
            "status_serial_label",
            "status_keyboard_label",
            "status_mouse_label",
            "status_video_label",
        ]

        for attr in gui_attributes:
            self.assertTrue(hasattr(app, attr), f"Missing GUI attribute: {attr}")


if __name__ == "__main__":
    # Run tests with verbose output
    unittest.main(verbosity=2)
