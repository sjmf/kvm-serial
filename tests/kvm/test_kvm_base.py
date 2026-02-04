#!/usr/bin/env python
"""
Base test class for KVM application testing.
Provides common mocking infrastructure and utilities for all KVM test suites.
"""

import unittest
from unittest.mock import patch, MagicMock
import sys


class KVMTestBase(unittest.TestCase):
    """
    Base test class providing common mocking infrastructure for KVM tests.

    Handles:
    - PyQt5 GUI component mocking to prevent window creation
    - Hardware dependency mocking (serial, video, etc.)
    - Common setup/teardown patterns
    - Reusable mock creation utilities
    """

    def setUp(self):
        """Set up common test environment with comprehensive mocking."""
        # Mock all PyQt5 imports before importing kvm module
        self.qt_patches = self._setup_qt_mocks()

        # Mock external dependencies - each returns a single patch object
        self.external_patches = [
            self._setup_serial_mock(),
            self._setup_cv2_mock(),
            self._setup_settings_mock(),
        ]

        # Hardware patches are returned as a list
        self.hardware_patches = self._setup_hardware_mocks()

        # Start all patches
        all_patches = self.qt_patches + self.external_patches + self.hardware_patches
        for patcher in all_patches:
            patcher.start()

        # Import is now safe after mocking
        from kvm_serial import kvm

        self.kvm_module = kvm

    def tearDown(self):
        """Clean up all patches and reset module state."""
        patch.stopall()

        # Remove kvm module from sys.modules to ensure clean import next time
        modules_to_remove = [
            "kvm_serial.kvm",
            "kvm_serial.backend.video",
            "kvm_serial.utils.communication",
            "kvm_serial.utils.settings",
        ]

        for module in modules_to_remove:
            if module in sys.modules:
                del sys.modules[module]

    def _setup_qt_mocks(self):
        """Set up comprehensive PyQt5 mocking to prevent GUI creation."""
        patches = []

        # Mock QApplication to prevent GUI startup
        patches.append(patch("PyQt5.QtWidgets.QApplication"))

        # Mock QMainWindow initialization to prevent GUI creation
        def mock_qmainwindow_init(self):
            pass

        patches.append(patch("PyQt5.QtWidgets.QMainWindow.__init__", mock_qmainwindow_init))

        # Mock QMainWindow methods that get called during initialization
        qmainwindow_methods = [
            "setWindowTitle",
            "setMinimumSize",
            "resize",
            "setCentralWidget",
            "setFocusPolicy",
            "menuBar",
            "setStatusBar",
            "setMenuBar",
            "show",
            "close",
        ]

        for method in qmainwindow_methods:
            patches.append(patch(f"PyQt5.QtWidgets.QMainWindow.{method}", return_value=MagicMock()))

        # Mock all Qt widgets used by the application
        qt_widgets = [
            "QLabel",
            "QAction",
            "QMenu",
            "QStatusBar",
            "QMessageBox",
            "QFileDialog",
            "QGraphicsView",
            "QGraphicsScene",
            "QGraphicsPixmapItem",
            "QVBoxLayout",
            "QWidget",
            "QSizePolicy",
        ]

        for widget in qt_widgets:
            patches.append(patch(f"PyQt5.QtWidgets.{widget}"))

        # Mock Qt Core components
        qt_core = ["QTimer", "QThread", "QMutex", "QMutexLocker"]
        for core_item in qt_core:
            patches.append(patch(f"PyQt5.QtCore.{core_item}"))

        # Mock QApplication.processEvents specifically
        patches.append(patch("PyQt5.QtWidgets.QApplication.processEvents"))

        # Mock Qt GUI components
        qt_gui = ["QImage", "QPixmap", "QPainter"]
        for gui_item in qt_gui:
            patches.append(patch(f"PyQt5.QtGui.{gui_item}"))

        return patches

    def _setup_serial_mock(self):
        """Set up serial communication mocking."""
        return patch("serial.Serial")

    def _setup_cv2_mock(self):
        """Set up OpenCV mocking."""
        return patch("cv2.cvtColor")

    def _setup_settings_mock(self):
        """Set up settings utility mocking."""
        return patch("kvm_serial.kvm.settings_util")

    def _setup_hardware_mocks(self):
        """Set up hardware-related mocking to prevent device access."""
        # Import video module explicitly to avoid string-based patch resolution
        # failures when kvm_serial.backend is pre-loaded in sys.modules without
        # the video submodule attribute (cross-group test pollution).
        from kvm_serial.backend import video as video_mod

        # Create individual patches for hardware components
        hardware_patches = [
            # Video capture mocking
            patch.object(video_mod, "CaptureDevice"),
            patch.object(video_mod, "CameraProperties"),
            patch("kvm_serial.kvm.CaptureDevice"),
            patch("kvm_serial.kvm.VideoCaptureWorker"),
            # Serial communication mocking
            patch("kvm_serial.utils.communication.list_serial_ports"),
            patch("kvm_serial.kvm.list_serial_ports"),
            # Operation classes mocking
            patch("kvm_serial.kvm.QtOp"),
            patch("kvm_serial.kvm.MouseOp"),
        ]

        # Store patches for cleanup and return them
        self._hardware_patches = hardware_patches
        return hardware_patches

    # Utility methods for common test scenarios

    def create_kvm_app(self):
        """Create a KVMQtGui instance with all hardware access safely mocked."""
        from kvm_serial.kvm import KVMQtGui

        return KVMQtGui()

    def create_mock_serial_ports(self, ports=None):
        """Create a list of mock serial port names."""
        if ports is None:
            ports = ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0"]
        return ports

    def create_mock_cameras(self, count=2):
        """Create a list of mock camera objects."""
        cameras = []
        for i in range(count):
            mock_camera = MagicMock()
            mock_camera.__str__ = MagicMock(return_value=f"Camera {i}")
            mock_camera.index = i
            mock_camera.width = 1280
            mock_camera.height = 720
            cameras.append(mock_camera)
        return cameras

    def create_mock_serial_instance(self):
        """Create a mock serial port instance."""
        mock_serial = MagicMock()
        mock_serial.close = MagicMock()
        return mock_serial

    def assert_gui_method_not_called(self, method_name):
        """Assert that a GUI method was not called (useful for headless testing)."""
        # This can be extended to track specific GUI method calls if needed
        pass

    def patch_kvm_method(self, app, method_name, return_value=None, side_effect=None):
        """
        Convenience method to patch a KVM app method.

        Args:
            app: KVMQtGui instance
            method_name: Name of method to patch (e.g., '_populate_serial_ports')
            return_value: Value to return from the patched method
            side_effect: Side effect for the patched method

        Returns:
            Mock object for the patched method
        """
        return patch.object(app, method_name, return_value=return_value, side_effect=side_effect)

    def assert_error_handling(self, mock_messagebox_method, expected_calls=1):
        """
        Assert that error handling (QMessageBox) was called correctly.

        Args:
            mock_messagebox_method: The mocked QMessageBox method (warning, critical, etc.)
            expected_calls: Expected number of calls (default: 1)
        """
        if expected_calls == 1:
            mock_messagebox_method.assert_called_once()
        else:
            self.assertEqual(mock_messagebox_method.call_count, expected_calls)

    def get_default_baud_rates(self):
        """Get the default baud rates used by the application."""
        return [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]

    def get_default_settings(self):
        """Get default application settings for testing."""
        return {
            "serial_port": "/dev/ttyUSB0",
            "baud_rate": "9600",
            "video_device": "0",
            "windowed": "False",
            "statusbar": "True",
            "verbose": "False",
            "hide_mouse": "False",
        }


