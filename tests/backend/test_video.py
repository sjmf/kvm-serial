import sys
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def sys_modules_patch():
    return {
        "pynput": MagicMock(),
        "numpy": MagicMock(),
        "cv2": MagicMock(),
        "serial": MagicMock(),
    }


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

    # TODO: Implement further tests
