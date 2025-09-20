#!/usr/bin/env python
"""
Test suite for KVM settings persistence functionality.
Uses KVMTestBase for common mocking infrastructure.
"""

import unittest
from unittest.mock import patch, MagicMock, call

# Import the base test class
from test_kvm_base import KVMTestBase, KVMTestMixins


class TestKVMSettingsPersistence(
    KVMTestBase,
    KVMTestMixins.SerialTestMixin,
    KVMTestMixins.VideoTestMixin,
    KVMTestMixins.SettingsTestMixin,
):
    """Test class for KVM settings persistence functionality."""

    def test_load_settings_partial_config(self):
        """Test loading with only some settings present."""
        app = self.create_kvm_app()
        partial_settings = {
            "serial_port": "/dev/ttyUSB0",
            "verbose": "True",
            # Missing other settings - should use defaults
        }

        app.serial_ports = ["/dev/ttyUSB0", "/dev/ttyUSB1"]
        app.video_devices = self.create_mock_cameras(2)
        app.baud_rates = self.get_default_baud_rates()
        self._setup_mock_menus(app)

        with (
            patch("kvm_serial.kvm.settings_util.load_settings", return_value=partial_settings),
            self.patch_kvm_method(app, "_KVMQtGui__init_serial"),
            self.patch_kvm_method(app, "_apply_log_level"),
        ):
            app._load_settings("test_config.ini")

            # Verify only provided settings were applied
            self.assertEqual(app.serial_port_var, "/dev/ttyUSB0")
            self.assertTrue(app.verbose_var)
            # Other settings should remain at defaults
            self.assertFalse(app.window_var)  # Default
            self.assertTrue(app.show_status_var)  # Default

    def test_load_settings_invalid_serial_port(self):
        """Test handling of invalid serial port in settings."""
        app = self.create_kvm_app()
        invalid_settings = self.create_test_settings(
            {"serial_port": "/dev/invalid_port"}  # Not in available ports
        )

        app.serial_ports = ["/dev/ttyUSB0", "/dev/ttyUSB1"]
        app.video_devices = self.create_mock_cameras(2)
        app.baud_rates = self.get_default_baud_rates()
        self._setup_mock_menus(app)

        with (
            patch("kvm_serial.kvm.settings_util.load_settings", return_value=invalid_settings),
            self.patch_kvm_method(app, "_KVMQtGui__init_serial"),
        ):
            # Store original value
            original_port = app.serial_port_var

            app._load_settings("test_config.ini")

            # Invalid port should be ignored, original value retained
            self.assertEqual(app.serial_port_var, original_port)

    def test_load_settings_invalid_baud_rate(self):
        """Test handling of invalid baud rate in settings."""
        app = self.create_kvm_app()
        invalid_settings = self.create_test_settings({"baud_rate": "999999"})  # Invalid baud rate

        app.serial_ports = ["/dev/ttyUSB0"]
        app.video_devices = self.create_mock_cameras(1)
        app.baud_rates = self.get_default_baud_rates()
        self._setup_mock_menus(app)

        with (
            patch("kvm_serial.kvm.settings_util.load_settings", return_value=invalid_settings),
            self.patch_kvm_method(app, "_KVMQtGui__init_serial"),
        ):
            original_baud = app.baud_rate_var

            app._load_settings("test_config.ini")

            # Invalid baud rate should be ignored
            self.assertEqual(app.baud_rate_var, original_baud)

    def test_load_settings_invalid_video_device(self):
        """Test handling of invalid video device index."""
        app = self.create_kvm_app()

        # Test various invalid video device values
        invalid_values = ["10", "-1", "invalid", ""]

        for invalid_value in invalid_values:
            with self.subTest(video_device=invalid_value):
                invalid_settings = self.create_test_settings({"video_device": invalid_value})

                app.video_devices = self.create_mock_cameras(2)  # Only 0, 1 valid
                self._setup_mock_menus(app)

                with (
                    patch(
                        "kvm_serial.kvm.settings_util.load_settings", return_value=invalid_settings
                    ),
                    self.patch_kvm_method(app, "_KVMQtGui__init_serial"),
                ):
                    original_video_var = app.video_var

                    app._load_settings("test_config.ini")

                    # Invalid video device should not change current setting
                    # (or should be handled gracefully)
                    if invalid_value in ["10", "-1"]:
                        # Out of range indices should be ignored
                        self.assertEqual(app.video_var, original_video_var)

    def test_load_settings_video_device_boundary_cases(self):
        """Test video device loading with boundary cases."""
        app = self.create_kvm_app()
        app.video_devices = self.create_mock_cameras(3)  # Indices 0, 1, 2
        app.video_worker = MagicMock()
        self._setup_mock_menus(app)

        # Test valid boundary cases
        boundary_cases = [
            ("0", 0),  # First device
            ("2", 2),  # Last device
        ]

        for setting_value, expected_index in boundary_cases:
            with self.subTest(video_device=setting_value):
                settings = self.create_test_settings({"video_device": setting_value})

                with (
                    patch("kvm_serial.kvm.settings_util.load_settings", return_value=settings),
                    self.patch_kvm_method(app, "_KVMQtGui__init_serial"),
                ):
                    app._load_settings("test_config.ini")

                    self.assertEqual(app.video_var, expected_index)
                    app.video_worker.set_camera_index.assert_called_with(expected_index)

    def test_save_settings_success(self):
        """Test successful settings saving."""
        app = self.create_kvm_app()
        app.serial_port_var = "/dev/ttyUSB1"
        app.baud_rate_var = 115200
        app.video_var = 2
        app.window_var = True
        app.show_status_var = False
        app.verbose_var = True
        app.hide_mouse_var = True

        expected_settings = {
            "serial_port": "/dev/ttyUSB1",
            "video_device": "2",
            "baud_rate": "115200",
            "windowed": "True",
            "statusbar": "False",
            "verbose": "True",
            "hide_mouse": "True",
        }

        with (
            patch("kvm_serial.kvm.settings_util.save_settings") as mock_save,
            patch("kvm_serial.kvm.QMessageBox.information") as mock_info,
        ):
            app._save_settings()

            mock_save.assert_called_once_with(app.CONFIG_FILE, "KVM", expected_settings)
            mock_info.assert_called_once()

    def test_boolean_settings_conversion(self):
        """Test proper conversion of boolean settings to/from strings."""
        app = self.create_kvm_app()
        self._setup_mock_menus(app)

        # Test all boolean combinations
        boolean_test_cases = [
            ("True", True),
            ("true", False),  # Case sensitive - should be False
            ("False", False),
            ("false", False),  # Case sensitive
            ("", False),  # Empty string
            ("1", False),  # Non-boolean string
        ]

        for str_value, expected_bool in boolean_test_cases:
            with self.subTest(value=str_value):
                settings = self.create_test_settings(
                    {
                        "verbose": str_value,
                        "windowed": str_value,
                        "statusbar": str_value,
                        "hide_mouse": str_value,
                    }
                )

                with (
                    patch("kvm_serial.kvm.settings_util.load_settings", return_value=settings),
                    self.patch_kvm_method(app, "_KVMQtGui__init_serial"),
                    self.patch_kvm_method(app, "_apply_log_level"),
                ):
                    app._load_settings("test_config.ini")

                    self.assertEqual(
                        app.verbose_var, expected_bool, f"verbose_var failed for '{str_value}'"
                    )
                    self.assertEqual(
                        app.window_var, expected_bool, f"window_var failed for '{str_value}'"
                    )
                    self.assertEqual(
                        app.show_status_var,
                        expected_bool,
                        f"show_status_var failed for '{str_value}'",
                    )
                    self.assertEqual(
                        app.hide_mouse_var,
                        expected_bool,
                        f"hide_mouse_var failed for '{str_value}'",
                    )

    def test_menu_selection_updates_on_load(self):
        """Test that menu selections are updated when settings are loaded."""
        app = self.create_kvm_app()
        app.serial_ports = ["/dev/ttyUSB0", "/dev/ttyUSB1"]
        app.video_devices = self.create_mock_cameras(2)
        app.baud_rates = self.get_default_baud_rates()

        # Set up mock menus with action tracking
        mock_serial_actions = [MagicMock(), MagicMock()]
        mock_serial_actions[0].text.return_value = "/dev/ttyUSB0"
        mock_serial_actions[1].text.return_value = "/dev/ttyUSB1"

        mock_baud_actions = [MagicMock(), MagicMock()]
        mock_baud_actions[0].text.return_value = "9600"
        mock_baud_actions[1].text.return_value = "115200"

        mock_video_actions = [MagicMock(), MagicMock()]
        mock_video_actions[0].text.return_value = "Camera 0"
        mock_video_actions[1].text.return_value = "Camera 1"

        app.serial_port_menu = MagicMock()
        app.serial_port_menu.actions.return_value = mock_serial_actions
        app.baud_rate_menu = MagicMock()
        app.baud_rate_menu.actions.return_value = mock_baud_actions
        app.video_device_menu = MagicMock()
        app.video_device_menu.actions.return_value = mock_video_actions

        settings = self.create_test_settings(
            {"serial_port": "/dev/ttyUSB1", "baud_rate": "115200", "video_device": "1"}
        )

        with (
            patch("kvm_serial.kvm.settings_util.load_settings", return_value=settings),
            self.patch_kvm_method(app, "_KVMQtGui__init_serial"),
        ):
            app._load_settings("test_config.ini")

            # Verify correct menu items were checked
            mock_serial_actions[1].setChecked.assert_called_with(True)
            mock_baud_actions[1].setChecked.assert_called_with(True)
            mock_video_actions[1].setChecked.assert_called_with(True)

    def test_ui_state_updates_on_load(self):
        """Test that UI components are updated when settings are loaded."""
        app = self.create_kvm_app()

        # Mock UI components that should be updated
        app.video_view = MagicMock()
        app.mouse_action = MagicMock()
        app.verbose_action = MagicMock()
        self._setup_mock_menus(app)

        settings = self.create_test_settings({"hide_mouse": "True", "verbose": "True"})

        with (
            patch("kvm_serial.kvm.settings_util.load_settings", return_value=settings),
            patch("kvm_serial.kvm.Qt.CursorShape.BlankCursor", "BLANK"),
            self.patch_kvm_method(app, "_KVMQtGui__init_serial"),
            self.patch_kvm_method(app, "_apply_log_level") as mock_apply_log,
        ):
            app._load_settings("test_config.ini")

            # Verify UI updates
            app.video_view.setCursor.assert_called_with("BLANK")
            app.mouse_action.setChecked.assert_called_with(True)
            app.verbose_action.setChecked.assert_called_with(True)
            mock_apply_log.assert_called_once()

    def test_settings_loading_with_missing_menus(self):
        """Test error handling when menus are not initialized."""
        app = self.create_kvm_app()

        # Don't set up menus - should raise TypeError
        app.video_device_menu = None
        app.baud_rate_menu = None
        app.serial_port_menu = None

        settings = self.create_test_settings()

        with (
            patch("kvm_serial.kvm.settings_util.load_settings", return_value=settings),
            self.assertRaises(TypeError),
        ):
            app._load_settings("test_config.ini")

    def test_load_settings_calls_init_serial(self):
        """Test that settings loading triggers serial initialization."""
        app = self.create_kvm_app()
        self._setup_mock_menus(app)

        settings = self.create_test_settings({"serial_port": "/dev/ttyUSB0", "baud_rate": "9600"})

        app.serial_ports = ["/dev/ttyUSB0"]
        app.baud_rates = self.get_default_baud_rates()

        with (
            patch("kvm_serial.kvm.settings_util.load_settings", return_value=settings),
            self.patch_kvm_method(app, "_KVMQtGui__init_serial") as mock_init_serial,
        ):
            app._load_settings("test_config.ini")

            # Serial initialization should be called after loading settings
            mock_init_serial.assert_called_once()

    def test_empty_settings_file_handling(self):
        """Test handling when settings file is empty or returns empty dict."""
        app = self.create_kvm_app()
        self._setup_mock_menus(app)

        with (
            patch("kvm_serial.kvm.settings_util.load_settings", return_value={}),
            self.patch_kvm_method(app, "_KVMQtGui__init_serial"),
        ):
            # Should not raise exception with empty settings
            app._load_settings("test_config.ini")

            # Default values should be retained
            self.assertIn(app.baud_rate_var, self.get_default_baud_rates())
            self.assertFalse(app.window_var)
            self.assertTrue(app.show_status_var)

    def test_settings_file_path_usage(self):
        """Test that correct file path is used for settings operations."""
        app = self.create_kvm_app()

        # Test save operation
        with patch("kvm_serial.kvm.settings_util.save_settings") as mock_save:
            app._save_settings()

            # Should use the CONFIG_FILE constant
            mock_save.assert_called_once()
            args = mock_save.call_args[0]
            self.assertEqual(args[0], app.CONFIG_FILE)
            self.assertEqual(args[1], "KVM")

    def test_verbose_logging_application(self):
        """Test that verbose logging setting is properly applied."""
        app = self.create_kvm_app()
        app.verbose_action = MagicMock()
        self._setup_mock_menus(app)

        settings = self.create_test_settings({"verbose": "True"})

        with (
            patch("kvm_serial.kvm.settings_util.load_settings", return_value=settings),
            self.patch_kvm_method(app, "_KVMQtGui__init_serial"),
            self.patch_kvm_method(app, "_apply_log_level") as mock_apply_log,
        ):
            app._load_settings("test_config.ini")

            # Verbose setting should be loaded and applied
            self.assertTrue(app.verbose_var)
            mock_apply_log.assert_called_once()

    def test_default_video_device_fallback(self):
        """Test fallback to first video device when setting is None."""
        app = self.create_kvm_app()
        app.video_devices = self.create_mock_cameras(2)
        app.video_worker = MagicMock()
        self._setup_mock_menus(app)

        # Settings with video_device as None (not present)
        settings = self.create_test_settings()
        del settings["video_device"]  # Remove video_device entirely

        with (
            patch("kvm_serial.kvm.settings_util.load_settings", return_value=settings),
            self.patch_kvm_method(app, "_KVMQtGui__init_serial"),
        ):
            app._load_settings("test_config.ini")

            # Should default to first device (index 0)
            app.video_worker.set_camera_index.assert_called_with(0)

    # Helper method to set up mock menus
    def _setup_mock_menus(self, app):
        """Set up mock menu objects for testing."""
        app.serial_port_menu = MagicMock()
        app.baud_rate_menu = MagicMock()
        app.video_device_menu = MagicMock()

        # Default empty actions
        app.serial_port_menu.actions.return_value = []
        app.baud_rate_menu.actions.return_value = []
        app.video_device_menu.actions.return_value = []


if __name__ == "__main__":
    unittest.main(verbosity=2)
