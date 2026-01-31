import sys
import cv2
import pytest
import numpy as np
from unittest.mock import patch, MagicMock, call


@pytest.fixture
def sys_modules_patch():
    return {
        "pynput": MagicMock(),
        "numpy": MagicMock(),
        "cv2": MagicMock(),
        "serial": MagicMock(),
    }


def _make_frame(width=1920, height=1080, channels=3, dtype="uint8"):
    """Create a real numpy array simulating a camera frame."""
    return np.zeros((height, width, channels), dtype=dtype)


class TestCameraProperties:
    def test_camera_properties_initialization(self, sys_modules_patch):
        """Test basic initialization of CameraProperties"""

        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.video import CameraProperties

            props = CameraProperties(
                index=0, width=1920, height=1080, fps=30, format=0
            )  # CV_8U format

            assert props.index == 0
            assert props.width == 1920
            assert props.height == 1080
            assert props.fps == 30
            assert props.format == 0

    def test_camera_properties_str(self, sys_modules_patch):

        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.video import CameraProperties

            """Test string representation of CameraProperties"""
            props = CameraProperties(
                index=1, width=1280, height=720, fps=60, format=0
            )  # CV_8U format

            expected = "1: 1280x720@60fps (CV_8U/0)"
            assert str(props) == expected


class TestCaptureDevice:
    def test_capture_device_initialization(self, sys_modules_patch):
        """Test basic initialization of CaptureDevice"""

        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.video import CaptureDevice

            device = CaptureDevice()
            assert device.cam is None
            assert device.fullscreen is False
            assert device.running is False
            assert device.thread is None

    def test_capture_device_thread_requirement(self, sys_modules_patch):
        """Test that non-threaded CaptureDevice raises exception on run"""

        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.video import CaptureDevice, CaptureDeviceException

            device = CaptureDevice(threaded=False)
            with pytest.raises(CaptureDeviceException):
                device.run()

    @patch("cv2.VideoCapture")
    def test_capture_device_with_camera(self, mock_video_capture, sys_modules_patch):
        """Test CaptureDevice initialization with a camera"""

        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.video import CaptureDevice

            mock_cam = MagicMock()
            device = CaptureDevice(cam=mock_cam, threaded=True)
            assert device.cam == mock_cam
            assert device.thread is not None

    def test_capture_device_get_frame(self, sys_modules_patch):
        """Test retrieval of a single frame"""
        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.video import CaptureDevice, CaptureDeviceException

            mock_cam = MagicMock()
            mock_cam.read.side_effect = [(None, "correct")]
            device = CaptureDevice(cam=None, threaded=False)

            with pytest.raises(CaptureDeviceException):
                device.getFrame()

            device.cam = mock_cam
            assert device.getFrame() == "correct"


