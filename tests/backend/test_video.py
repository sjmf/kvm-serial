from unittest.mock import patch, MagicMock
import pytest
from kvm_serial.backend.video import CameraProperties, CaptureDevice, CaptureDeviceException


class TestCameraProperties:
    def test_camera_properties_initialization(self):
        """Test basic initialization of CameraProperties"""
        props = CameraProperties(index=0, width=1920, height=1080, fps=30, format=0)  # CV_8U format

        assert props.index == 0
        assert props.width == 1920
        assert props.height == 1080
        assert props.fps == 30
        assert props.format == 0

    def test_camera_properties_str(self):
        """Test string representation of CameraProperties"""
        props = CameraProperties(index=1, width=1280, height=720, fps=60, format=0)  # CV_8U format

        expected = "1: 1280x720@60fps (CV_8U/0)"
        assert str(props) == expected


class TestCaptureDevice:
    def test_capture_device_initialization(self):
        """Test basic initialization of CaptureDevice"""
        device = CaptureDevice()
        assert device.cam is None
        assert device.fullscreen is False
        assert device.running is False
        assert device.thread is None

    def test_capture_device_thread_requirement(self):
        """Test that non-threaded CaptureDevice raises exception on run"""
        device = CaptureDevice(threaded=False)
        with pytest.raises(CaptureDeviceException):
            device.run()

    @patch("cv2.VideoCapture")
    def test_capture_device_with_camera(self, mock_video_capture):
        """Test CaptureDevice initialization with a camera"""
        mock_cam = MagicMock()
        device = CaptureDevice(cam=mock_cam, threaded=True)
        assert device.cam == mock_cam
        assert device.thread is not None

    # TODO: Implement further tests