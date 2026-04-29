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


class TestPickViewfinderSettings(KVMTestBase):
    """Unit tests for _pick_viewfinder_settings."""

    def _make_setting(self, w, h, fmt):
        """Return a mock QCameraViewfinderSettings entry for a given resolution and pixel format."""
        s = MagicMock()
        size = MagicMock()
        size.width.return_value = w
        size.height.return_value = h
        s.resolution.return_value = size
        s.pixelFormat.return_value = fmt
        return s

    def _make_app_with_supported(self, supported_settings):
        app = self.create_kvm_app()
        app.qcamera = MagicMock()
        app.qcamera.supportedViewfinderSettings.return_value = supported_settings
        return app

    def _result_fmt(self, app, w, h):
        """Call _pick_viewfinder_settings and return the pixel format it requested.

        QCameraViewfinderSettings is mocked by KVMTestBase, so we can't read back
        pixelFormat() — instead we inspect what setPixelFormat() was called with.
        """
        result = app._pick_viewfinder_settings(w, h)
        if result is None:
            return None
        if result.setPixelFormat.called:
            return result.setPixelFormat.call_args[0][0]
        return None

    def test_prefers_argb32_over_uyvy(self):
        """ARGB32 must be chosen over UYVY when both are available."""
        from PyQt5.QtMultimedia import QVideoFrame

        app = self._make_app_with_supported(
            [
                self._make_setting(1920, 1080, QVideoFrame.Format_UYVY),
                self._make_setting(1920, 1080, QVideoFrame.Format_ARGB32),
            ]
        )
        self.assertEqual(self._result_fmt(app, 1920, 1080), QVideoFrame.Format_ARGB32)

    def test_prefers_bgra32_over_yuyv(self):
        """BGRA32 must be chosen over YUYV when both are available."""
        from PyQt5.QtMultimedia import QVideoFrame

        app = self._make_app_with_supported(
            [
                self._make_setting(1920, 1080, QVideoFrame.Format_YUYV),
                self._make_setting(1920, 1080, QVideoFrame.Format_BGRA32),
            ]
        )
        self.assertEqual(self._result_fmt(app, 1920, 1080), QVideoFrame.Format_BGRA32)

    def test_argb32_preferred_over_bgra32(self):
        """ARGB32 has higher priority than BGRA32."""
        from PyQt5.QtMultimedia import QVideoFrame

        app = self._make_app_with_supported(
            [
                self._make_setting(1920, 1080, QVideoFrame.Format_BGRA32),
                self._make_setting(1920, 1080, QVideoFrame.Format_ARGB32),
            ]
        )
        self.assertEqual(self._result_fmt(app, 1920, 1080), QVideoFrame.Format_ARGB32)

    def test_falls_back_to_uyvy_when_only_option(self):
        """When UYVY is the only format at 1920x1080, it must still be chosen."""
        from PyQt5.QtMultimedia import QVideoFrame

        app = self._make_app_with_supported(
            [
                self._make_setting(1920, 1080, QVideoFrame.Format_UYVY),
            ]
        )
        self.assertEqual(self._result_fmt(app, 1920, 1080), QVideoFrame.Format_UYVY)

    def test_returns_none_when_no_match_for_resolution(self):
        """When no supported settings match the requested resolution, None is returned."""
        from PyQt5.QtMultimedia import QVideoFrame

        app = self._make_app_with_supported(
            [
                self._make_setting(1280, 720, QVideoFrame.Format_NV12),
            ]
        )
        self.assertIsNone(app._pick_viewfinder_settings(1920, 1080))

    def test_returns_none_when_supported_list_is_empty(self):
        app = self._make_app_with_supported([])
        self.assertIsNone(app._pick_viewfinder_settings(1920, 1080))

    def test_result_has_correct_resolution(self):
        """The returned settings object must carry the requested resolution."""
        from PyQt5.QtMultimedia import QVideoFrame

        app = self._make_app_with_supported(
            [
                self._make_setting(1920, 1080, QVideoFrame.Format_ARGB32),
            ]
        )
        with patch("kvm_serial.kvm.QCameraViewfinderSettings") as MockSettings:
            mock_s = MockSettings.return_value
            app._pick_viewfinder_settings(1920, 1080)
            mock_s.setResolution.assert_called_once_with(1920, 1080)
            mock_s.setPixelFormat.assert_called_once_with(QVideoFrame.Format_ARGB32)