class TestConfigureDshowCamera:
    """Tests for _configure_dshow_camera helper (issue #19)"""

    def test_sets_properties_in_correct_order(self):
        """Dimensions must be set before FOURCC (see cap_dshow.cpp L3472-L3475)"""
        from kvm_serial.backend.video import _configure_dshow_camera

        mock_cam = MagicMock()
        mock_cam.set.return_value = True
        _configure_dshow_camera(mock_cam, width=1920, height=1080)

        calls = mock_cam.set.call_args_list
        # Width and height set before FOURCC
        assert len(calls) == 3
        assert calls[0] == call(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        assert calls[1] == call(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        # Third call is FOURCC
        assert calls[2][0][0] == cv2.CAP_PROP_FOURCC

    def test_returns_true_when_mjpg_accepted(self):
        from kvm_serial.backend.video import _configure_dshow_camera

        mock_cam = MagicMock()
        mock_cam.set.return_value = True
        assert _configure_dshow_camera(mock_cam) is True

    def test_returns_false_when_mjpg_rejected(self):
        """Devices that don't support MJPG should still work with default codec"""
        from kvm_serial.backend.video import _configure_dshow_camera

        mock_cam = MagicMock()
        # Width/height succeed, FOURCC fails
        mock_cam.set.side_effect = [True, True, False]
        assert _configure_dshow_camera(mock_cam) is False

    def test_custom_resolution(self):
        from kvm_serial.backend.video import _configure_dshow_camera

        mock_cam = MagicMock()
        mock_cam.set.return_value = True
        _configure_dshow_camera(mock_cam, width=1280, height=720)

        calls = mock_cam.set.call_args_list
        assert calls[0] == call(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        assert calls[1] == call(cv2.CAP_PROP_FRAME_HEIGHT, 720)


class TestFormatFromFrame:
    """Tests for CameraProperties.format_from_frame"""

    def test_uint8_3ch_gives_cv8uc3(self):
        """Standard BGR frame: uint8 + 3 channels = CV_8UC3 (16)"""
        from kvm_serial.backend.video import CameraProperties

        frame = _make_frame(640, 480, channels=3, dtype="uint8")
        assert CameraProperties.format_from_frame(frame) == 16

    def test_uint8_1ch_gives_cv8uc1(self):
        """Grayscale frame: uint8 + 1 channel = CV_8UC1 (0)"""
        from kvm_serial.backend.video import CameraProperties

        frame = np.zeros((480, 640), dtype="uint8")
        assert CameraProperties.format_from_frame(frame) == 0

    def test_float32_3ch_gives_cv32fc3(self):
        """Float frame: float32 + 3 channels = CV_32FC3 (21)"""
        from kvm_serial.backend.video import CameraProperties

        frame = _make_frame(640, 480, channels=3, dtype="float32")
        assert CameraProperties.format_from_frame(frame) == 21

    def test_unrecognised_dtype_returns_minus_one(self):
        from kvm_serial.backend.video import CameraProperties

        frame = np.zeros((480, 640, 3), dtype="complex128")
        assert CameraProperties.format_from_frame(frame) == -1

    def test_uint8_4ch_gives_cv8uc4(self):
        """RGBA frame: uint8 + 4 channels = CV_8UC4 (24)"""
        from kvm_serial.backend.video import CameraProperties

        frame = _make_frame(640, 480, channels=4, dtype="uint8")
        assert CameraProperties.format_from_frame(frame) == 24


class TestMeasureFramerate:
    """Tests for _measure_framerate helper"""

    def test_measures_fps_from_frame_timing(self):
        from kvm_serial.backend.video import _measure_framerate

        mock_cam = MagicMock()
        # Simulate 5 frames in 0.5s = 10 FPS
        with patch("kvm_serial.backend.video.time") as mock_time:
            mock_time.perf_counter.side_effect = [0.0, 0.5]
            fps = _measure_framerate(mock_cam)

        assert fps == 10
        assert mock_cam.read.call_count == 5

    def test_returns_zero_on_instant_elapsed(self):
        from kvm_serial.backend.video import _measure_framerate

        mock_cam = MagicMock()
        with patch("kvm_serial.backend.video.time") as mock_time:
            mock_time.perf_counter.side_effect = [0.0, 0.0]
            fps = _measure_framerate(mock_cam)

        assert fps == 0


class TestGetCamerasWindows:
    """Tests for getCameras() on Windows with DirectShow configuration"""

    @patch("kvm_serial.backend.video.sys")
    @patch("kvm_serial.backend.video._configure_dshow_camera")
    @patch("kvm_serial.backend.video.cv2")
    def test_calls_configure_dshow_on_windows(self, mock_cv2, mock_configure, mock_sys):
        """DirectShow configuration should be called on Windows"""
        from kvm_serial.backend.video import CaptureDevice

        mock_sys.platform = "win32"
        mock_cam = MagicMock()
        mock_cam.isOpened.return_value = True
        frame = _make_frame(1920, 1080)
        mock_cam.read.return_value = (True, frame)
        mock_cam.get.return_value = 30
        mock_cv2.VideoCapture.return_value = mock_cam

        cameras = CaptureDevice.getCameras()

        mock_configure.assert_called()
        assert len(cameras) > 0
        assert cameras[0].width == 1920
        assert cameras[0].height == 1080

    @patch("kvm_serial.backend.video.sys")
    @patch("kvm_serial.backend.video._configure_dshow_camera")
    @patch("kvm_serial.backend.video.cv2")
    def test_skips_configure_dshow_on_macos(self, mock_cv2, mock_configure, mock_sys):
        """DirectShow configuration should NOT be called on macOS"""
        from kvm_serial.backend.video import CaptureDevice

        mock_sys.platform = "darwin"
        mock_cam = MagicMock()
        mock_cam.isOpened.return_value = True
        frame = _make_frame(1280, 720)
        mock_cam.read.return_value = (True, frame)
        mock_cam.get.return_value = 29
        mock_cv2.VideoCapture.return_value = mock_cam

        cameras = CaptureDevice.getCameras()

        mock_configure.assert_not_called()
        assert cameras[0].width == 1280
        assert cameras[0].height == 720

    @patch("kvm_serial.backend.video.sys")
    @patch("kvm_serial.backend.video._configure_dshow_camera")
    @patch("kvm_serial.backend.video.cv2")
    def test_skips_configure_dshow_on_linux(self, mock_cv2, mock_configure, mock_sys):
        """DirectShow configuration should NOT be called on Linux"""
        from kvm_serial.backend.video import CaptureDevice

        mock_sys.platform = "linux"
        mock_cam = MagicMock()
        mock_cam.isOpened.return_value = True
        frame = _make_frame(1280, 720)
        mock_cam.read.return_value = (True, frame)
        mock_cam.get.return_value = 30
        mock_cv2.VideoCapture.return_value = mock_cam

        cameras = CaptureDevice.getCameras()

        mock_configure.assert_not_called()

    @patch("kvm_serial.backend.video._measure_framerate", return_value=30)
    @patch("kvm_serial.backend.video.sys")
    @patch("kvm_serial.backend.video.cv2")
    def test_measures_fps_when_reported_as_zero(self, mock_cv2, mock_sys, mock_measure):
        """When CAP_PROP_FPS returns 0, FPS should be measured from frame timing"""
        from kvm_serial.backend.video import CaptureDevice

        mock_sys.platform = "linux"
        mock_cam = MagicMock()
        mock_cam.isOpened.return_value = True
        frame = _make_frame(1280, 720)
        mock_cam.read.return_value = (True, frame)
        mock_cam.get.return_value = 0  # FPS not reported
        mock_cv2.VideoCapture.return_value = mock_cam

        cameras = CaptureDevice.getCameras()

        mock_measure.assert_called()
        assert cameras[0].fps == 30

    @patch("kvm_serial.backend.video.sys")
    @patch("kvm_serial.backend.video.cv2")
    def test_derives_dimensions_from_frame_shape(self, mock_cv2, mock_sys):
        """Dimensions should come from frame.shape, not cam.get()"""
        from kvm_serial.backend.video import CaptureDevice

        mock_sys.platform = "linux"
        mock_cam = MagicMock()
        mock_cam.isOpened.return_value = True
        # cam.get() would return 640x480, but frame is 1920x1080
        frame = _make_frame(1920, 1080)
        mock_cam.read.return_value = (True, frame)
        mock_cam.get.return_value = 30
        mock_cv2.VideoCapture.return_value = mock_cam

        cameras = CaptureDevice.getCameras()

        assert cameras[0].width == 1920
        assert cameras[0].height == 1080

    @patch("kvm_serial.backend.video.sys")
    @patch("kvm_serial.backend.video.cv2")
    def test_derives_format_from_frame_dtype(self, mock_cv2, mock_sys):
        """Format should be derived from frame dtype, not CAP_PROP_FORMAT"""
        from kvm_serial.backend.video import CaptureDevice

        mock_sys.platform = "linux"
        mock_cam = MagicMock()
        mock_cam.isOpened.return_value = True
        frame = _make_frame(1280, 720, channels=3, dtype="uint8")
        mock_cam.read.return_value = (True, frame)
        mock_cam.get.return_value = -1  # CAP_PROP_FORMAT returns -1 on DirectShow
        mock_cv2.VideoCapture.return_value = mock_cam

        cameras = CaptureDevice.getCameras()

        # uint8 + 3ch = CV_8UC3 = 16, not -1
        assert cameras[0].format == 16


class TestSetCameraWindows:
    """Tests for setCamera() with DirectShow configuration"""

    @patch("kvm_serial.backend.video.sys")
    @patch("kvm_serial.backend.video._configure_dshow_camera")
    @patch("kvm_serial.backend.video.cv2")
    def test_calls_configure_dshow_on_windows(self, mock_cv2, mock_configure, mock_sys):
        from kvm_serial.backend.video import CaptureDevice

        mock_sys.platform = "win32"
        mock_cam = MagicMock()
        mock_cam.isOpened.return_value = True
        frame = _make_frame(1920, 1080)
        mock_cam.read.return_value = (True, frame)
        mock_cv2.VideoCapture.return_value = mock_cam

        device = CaptureDevice()
        device.setCamera(0)

        mock_configure.assert_called_once_with(mock_cam)

    @patch("kvm_serial.backend.video.sys")
    @patch("kvm_serial.backend.video._configure_dshow_camera")
    @patch("kvm_serial.backend.video.cv2")
    def test_skips_configure_dshow_on_macos(self, mock_cv2, mock_configure, mock_sys):
        from kvm_serial.backend.video import CaptureDevice

        mock_sys.platform = "darwin"
        mock_cam = MagicMock()
        mock_cam.isOpened.return_value = True
        frame = _make_frame(1280, 720)
        mock_cam.read.return_value = (True, frame)
        mock_cv2.VideoCapture.return_value = mock_cam

        device = CaptureDevice()
        device.setCamera(0)

        mock_configure.assert_not_called()

    @patch("kvm_serial.backend.video.sys")
    @patch("kvm_serial.backend.video.cv2")
    def test_stores_actual_dimensions_from_frame(self, mock_cv2, mock_sys):
        """camera_width/camera_height should reflect actual frame, not cam.get()"""
        from kvm_serial.backend.video import CaptureDevice

        mock_sys.platform = "linux"
        mock_cam = MagicMock()
        mock_cam.isOpened.return_value = True
        frame = _make_frame(1920, 1080)
        mock_cam.read.return_value = (True, frame)
        mock_cv2.VideoCapture.return_value = mock_cam

        device = CaptureDevice()
        device.setCamera(0)

        assert device.camera_width == 1920
        assert device.camera_height == 1080

    @patch("kvm_serial.backend.video.sys")
    @patch("kvm_serial.backend.video.cv2")
    def test_raises_on_failed_open(self, mock_cv2, mock_sys):
        from kvm_serial.backend.video import CaptureDevice, CaptureDeviceException

        mock_sys.platform = "linux"
        mock_cam = MagicMock()
        mock_cam.isOpened.return_value = False
        mock_cv2.VideoCapture.return_value = mock_cam

        device = CaptureDevice()
        with pytest.raises(CaptureDeviceException):
            device.setCamera(0)

    @patch("kvm_serial.backend.video.sys")
    @patch("kvm_serial.backend.video.cv2")
    def test_raises_on_failed_frame_read(self, mock_cv2, mock_sys):
        from kvm_serial.backend.video import CaptureDevice, CaptureDeviceException

        mock_sys.platform = "linux"
        mock_cam = MagicMock()
        mock_cam.isOpened.return_value = True
        mock_cam.read.return_value = (False, None)
        mock_cv2.VideoCapture.return_value = mock_cam

        device = CaptureDevice()
        with pytest.raises(CaptureDeviceException):
            device.setCamera(0)