class KVMTestMixins:
    """
    Mixin classes for specific testing scenarios.
    Can be combined with KVMTestBase for targeted functionality.
    """

    class SerialTestMixin:
        """Mixin for serial port testing functionality."""

        def setup_serial_test_data(self):
            """Set up common serial test data."""
            self.test_ports = ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0"]
            self.test_baud_rates = [9600, 115200, 38400]

        def assert_serial_initialization(self, app, expected_port, expected_baud):
            """Assert serial port was initialized correctly."""
            self.assertEqual(app.serial_port_var, expected_port)
            self.assertEqual(app.baud_rate_var, expected_baud)

    class VideoTestMixin:
        """Mixin for video device testing functionality."""

        def setup_video_test_data(self):
            """Set up common video test data."""
            self.test_cameras = self.create_mock_cameras(3)

        def assert_video_device_selection(self, app, expected_index, expected_device):
            """Assert video device was selected correctly."""
            self.assertEqual(app.video_var, expected_index)
            self.assertEqual(app.video_device_var, expected_device)

    class SettingsTestMixin:
        """Mixin for settings testing functionality."""

        def create_test_settings(self, overrides=None):
            """Create test settings with optional overrides."""
            settings = self.get_default_settings()
            if overrides:
                settings.update(overrides)
            return settings

        def assert_settings_loaded(self, app, expected_settings):
            """Assert settings were loaded correctly into the app."""
            for key, value in expected_settings.items():
                if hasattr(app, f"{key}_var"):
                    app_value = getattr(app, f"{key}_var")
                    if isinstance(app_value, bool):
                        expected_bool = value.lower() == "true"
                        self.assertEqual(app_value, expected_bool)
                    else:
                        self.assertEqual(str(app_value), str(value))


# Convenience function for creating combined test classes
def create_kvm_test_class(*mixins):
    """
    Create a test class combining KVMTestBase with specified mixins.

    Usage:
        class MyTest(create_kvm_test_class(SerialTestMixin, VideoTestMixin)):
            def test_something(self):
                pass
    """
    class_dict = {}
    bases = (KVMTestBase,) + mixins

    return type("KVMTestClass", bases, class_dict)
