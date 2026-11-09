"""Tests for kvm_serial/backend/video.py — Qt-based camera enumeration.

The module is a thin layer over QtMultimedia. Tests mock QCamera / QCameraInfo
at the module level so they don't require a real camera or display server.
"""

from unittest.mock import patch, MagicMock
import pytest

from PyQt5.QtMultimedia import QCamera

# Bound before the autouse fixture below patches the module attribute.
from kvm_serial.backend.video import wait_for_loaded as real_wait_for_loaded


@pytest.fixture
def fake_info():
    """Return a MagicMock that mimics PyQt5.QtMultimedia.QCameraInfo."""
    info = MagicMock()
    info.description.return_value = "FaceTime HD Camera"
    info.deviceName.return_value = "device-uuid-1234"
    return info


@pytest.fixture
def fake_settings():
    """Return a list of MagicMock viewfinder settings (640x480, 1280x720, 1920x1080 @ 30fps)."""
    settings = []
    for w, h in [(640, 480), (1280, 720), (1920, 1080)]:
        s = MagicMock()
        size = MagicMock()
        size.width.return_value = w
        size.height.return_value = h
        s.resolution.return_value = size
        s.maximumFrameRate.return_value = 30.0
        s.minimumFrameRate.return_value = 15.0
        settings.append(s)
    return settings


@pytest.fixture
def fake_camera_factory(fake_settings):
    """Factory returning a MagicMock that mimics QCamera with given viewfinder defaults."""

    def make(default_w=1280, default_h=720):
        cam = MagicMock()
        cam.supportedViewfinderSettings.return_value = fake_settings
        current = MagicMock()
        size = MagicMock()
        size.isValid.return_value = True
        size.width.return_value = default_w
        size.height.return_value = default_h
        current.resolution.return_value = size
        cam.viewfinderSettings.return_value = current
        return cam

    return make


@pytest.fixture(autouse=True)
def skip_event_loop_wait():
    """Patch wait_for_loaded to a no-op so QEventLoop.exec_() isn't entered with a mock QCamera."""
    from kvm_serial.backend import video as video_mod

    with patch.object(video_mod, "wait_for_loaded", return_value=True):
        yield


class TestCameraProperties:
    def test_str(self):
        from kvm_serial.backend.video import CameraProperties

        props = CameraProperties(
            index=1,
            name="HD Webcam",
            unique_id="uuid",
            width=1280,
            height=720,
            fps=60,
            resolutions=[(1280, 720)],
            default_resolution=(1280, 720),
            info=None,
        )
        assert str(props) == "HD Webcam"

    def test_getitem_subscript_access(self):
        """Existing GUI code reads CameraProperties via __getitem__."""
        from kvm_serial.backend.video import CameraProperties

        props = CameraProperties(
            index=2,
            name="Cam",
            unique_id="u",
            width=640,
            height=480,
            fps=30,
            resolutions=[(640, 480)],
            default_resolution=(640, 480),
            info=None,
        )
        assert props["index"] == 2
        assert props["width"] == 640


class TestEnumerateCameras:
    def test_returns_one_camera_per_qcamerainfo(self, fake_info, fake_camera_factory):
        from kvm_serial.backend import video as video_mod

        cam = fake_camera_factory()
        with (
            patch.object(video_mod.QCameraInfo, "availableCameras", return_value=[fake_info]),
            patch.object(video_mod, "QCamera", return_value=cam),
        ):
            cameras = video_mod.enumerate_cameras()

        assert len(cameras) == 1
        c = cameras[0]
        assert c.index == 0
        assert c.name == "FaceTime HD Camera"
        assert c.unique_id == "device-uuid-1234"
        assert (1920, 1080) in c.resolutions
        assert c.fps == 30  # max of viewfinder settings

    def test_resolutions_sorted_largest_first(self, fake_info, fake_camera_factory):
        from kvm_serial.backend import video as video_mod

        cam = fake_camera_factory()
        with (
            patch.object(video_mod.QCameraInfo, "availableCameras", return_value=[fake_info]),
            patch.object(video_mod, "QCamera", return_value=cam),
        ):
            cameras = video_mod.enumerate_cameras()

        resolutions = cameras[0].resolutions
        # Largest first per the sort in _probe_camera.
        assert resolutions[0] == (1920, 1080)

    def test_no_cameras_returns_empty_list(self):
        from kvm_serial.backend import video as video_mod

        with patch.object(video_mod.QCameraInfo, "availableCameras", return_value=[]):
            assert video_mod.enumerate_cameras() == []

    def test_empty_viewfinder_settings_and_invalid_default_gives_empty_resolutions(self, fake_info):
        """When supportedViewfinderSettings() is empty and viewfinderSettings() returns
        an invalid size, resolutions must be [] — not [(0, 0)].
        """
        from kvm_serial.backend import video as video_mod

        cam = MagicMock()
        cam.supportedViewfinderSettings.return_value = []
        current = MagicMock()
        size = MagicMock()
        size.isValid.return_value = False
        size.width.return_value = 0
        current.resolution.return_value = size
        cam.viewfinderSettings.return_value = current

        with (
            patch.object(video_mod.QCameraInfo, "availableCameras", return_value=[fake_info]),
            patch.object(video_mod, "QCamera", return_value=cam),
        ):
            cameras = video_mod.enumerate_cameras()

        assert cameras[0].resolutions == []
        assert cameras[0].default_resolution == (0, 0)

    def test_empty_viewfinder_settings_with_valid_default_uses_default_as_fallback(self, fake_info):
        """When supportedViewfinderSettings() is empty but viewfinderSettings() returns a
        valid size, that size should be used as the sole entry in resolutions.
        """
        from kvm_serial.backend import video as video_mod

        cam = MagicMock()
        cam.supportedViewfinderSettings.return_value = []
        current = MagicMock()
        size = MagicMock()
        size.isValid.return_value = True
        size.width.return_value = 1280
        size.height.return_value = 720
        current.resolution.return_value = size
        cam.viewfinderSettings.return_value = current

        with (
            patch.object(video_mod.QCameraInfo, "availableCameras", return_value=[fake_info]),
            patch.object(video_mod, "QCamera", return_value=cam),
        ):
            cameras = video_mod.enumerate_cameras()

        assert cameras[0].resolutions == [(1280, 720)]
        assert cameras[0].default_resolution == (1280, 720)

    def test_failing_probe_skips_camera_without_raising(self, fake_info, fake_camera_factory):
        """A QCamera that throws should not abort enumeration of other devices."""
        from kvm_serial.backend import video as video_mod

        good = fake_camera_factory()
        bad_info = MagicMock()
        bad_info.description.return_value = "Bad Cam"
        bad_info.deviceName.return_value = "bad"

        # First QCamera() call (for bad_info) raises; second (for fake_info) succeeds.
        constructor_calls = iter([RuntimeError("camera offline"), good])

        def fake_qcamera(_info):
            v = next(constructor_calls)
            if isinstance(v, Exception):
                raise v
            return v

        with (
            patch.object(
                video_mod.QCameraInfo, "availableCameras", return_value=[bad_info, fake_info]
            ),
            patch.object(video_mod, "QCamera", side_effect=fake_qcamera),
        ):
            cameras = video_mod.enumerate_cameras()

        assert len(cameras) == 1
        assert cameras[0].name == "FaceTime HD Camera"


