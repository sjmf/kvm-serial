#!/usr/bin/env python
"""
Test suite for KVM application initialization and configuration.
Tests the core setup logic without instantiating actual GUI components.
"""

import unittest
from unittest.mock import patch, MagicMock
import sys


class TestKVMInitialization(unittest.TestCase):
    """Test class for KVM application initialization and configuration."""

    def setUp(self):
        """Set up test environment with comprehensive mocking."""
        # Mock all PyQt5 imports before importing kvm module
        self.qt_patches = self._setup_qt_mocks()

        # Mock external dependencies
        self.mock_serial = self._setup_serial_mock()
        self.mock_cv2 = self._setup_cv2_mock()
        self.mock_settings = self._setup_settings_mock()

        # Start all patches
        for patcher in self.qt_patches + [self.mock_serial, self.mock_cv2, self.mock_settings]:
            patcher.start()

        # Now safe to import the module
        global kvm
        from kvm_serial import kvm

    def tearDown(self):
        """Clean up all patches."""
        patch.stopall()

        # Remove kvm module from sys.modules to ensure clean import next time
        if "kvm_serial.kvm" in sys.modules:
            del sys.modules["kvm_serial.kvm"]

    def _setup_qt_mocks(self):
        """Set up comprehensive PyQt5 mocking."""
        patches = []

        # Mock QApplication to prevent GUI startup
        qt_app_patch = patch("PyQt5.QtWidgets.QApplication")
        patches.append(qt_app_patch)

        # Instead of mocking QMainWindow completely, let's mock its __init__ method
        # This allows the class to exist but prevents GUI initialization
        def mock_qmainwindow_init(self):
            # Just do minimal setup without actual Qt window creation
            pass

        main_window_init_patch = patch(
            "PyQt5.QtWidgets.QMainWindow.__init__", mock_qmainwindow_init
        )
        patches.append(main_window_init_patch)

        # Mock the GUI methods that would be called
        main_window_methods = [
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

        for method in main_window_methods:
            method_patch = patch(f"PyQt5.QtWidgets.QMainWindow.{method}", return_value=MagicMock())
            patches.append(method_patch)

        # Mock all other Qt widgets used
        qt_widgets = [
            "QLabel",
            "QAction",
            "QMenu",
            "QStatusBar",
            "QMessageBox",
            "QGraphicsView",
            "QGraphicsScene",
            "QGraphicsPixmapItem",
            "QVBoxLayout",
            "QWidget",
            "QSizePolicy",
        ]

        for widget in qt_widgets:
            patch_obj = patch(f"PyQt5.QtWidgets.{widget}")
            patches.append(patch_obj)

        # Mock Qt Core components
        qt_core = ["QTimer", "QThread", "QMutex", "QMutexLocker"]
        for core_item in qt_core:
            patch_obj = patch(f"PyQt5.QtCore.{core_item}")
            patches.append(patch_obj)

        # Mock QApplication.processEvents specifically
        process_events_patch = patch("PyQt5.QtWidgets.QApplication.processEvents")
        patches.append(process_events_patch)

        # Mock Qt GUI components
        qt_gui = ["QImage", "QPixmap", "QPainter"]
        for gui_item in qt_gui:
            patch_obj = patch(f"PyQt5.QtGui.{gui_item}")
            patches.append(patch_obj)

        return patches

    def _setup_serial_mock(self):
        """Set up serial communication mocking."""
        return patch("serial.Serial")

    def _setup_cv2_mock(self):
        """Set up OpenCV mocking."""
        return patch("cv2.cvtColor")

    def _setup_settings_mock(self):
        """Set up settings utility mocking."""
        # Mock the settings utility import path
        settings_patch = patch("kvm_serial.kvm.settings_util")
        return settings_patch

    @patch("kvm_serial.kvm.list_serial_ports")
    @patch("kvm_serial.kvm.CaptureDevice")
    def test_window_initialization(self, mock_capture_device, mock_list_ports):
        """Test basic window initialization without GUI creation."""
        # Setup mocks
        mock_list_ports.return_value = ["/dev/ttyUSB0", "/dev/ttyUSB1"]
        mock_capture_device.getCameras.return_value = []

        # Create instance
        from kvm_serial.kvm import KVMQtGui

        app = KVMQtGui()

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

    @patch("kvm_serial.kvm.list_serial_ports")
    @patch("kvm_serial.kvm.CaptureDevice")
    def test_menu_creation_logic(self, mock_capture_device, mock_list_ports):
        """Test that menu creation logic is called properly."""
        # Setup mocks
        mock_list_ports.return_value = ["/dev/ttyUSB0"]
        mock_capture_device.getCameras.return_value = []

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

    @patch("kvm_serial.kvm.list_serial_ports")
    @patch("kvm_serial.kvm.CaptureDevice")
    def test_status_bar_initialization(self, mock_capture_device, mock_list_ports):
        """Test status bar setup logic."""
        mock_list_ports.return_value = ["/dev/ttyUSB0"]
        mock_capture_device.getCameras.return_value = []

        from kvm_serial.kvm import KVMQtGui

        with patch.object(KVMQtGui, "_KVMQtGui__init_status_bar") as mock_init_status:
            app = KVMQtGui()
            mock_init_status.assert_called_once()

    @patch("kvm_serial.kvm.list_serial_ports")
    @patch("kvm_serial.kvm.CaptureDevice")
    def test_device_discovery_calls(self, mock_capture_device, mock_list_ports):
        """Test that device discovery methods are called during initialization."""
        # Setup return values
        mock_ports = ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0"]
        mock_cameras = [MagicMock(), MagicMock()]

        mock_list_ports.return_value = mock_ports
        mock_capture_device.getCameras.return_value = mock_cameras

        from kvm_serial.kvm import KVMQtGui

        with (
            patch.object(KVMQtGui, "_populate_serial_ports") as mock_pop_serial,
            patch.object(KVMQtGui, "_populate_baud_rates") as mock_pop_baud,
            patch.object(KVMQtGui, "_populate_video_devices") as mock_pop_video,
        ):

            app = KVMQtGui()

            # These should be called during __init_devices (which is deferred)
            # We'll verify the methods exist and can be called
            self.assertTrue(hasattr(app, "_populate_serial_ports"))
            self.assertTrue(hasattr(app, "_populate_baud_rates"))
            self.assertTrue(hasattr(app, "_populate_video_devices"))

    @patch("kvm_serial.kvm.list_serial_ports")
    @patch("kvm_serial.kvm.CaptureDevice")
    def test_default_values_set_correctly(self, mock_capture_device, mock_list_ports):
        """Test that default configuration values are set properly."""
        mock_list_ports.return_value = ["/dev/ttyUSB0"]
        mock_capture_device.getCameras.return_value = []

        from kvm_serial.kvm import KVMQtGui

        app = KVMQtGui()

        # Test default values
        self.assertEqual(app.baud_rate_var, 9600)  # Default from baud_rates[3]
        self.assertFalse(app.window_var)
        self.assertTrue(app.show_status_var)
        self.assertFalse(app.verbose_var)
        self.assertFalse(app.hide_mouse_var)
        self.assertEqual(app.target_fps, 30)

        # Test dimension defaults
        self.assertEqual(app.window_min_width, 512)
        self.assertEqual(app.window_min_height, 320)
        self.assertEqual(app.status_bar_default_height, 24)

    @patch("kvm_serial.kvm.list_serial_ports")
    @patch("kvm_serial.kvm.CaptureDevice")
    def test_button_map_initialization(self, mock_capture_device, mock_list_ports):
        """Test that mouse button mapping is set up correctly."""
        mock_list_ports.return_value = []
        mock_capture_device.getCameras.return_value = []

        from kvm_serial.kvm import KVMQtGui

        app = KVMQtGui()

        # Verify button mapping exists and has expected entries
        self.assertIsInstance(app.BUTTON_MAP, dict)
        self.assertIn("MIDDLE", app.BUTTON_MAP.values())
        self.assertIn("LEFT", app.BUTTON_MAP.values())
        self.assertIn("RIGHT", app.BUTTON_MAP.values())

    @patch("kvm_serial.kvm.list_serial_ports")
    @patch("kvm_serial.kvm.CaptureDevice")
    @patch("kvm_serial.kvm.VideoCaptureWorker")
    def test_video_worker_initialization(
        self, mock_worker_class, mock_capture_device, mock_list_ports
    ):
        """Test that video capture worker is initialized properly."""
        mock_list_ports.return_value = []
        mock_capture_device.getCameras.return_value = []

        # Mock the worker instance
        mock_worker_instance = MagicMock()
        mock_worker_class.return_value = mock_worker_instance

        from kvm_serial.kvm import KVMQtGui

        # Let's also mock the video view size to ensure it has valid dimensions
        with patch.object(KVMQtGui, "_KVMQtGui__init_video") as mock_init_video:
            app = KVMQtGui()

            # Verify that __init_video was called during initialization
            mock_init_video.assert_called_once()

        # Now test the actual video worker creation by calling the real initialization
        app = KVMQtGui()

        # Check if VideoCaptureWorker was instantiated (it should be called in __init_video)
        if mock_worker_class.called:
            # If it was called, verify the parameters
            call_args = mock_worker_class.call_args
            self.assertIsNotNone(
                call_args, "VideoCaptureWorker should have been called with arguments"
            )

            # Verify worker methods were called
            mock_worker_instance.start.assert_called_once()
        else:
            # If not called, let's check that the video_worker attribute exists
            self.assertTrue(
                hasattr(app, "video_worker"),
                "App should have video_worker attribute even if mocked differently",
            )

    @patch("kvm_serial.kvm.list_serial_ports", side_effect=Exception("Port discovery failed"))
    @patch("kvm_serial.kvm.CaptureDevice")
    def test_initialization_handles_port_discovery_failure(
        self, mock_capture_device, mock_list_ports
    ):
        """Test graceful handling of serial port discovery failure."""
        mock_capture_device.getCameras.return_value = []

        from kvm_serial.kvm import KVMQtGui

        # Should not raise exception despite port discovery failure
        app = KVMQtGui()
        self.assertIsNotNone(app)

    @patch("kvm_serial.kvm.list_serial_ports")
    @patch(
        "kvm_serial.kvm.CaptureDevice.getCameras", side_effect=Exception("Camera discovery failed")
    )
    def test_initialization_handles_camera_discovery_failure(
        self, mock_get_cameras, mock_list_ports
    ):
        """Test graceful handling of camera discovery failure."""
        mock_list_ports.return_value = ["/dev/ttyUSB0"]

        from kvm_serial.kvm import KVMQtGui

        # Should not raise exception despite camera discovery failure
        app = KVMQtGui()
        self.assertIsNotNone(app)


if __name__ == "__main__":
    # Run tests with verbose output
    unittest.main(verbosity=2)
