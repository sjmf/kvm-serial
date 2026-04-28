"""Tests for kvm_serial/backend/video.py — Qt-based camera enumeration.

The module is a thin layer over QtMultimedia. Tests mock QCamera / QCameraInfo
at the module level so they don't require a real camera or display server.
"""

from unittest.mock import patch, MagicMock
import pytest


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
    """Patch _wait_for_loaded to a no-op so QEventLoop.exec_() isn't entered with a mock QCamera."""
    from kvm_serial.backend import video as video_mod

    with patch.object(video_mod, "_wait_for_loaded", return_value=True):
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


class TestCaptureDeviceShim:
    """CaptureDevice is retained as a back-compat namespace exposing getCameras()."""

    def test_getCameras_delegates_to_enumerate_cameras(self):
        from kvm_serial.backend import video as video_mod

        sentinel = [MagicMock()]
        with patch.object(video_mod, "enumerate_cameras", return_value=sentinel):
            assert video_mod.CaptureDevice.getCameras() is sentinel
