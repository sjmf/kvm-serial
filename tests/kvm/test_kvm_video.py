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


class TestPickViewfinderSettingsPlatformGating(KVMTestBase):
    """The unsupported-format set is platform-gated. Each entry has a confirmed
    failure mode on real hardware; these tests pin the gating so a future
    refactor can't silently regress one of the known-broken combinations.
    """

    def _make_setting(self, w, h, fmt):
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
        result = app._pick_viewfinder_settings(w, h)
        if result is None:
            return None
        if result.setPixelFormat.called:
            return result.setPixelFormat.call_args[0][0]
        return None

    def test_macos_rejects_yuyv_when_alternative_exists(self):
        """Regression: macOS AVFoundation cannot render YUYV (Razer capture card,
        confirmed black screen). When a non-YUYV format is also available it must
        be chosen instead, even if it's not in the preferred list.
        """
        from PyQt5.QtMultimedia import QVideoFrame

        with patch("kvm_serial.kvm.sys.platform", "darwin"):
            app = self._make_app_with_supported(
                [
                    self._make_setting(1920, 1080, QVideoFrame.Format_YUYV),
                    self._make_setting(1920, 1080, QVideoFrame.Format_Jpeg),
                ]
            )
            # Jpeg is not in the macOS reject set, YUYV is — Jpeg wins by elimination.
            self.assertEqual(self._result_fmt(app, 1920, 1080), QVideoFrame.Format_Jpeg)

    def test_macos_rejects_uyvy_when_alternative_exists(self):
        """macOS AVFoundation cannot render UYVY ("Failed to start viewfinder")."""
        from PyQt5.QtMultimedia import QVideoFrame

        with patch("kvm_serial.kvm.sys.platform", "darwin"):
            app = self._make_app_with_supported(
                [
                    self._make_setting(1920, 1080, QVideoFrame.Format_UYVY),
                    self._make_setting(1920, 1080, QVideoFrame.Format_NV12),
                ]
            )
            self.assertEqual(self._result_fmt(app, 1920, 1080), QVideoFrame.Format_NV12)

    def test_windows_picks_yuyv_over_jpeg_at_1080p(self):
        """Regression: at 1920x1080 a typical USB capture card on Windows DirectShow
        offers only {MJPG (Format_Jpeg), YUY2 (Format_YUYV)}. YUYV renders correctly
        on DirectShow; Jpeg is a silent black screen. The prior unified blocklist
        rejected YUYV alongside UYVY, forcing fallback to Jpeg → black screen on
        startup. Verify YUYV is now chosen.
        """
        from PyQt5.QtMultimedia import QVideoFrame

        with patch("kvm_serial.kvm.sys.platform", "win32"):
            app = self._make_app_with_supported(
                [
                    self._make_setting(1920, 1080, QVideoFrame.Format_Jpeg),
                    self._make_setting(1920, 1080, QVideoFrame.Format_YUYV),
                ]
            )
            self.assertEqual(self._result_fmt(app, 1920, 1080), QVideoFrame.Format_YUYV)

    def test_windows_does_not_reject_yuyv_alone(self):
        """On Windows YUYV is explicitly *not* in the unsupported set; if it's the
        only format offered, it must be picked (and the camera renders).
        """
        from PyQt5.QtMultimedia import QVideoFrame

        with patch("kvm_serial.kvm.sys.platform", "win32"):
            app = self._make_app_with_supported(
                [self._make_setting(1920, 1080, QVideoFrame.Format_YUYV)]
            )
            self.assertEqual(self._result_fmt(app, 1920, 1080), QVideoFrame.Format_YUYV)

    def test_linux_rejects_nothing(self):
        """Linux V4L2 has no observed failure modes — the rejection set is empty,
        so even YUYV-only or Jpeg-only must round-trip without falling through to
        the 'all unsupported' warning branch.
        """
        from PyQt5.QtMultimedia import QVideoFrame

        # Per docs/TESTING.md, create_kvm_app exhausts shared Qt mock side_effects
        # if called repeatedly inside a single test. Create the app once and rebind
        # supportedViewfinderSettings per subtest.
        app = self.create_kvm_app()
        app.qcamera = MagicMock()

        for fmt in (QVideoFrame.Format_YUYV, QVideoFrame.Format_UYVY, QVideoFrame.Format_Jpeg):
            with self.subTest(fmt=fmt), patch("kvm_serial.kvm.sys.platform", "linux"):
                app.qcamera.supportedViewfinderSettings.return_value = [
                    self._make_setting(1920, 1080, fmt)
                ]
                self.assertEqual(self._result_fmt(app, 1920, 1080), fmt)

    def test_preferred_format_wins_regardless_of_platform(self):
        """ARGB32/BGRA32/NV12 are picked first on any platform, before the reject
        set is even consulted. Pin this so a future refactor that moves the
        rejection check before the preferred loop doesn't silently regress macOS
        cameras that offer NV12 alongside YUYV.
        """
        from PyQt5.QtMultimedia import QVideoFrame

        app = self.create_kvm_app()
        app.qcamera = MagicMock()
        app.qcamera.supportedViewfinderSettings.return_value = [
            self._make_setting(1920, 1080, QVideoFrame.Format_YUYV),
            self._make_setting(1920, 1080, QVideoFrame.Format_NV12),
        ]

        for platform in ("darwin", "win32", "linux"):
            with self.subTest(platform=platform), patch("kvm_serial.kvm.sys.platform", platform):
                self.assertEqual(self._result_fmt(app, 1920, 1080), QVideoFrame.Format_NV12)

    def test_only_unsupported_available_falls_through_with_warning(self):
        """On macOS with a camera that only offers YUYV, the function must still
        return a settings object (so the camera opens and the warning logs fire)
        rather than returning None — black-with-explanation beats silent failure.
        """
        from PyQt5.QtMultimedia import QVideoFrame

        with (
            patch("kvm_serial.kvm.sys.platform", "darwin"),
            patch("kvm_serial.kvm.logging.warning") as mock_warning,
        ):
            app = self._make_app_with_supported(
                [self._make_setting(1920, 1080, QVideoFrame.Format_YUYV)]
            )
            self.assertEqual(self._result_fmt(app, 1920, 1080), QVideoFrame.Format_YUYV)
            mock_warning.assert_called_once()
            self.assertIn("unrenderable", mock_warning.call_args[0][0])
