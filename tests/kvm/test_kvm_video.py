#!/usr/bin/env python
"""Tests for the Qt-based video pipeline in kvm_serial.kvm.

The previous file tested a custom QThread frame-capture worker and a per-frame
QTimer; that architecture is gone. Frames are now delivered by QtMultimedia
into QGraphicsVideoItem, so most of the surface area moves into Qt and
tests collapse to verifying the small Python glue layer.
"""

import unittest
from unittest.mock import patch, MagicMock

from test_kvm_base import KVMTestBase


class TestKVMVideoPipeline(KVMTestBase):
    def test_video_item_attribute_exists(self):
        """KVMQtGui owns a QGraphicsVideoItem (the QtMultimedia video sink)."""
        app = self.create_kvm_app()
        self.assertTrue(hasattr(app, "video_item"))

    def test_qcamera_initially_none(self):
        """No QCamera is constructed until enumeration completes and a device is selected."""
        app = self.create_kvm_app()
        self.assertIsNone(app.qcamera)

    def test_set_camera_assigns_viewfinder_and_starts(self):
        """_set_camera should construct a QCamera, attach the video item, and start streaming."""
        app = self.create_kvm_app()

        info = MagicMock()
        camera = MagicMock(
            name="Camera0",
            unique_id="uid",
            width=1280,
            height=720,
            fps=30,
            resolutions=[(1280, 720)],
            default_resolution=(1280, 720),
            info=info,
        )
        camera.name = "Camera0"

        with patch("kvm_serial.kvm.QCamera") as MockQCamera:
            mock_cam = MockQCamera.return_value
            app._set_camera(camera)
            MockQCamera.assert_called_once_with(info)
            mock_cam.setViewfinder.assert_called_once_with(app.video_item)
            mock_cam.start.assert_called_once()

    def test_set_camera_stops_previous_instance(self):
        """Switching cameras must tear down the previous QCamera before opening the next."""
        app = self.create_kvm_app()

        previous = MagicMock()
        app.qcamera = previous

        info = MagicMock()
        camera = MagicMock(
            unique_id="uid",
            width=640,
            height=480,
            default_resolution=(640, 480),
            info=info,
        )
        camera.name = "Cam"

        with patch("kvm_serial.kvm.QCamera"):
            app._set_camera(camera)
            previous.stop.assert_called_once()
            previous.unload.assert_called_once()

    def test_set_camera_skips_when_info_missing(self):
        """A CameraProperties with no QCameraInfo cannot be opened — skip silently."""
        app = self.create_kvm_app()
        camera = MagicMock(info=None)
        camera.name = "no-info"

        with patch("kvm_serial.kvm.QCamera") as MockQCamera:
            app._set_camera(camera)
            MockQCamera.assert_not_called()

    def test_camera_resolution_falls_back_to_window_defaults(self):
        """With no camera selected and no native size, default resolution returns the window defaults."""
        app = self.create_kvm_app()
        # video_item is mocked; force nativeSize() invalid so fallbacks engage.
        invalid_size = MagicMock()
        invalid_size.isValid.return_value = False
        invalid_size.width.return_value = 0
        invalid_size.height.return_value = 0
        app.video_item.nativeSize.return_value = invalid_size
        app.video_var = -1

        w, h = app._camera_resolution()
        self.assertEqual((w, h), (app.window_default_width, app.window_default_height))

    def test_camera_resolution_uses_native_size_when_available(self):
        app = self.create_kvm_app()
        size = MagicMock()
        size.isValid.return_value = True
        size.width.return_value = 1920
        size.height.return_value = 1080
        app.video_item.nativeSize.return_value = size

        self.assertEqual(app._camera_resolution(), (1920, 1080))


if __name__ == "__main__":
    unittest.main()