class TestWaitForLoaded:
    """wait_for_loaded() with QEventLoop/QTimer mocked, so no event loop is spun."""

    @pytest.fixture
    def loop_mocks(self):
        from kvm_serial.backend import video as video_mod

        with (
            patch.object(video_mod, "QEventLoop") as MockLoop,
            patch.object(video_mod, "QTimer") as MockTimer,
        ):
            yield MockLoop.return_value, MockTimer.return_value

    def _cam(self, *statuses):
        cam = MagicMock()
        cam.status.side_effect = list(statuses)
        return cam

    def test_already_loaded_returns_true_without_loop(self, loop_mocks):
        loop, _ = loop_mocks
        cam = self._cam(QCamera.LoadedStatus)
        assert real_wait_for_loaded(cam) is True
        loop.exec_.assert_not_called()

    def test_unavailable_returns_false_without_loop(self, loop_mocks):
        """A missing backend plugin leaves the camera Unavailable: don't wait out the timeout."""
        loop, _ = loop_mocks
        cam = self._cam(QCamera.UnavailableStatus, QCamera.UnavailableStatus)
        assert real_wait_for_loaded(cam) is False
        loop.exec_.assert_not_called()

    def _captured_slot(self, cam):
        (slot,), _ = cam.statusChanged.connect.call_args
        return slot

    def test_waits_until_loaded(self, loop_mocks):
        loop, timer = loop_mocks
        cam = self._cam(QCamera.LoadingStatus, QCamera.LoadingStatus, QCamera.LoadedStatus)

        def run_loop():
            slot = self._captured_slot(cam)
            slot(QCamera.LoadingStatus)
            loop.quit.assert_not_called()
            slot(QCamera.LoadedStatus)

        loop.exec_.side_effect = run_loop
        assert real_wait_for_loaded(cam, timeout_ms=1234) is True
        timer.start.assert_called_once_with(1234)
        loop.quit.assert_called_once()
        cam.statusChanged.disconnect.assert_called_once()

    @pytest.mark.parametrize(
        "status",
        [QCamera.UnavailableStatus, QCamera.UnloadingStatus, QCamera.UnloadedStatus],
    )
    def test_stops_early_when_loading_ends_without_loaded(self, loop_mocks, status):
        """Torn down or failed mid-load: quit the loop rather than block for the timeout."""
        loop, _ = loop_mocks
        cam = self._cam(QCamera.LoadingStatus, QCamera.LoadingStatus, status)
        loop.exec_.side_effect = lambda: self._captured_slot(cam)(status)
        assert real_wait_for_loaded(cam) is False
        loop.quit.assert_called_once()

    def test_timeout_returns_false(self, loop_mocks):
        loop, timer = loop_mocks
        cam = self._cam(QCamera.LoadingStatus, QCamera.LoadingStatus, QCamera.LoadingStatus)
        assert real_wait_for_loaded(cam) is False
        timer.timeout.connect.assert_called_once_with(loop.quit)


class TestCaptureDeviceShim:
    """CaptureDevice is retained as a back-compat namespace exposing getCameras()."""

    def test_getCameras_delegates_to_enumerate_cameras(self):
        from kvm_serial.backend import video as video_mod

        sentinel = [MagicMock()]
        with patch.object(video_mod, "enumerate_cameras", return_value=sentinel):
            assert video_mod.CaptureDevice.getCameras() is sentinel
