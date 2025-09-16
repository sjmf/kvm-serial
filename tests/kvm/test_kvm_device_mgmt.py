#!/usr/bin/env python
"""
Test suite for KVM device management functionality.
Uses KVMTestBase for common mocking infrastructure.
"""

import unittest
from unittest.mock import patch, MagicMock
from serial import SerialException

# Import the base test class
from test_kvm_base import KVMTestBase, KVMTestMixins


class TestKVMDeviceManagement(
    KVMTestBase, KVMTestMixins.SerialTestMixin, KVMTestMixins.VideoTestMixin
):
    """Test class for KVM device management functionality."""

    def test_populate_serial_ports_success(self):
        """Test successful serial port discovery and population."""
        test_ports = self.create_mock_serial_ports()

        app = self.create_kvm_app()

        with (
            patch("kvm_serial.kvm.list_serial_ports", return_value=test_ports),
            self.patch_kvm_method(app, "_populate_serial_port_menu"),
        ):
            app._populate_serial_ports()

            self.assertEqual(app.serial_ports, test_ports)
            self.assertEqual(app.serial_port_var, test_ports[-1])

    def test_populate_serial_ports_empty_list(self):
        """Test handling when no serial ports are found."""
        app = self.create_kvm_app()

        with (
            patch("kvm_serial.kvm.list_serial_ports", return_value=[]),
            self.patch_kvm_method(app, "_populate_serial_port_menu"),
            patch("kvm_serial.kvm.QMessageBox.warning") as mock_warning,
        ):
            app._populate_serial_ports()

            self.assert_error_handling(mock_warning)
            self.assertEqual(app.serial_ports, [])
            self.assertEqual(app.serial_port_var, "None found")

    def test_populate_serial_ports_exception_handling(self):
        """Test handling of exceptions during serial port discovery."""
        app = self.create_kvm_app()

        with (
            patch(
                "kvm_serial.kvm.list_serial_ports", side_effect=Exception("Port discovery failed")
            ),
            self.patch_kvm_method(app, "_populate_serial_port_menu"),
            patch("kvm_serial.kvm.QMessageBox.critical") as mock_critical,
        ):
            app._populate_serial_ports()

            self.assert_error_handling(mock_critical)
            self.assertEqual(app.serial_ports, [])
            self.assertEqual(app.serial_port_var, "Error")

    def test_serial_port_selection(self):
        """Test serial port selection logic."""
        app = self.create_kvm_app()
        test_ports = self.create_mock_serial_ports()
        app.serial_ports = test_ports

        # Mock the menu
        mock_action = MagicMock()
        mock_action.text.return_value = test_ports[1]
        mock_menu = MagicMock()
        mock_menu.actions.return_value = [mock_action]
        app.serial_port_menu = mock_menu

        with self.patch_kvm_method(app, "_KVMQtGui__init_serial") as mock_init_serial:
            app._on_serial_port_selected(test_ports[1])

            self.assertEqual(app.serial_port_var, test_ports[1])
            mock_init_serial.assert_called_once()

    def test_baud_rate_selection(self):
        """Test baud rate selection logic."""
        app = self.create_kvm_app()
        baud_rates = self.get_default_baud_rates()
        test_rate = baud_rates[-1]  # 115200

        # Mock the baud rate menu
        mock_action = MagicMock()
        mock_action.text.return_value = str(test_rate)
        mock_menu = MagicMock()
        mock_menu.actions.return_value = [mock_action]
        app.baud_rate_menu = mock_menu

        with self.patch_kvm_method(app, "_KVMQtGui__init_serial") as mock_init_serial:
            app._on_baud_rate_selected(test_rate)

            self.assertEqual(app.baud_rate_var, test_rate)
            mock_init_serial.assert_called_once()

    def test_populate_video_devices_success(self):
        """Test successful video device discovery and population."""
        test_cameras = self.create_mock_cameras(2)
        app = self.create_kvm_app()

        with (
            patch("kvm_serial.kvm.CaptureDevice.getCameras", return_value=test_cameras),
            self.patch_kvm_method(app, "_populate_video_device_menu"),
        ):
            app._populate_video_devices()

            self.assertEqual(app.video_devices, test_cameras)
            self.assertEqual(app.video_device_var, str(test_cameras[0]))
            self.assertEqual(app.video_var, 0)

    def test_populate_video_devices_empty_list(self):
        """Test handling when no video devices are found."""
        app = self.create_kvm_app()

        with (
            patch("kvm_serial.kvm.CaptureDevice.getCameras", return_value=[]),
            self.patch_kvm_method(app, "_populate_video_device_menu"),
            patch("kvm_serial.kvm.QMessageBox.warning") as mock_warning,
        ):
            app._populate_video_devices()

            self.assert_error_handling(mock_warning)
            self.assertEqual(app.video_devices, [])
            self.assertEqual(app.video_device_var, "None found")

    def test_populate_video_devices_exception_handling(self):
        """Test handling of exceptions during video device discovery."""
        app = self.create_kvm_app()

        with (
            patch(
                "kvm_serial.kvm.CaptureDevice.getCameras",
                side_effect=Exception("Camera discovery failed"),
            ),
            self.patch_kvm_method(app, "_populate_video_device_menu"),
            patch("kvm_serial.kvm.QMessageBox.critical") as mock_critical,
        ):
            app._populate_video_devices()

            self.assert_error_handling(mock_critical)
            self.assertEqual(app.video_devices, [])
            self.assertEqual(app.video_device_var, "Error")

    def test_video_device_selection(self):
        """Test video device selection logic."""
        app = self.create_kvm_app()
        test_cameras = self.create_mock_cameras(2)
        app.video_devices = test_cameras

        # Mock the menu
        mock_action = MagicMock()
        mock_action.text.return_value = str(test_cameras[1])
        mock_menu = MagicMock()
        mock_menu.actions.return_value = [mock_action]
        app.video_device_menu = mock_menu

        # Mock video worker
        app.video_worker = MagicMock()

        app._on_video_device_selected(1, str(test_cameras[1]))

        self.assert_video_device_selection(app, 1, str(test_cameras[1]))
        app.video_worker.set_camera_index.assert_called_once_with(1)

    def test_serial_initialization_success(self):
        """Test successful serial port initialization."""
        app = self.create_kvm_app()
        app.serial_port_var = "/dev/ttyUSB0"
        app.baud_rate_var = 9600

        mock_serial_instance = self.create_mock_serial_instance()
        mock_qtop_instance = MagicMock()
        mock_mouseop_instance = MagicMock()

        with (
            patch("kvm_serial.kvm.Serial", return_value=mock_serial_instance) as mock_serial_class,
            patch("kvm_serial.kvm.QtOp", return_value=mock_qtop_instance) as mock_qtop,
            patch("kvm_serial.kvm.MouseOp", return_value=mock_mouseop_instance) as mock_mouseop,
        ):
            app._KVMQtGui__init_serial()

            mock_serial_class.assert_called_once_with("/dev/ttyUSB0", 9600)
            self.assertEqual(app.serial_port, mock_serial_instance)
            mock_qtop.assert_called_once_with(mock_serial_instance)
            mock_mouseop.assert_called_once_with(mock_serial_instance)
            self.assertEqual(app.keyboard_op, mock_qtop_instance)
            self.assertEqual(app.mouse_op, mock_mouseop_instance)

    def test_serial_initialization_failure(self):
        """Test handling of serial port initialization failure."""
        app = self.create_kvm_app()
        app.serial_port_var = "/dev/ttyUSB0"
        app.baud_rate_var = 9600

        with (
            patch("kvm_serial.kvm.Serial", side_effect=SerialException("Port not available")),
            patch("kvm_serial.kvm.QMessageBox.critical") as mock_critical,
        ):
            app._KVMQtGui__init_serial()

            self.assert_error_handling(mock_critical)
            self.assertIsNone(app.serial_port)
            self.assertIsNone(app.keyboard_op)
            self.assertIsNone(app.mouse_op)

    def test_serial_port_closing(self):
        """Test proper serial port closing."""
        app = self.create_kvm_app()
        mock_serial_port = self.create_mock_serial_instance()
        app.serial_port = mock_serial_port

        app._close_serial_port()

        mock_serial_port.close.assert_called_once()
        self.assertIsNone(app.serial_port)

    def test_serial_port_closing_with_exception(self):
        """Test handling exceptions during serial port closing."""
        app = self.create_kvm_app()
        mock_serial_port = self.create_mock_serial_instance()
        mock_serial_port.close.side_effect = Exception("Close failed")
        app.serial_port = mock_serial_port

        app._close_serial_port()

        mock_serial_port.close.assert_called_once()
        self.assertIsNone(app.serial_port)

    def test_invalid_port_handling(self):
        """Test handling of invalid serial port configurations."""
        app = self.create_kvm_app()

        invalid_ports = ["Loading serial...", "None found", "Error", None, ""]

        for invalid_port in invalid_ports:
            with self.subTest(port=invalid_port):
                app.serial_port_var = invalid_port
                app.baud_rate_var = 9600

                app._KVMQtGui__init_serial()

                self.assertIsNone(app.serial_port)
                self.assertIsNone(app.keyboard_op)
                self.assertIsNone(app.mouse_op)

    def test_invalid_baud_rate_handling(self):
        """Test handling of invalid baud rate configurations."""
        app = self.create_kvm_app()
        app.serial_port_var = "/dev/ttyUSB0"

        invalid_rates = [-1, 0, 999999, None]

        for invalid_rate in invalid_rates:
            with self.subTest(rate=invalid_rate):
                app.baud_rate_var = invalid_rate

                app._KVMQtGui__init_serial()

                self.assertIsNone(app.serial_port)
                self.assertIsNone(app.keyboard_op)
                self.assertIsNone(app.mouse_op)


if __name__ == "__main__":
    unittest.main(verbosity=2)
