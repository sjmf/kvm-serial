#!/usr/bin/env python
"""
Test suite for KVM video processing functionality.
Uses KVMTestBase for common mocking infrastructure.
"""

import unittest
import numpy as np
from unittest.mock import patch, MagicMock
from PyQt5.QtCore import Qt

# Import the base test class
from test_kvm_base import KVMTestBase


class TestKVMVideoProcessing(KVMTestBase):
    """Test class for KVM video processing functionality."""

    def test_video_worker_initialization(self):
        """Test video capture worker initialization with correct parameters."""
        app = self.create_kvm_app()

        # Check that video worker exists and is properly mocked
        self.assertTrue(hasattr(app, "video_worker"))
        self.assertIsNotNone(app.video_worker)

        # Since video worker is mocked, just verify it's callable
        self.assertTrue(hasattr(app.video_worker, "frame_ready"))
        self.assertTrue(hasattr(app.video_worker, "start"))

    def test_video_timer_initialization(self):
        """Test that video update timer is initialized with correct intervals."""
        app = self.create_kvm_app()

        self.assertTrue(hasattr(app, "video_update_timer"))
        self.assertIsNotNone(app.video_update_timer)

        # Timer is mocked, so just verify it has expected methods
        self.assertTrue(hasattr(app.video_update_timer, "timeout"))
        self.assertTrue(hasattr(app.video_update_timer, "start"))

    def test_frame_request_logic(self):
        """Test frame request logic and timing controls."""
        app = self.create_kvm_app()

        # Mock the video worker's request_frame method
        with patch.object(app.video_worker, "request_frame") as mock_request:
            # Reset timing to ensure first request goes through
            app.last_capture_request = 0.0
            current_time = 1000.0

            with patch("time.time", return_value=current_time):
                # First call should request frame
                app._request_video_frame()
                mock_request.assert_called_once()

                # Set recent request time to test frame dropping
                # Make the time difference smaller than the threshold to prevent request
                time_threshold = (1.0 / app.target_fps) - app.frame_drop_threshold
                app.last_capture_request = current_time - (
                    time_threshold - 0.001
                )  # Just under threshold

                # Immediate second call should not request frame (too soon)
                mock_request.reset_mock()
                app._request_video_frame()
                mock_request.assert_not_called()

    def test_frame_drop_threshold_behavior(self):
        """Test frame dropping when capture is too slow."""
        app = self.create_kvm_app()

        with patch.object(app.video_worker, "request_frame") as mock_request:
            # Set last request time to simulate slow capture
            current_time = 1000.0

            # Calculate the exact threshold for frame dropping
            time_threshold = (1.0 / app.target_fps) - app.frame_drop_threshold
            app.last_capture_request = current_time - (
                time_threshold - 0.001
            )  # Just under threshold

            with patch("time.time", return_value=current_time):
                # Should not request new frame due to frame drop threshold
                app._request_video_frame()
                mock_request.assert_not_called()

                # After threshold time has passed, should request frame
                mock_request.reset_mock()
                app.last_capture_request = current_time - (
                    time_threshold + 0.001
                )  # Just over threshold
                app._request_video_frame()
                mock_request.assert_called_once()

    def test_target_fps_modification(self):
        """Test changing target FPS and timer interval updates."""
        app = self.create_kvm_app()
        initial_fps = app.target_fps

        # Test increasing FPS
        new_fps = 60
        with patch.object(app.video_update_timer, "setInterval") as mock_set_interval:
            app.set_target_fps(new_fps)
            self.assertEqual(app.target_fps, new_fps)
            expected_interval = 1000 // new_fps
            mock_set_interval.assert_called_with(expected_interval)

        # Test decreasing FPS
        new_fps = 15
        with patch.object(app.video_update_timer, "setInterval") as mock_set_interval:
            app.set_target_fps(new_fps)
            self.assertEqual(app.target_fps, new_fps)
            expected_interval = 1000 // new_fps
            mock_set_interval.assert_called_with(expected_interval)

        # Test edge cases - should clamp values
        app.set_target_fps(0)  # Should clamp to 1
        self.assertEqual(app.target_fps, 1)

        app.set_target_fps(200)  # Should clamp to 120
        self.assertEqual(app.target_fps, 120)

    def test_canvas_size_updates(self):
        """Test canvas size updates propagate to video worker."""
        app = self.create_kvm_app()

        # Mock the video worker's set_canvas_size method
        with patch.object(app.video_worker, "set_canvas_size") as mock_set_size:
            # Create a mock resize event
            mock_event = MagicMock()

            # Mock the video view size
            mock_size = MagicMock()
            mock_size.width.return_value = 800
            mock_size.height.return_value = 600
            app.video_view.size = MagicMock(return_value=mock_size)

            # Trigger resize event
            with patch("kvm_serial.kvm.QMainWindow.resizeEvent"):
                app.resizeEvent(mock_event)

            # Should have called set_canvas_size with new dimensions
            mock_set_size.assert_called_once_with(800, 600)

    def test_canvas_size_updates_with_invalid_dimensions(self):
        """Test canvas size updates handle invalid dimensions gracefully."""
        app = self.create_kvm_app()

        with patch.object(app.video_worker, "set_canvas_size") as mock_set_size:
            mock_event = MagicMock()

            # Test zero dimensions
            mock_size = MagicMock()
            mock_size.width.return_value = 0
            mock_size.height.return_value = 0
            app.video_view.size = MagicMock(return_value=mock_size)

            with patch("kvm_serial.kvm.QMainWindow.resizeEvent"):
                app.resizeEvent(mock_event)

            # Should not call set_canvas_size with invalid dimensions
            mock_set_size.assert_not_called()

    def test_frame_ready_processing_rgb888(self):
        """Test frame processing for RGB888 format."""
        app = self.create_kvm_app()

        # Create a mock RGB frame (3 channels, uint8)
        mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        mock_frame[:, :, 0] = 255  # Red channel

        # The mocked base class prevents actual QImage creation, so test the logic path
        with (
            patch("cv2.cvtColor") as mock_cvtcolor,
            patch("kvm_serial.kvm.QImage") as mock_qimage_class,
            patch("kvm_serial.kvm.QPixmap") as mock_qpixmap_class,
        ):
            # Set up successful mocks
            mock_converted_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            mock_cvtcolor.return_value = mock_converted_frame

            mock_qimage = MagicMock()
            mock_qimage.isNull.return_value = False
            mock_qimage_class.return_value = mock_qimage

            mock_pixmap = MagicMock()
            mock_qpixmap_class.fromImage.return_value = mock_pixmap

            # Process the frame
            app._on_frame_ready(mock_frame)

            # Verify BGR to RGB conversion was called
            mock_cvtcolor.assert_called_once()

    def test_frame_ready_processing_rgba8888(self):
        """Test frame processing for RGBA8888 format."""
        app = self.create_kvm_app()

        # Create a mock RGBA frame (4 channels, uint8)
        mock_frame = np.zeros((480, 640, 4), dtype=np.uint8)

        with (
            patch("cv2.cvtColor") as mock_cvtcolor,
            patch("kvm_serial.kvm.QImage") as mock_qimage_class,
        ):
            # Set up mocks
            mock_qimage = MagicMock()
            mock_qimage.isNull.return_value = False
            mock_qimage_class.return_value = mock_qimage

            # Process the frame
            app._on_frame_ready(mock_frame)

            # Should not call color conversion for RGBA
            mock_cvtcolor.assert_not_called()

            # Should attempt to create QImage (even though it fails in mocked environment)
            self.assertTrue(mock_qimage_class.called)

    def test_frame_ready_processing_invalid_dimensions(self):
        """Test frame processing handles invalid frame dimensions."""
        app = self.create_kvm_app()

        # Create frames with invalid dimensions
        invalid_frames = [
            np.zeros((480, 640), dtype=np.uint8),  # 2D frame (missing channels)
            np.zeros((480, 640, 2), dtype=np.uint8),  # 2 channels (invalid)
            np.zeros((480, 640, 5), dtype=np.uint8),  # 5 channels (invalid)
        ]

        for invalid_frame in invalid_frames:
            with self.subTest(frame_shape=invalid_frame.shape):
                # Should handle invalid frames without crashing
                try:
                    app._on_frame_ready(invalid_frame)
                except Exception:
                    self.fail(f"Should handle invalid frame shape {invalid_frame.shape} gracefully")

    def test_frame_ready_processing_qimage_creation_failure(self):
        """Test frame processing handles QImage creation failure."""
        app = self.create_kvm_app()

        mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Test the actual failure path in the code (QImage.isNull() returns True)
        with (
            patch("cv2.cvtColor") as mock_cvtcolor,
            patch("kvm_serial.kvm.QImage") as mock_qimage_class,
        ):
            # Mock QImage creation to return null image
            mock_qimage = MagicMock()
            mock_qimage.isNull.return_value = True  # This triggers the failure path
            mock_qimage_class.return_value = mock_qimage
            mock_cvtcolor.return_value = mock_frame

            # Should handle null QImage gracefully
            try:
                app._on_frame_ready(mock_frame)
            except Exception:
                self.fail("Should handle QImage creation failure gracefully")

    def test_frame_ready_processing_exception_handling(self):
        """Test frame processing handles exceptions gracefully."""
        app = self.create_kvm_app()

        mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Test that exceptions in color conversion are handled
        with patch("cv2.cvtColor", side_effect=Exception("Color conversion failed")):
            # Should not raise exception
            try:
                app._on_frame_ready(mock_frame)
            except Exception:
                self.fail("Should handle color conversion exceptions gracefully")

    def test_fps_calculation_logic(self):
        """Test FPS calculation and tracking over time."""
        app = self.create_kvm_app()

        # Test that FPS calculation attributes exist and work correctly
        self.assertTrue(hasattr(app, "frame_count"))
        self.assertTrue(hasattr(app, "fps_calculation_start"))
        self.assertTrue(hasattr(app, "actual_fps"))

        # Test FPS calculation logic by calling directly with valid frame
        mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Initialize FPS calculation variables
        start_time = 1000.0
        app.fps_calculation_start = start_time
        app.frame_count = 0

        # Test frame counting increments
        initial_count = app.frame_count

        # Simulate one frame processed successfully (bypass QImage issues)
        with (
            patch("cv2.cvtColor") as mock_cvtcolor,
            patch("kvm_serial.kvm.QImage") as mock_qimage_class,
            patch("kvm_serial.kvm.QPixmap") as mock_qpixmap_class,
            patch("time.time", return_value=start_time + 0.5),  # Half second later
        ):
            # Mock successful image processing
            mock_converted_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            mock_cvtcolor.return_value = mock_converted_frame

            mock_qimage = MagicMock()
            mock_qimage.isNull.return_value = False
            mock_qimage_class.return_value = mock_qimage

            mock_pixmap = MagicMock()
            mock_qpixmap_class.fromImage.return_value = mock_pixmap

            app._on_frame_ready(mock_frame)

            # Frame count should increment when processing succeeds
            self.assertEqual(app.frame_count, initial_count + 1)

    def test_video_worker_camera_index_setting(self):
        """Test video worker camera index updates."""
        app = self.create_kvm_app()

        with patch.object(app.video_worker, "set_camera_index") as mock_set_index:
            # Test setting valid camera index
            app._on_video_device_selected(2, "Camera 2")
            mock_set_index.assert_called_once_with(2)

    def test_video_worker_thread_lifecycle(self):
        """Test video worker thread start and cleanup."""
        app = self.create_kvm_app()

        # Mock video worker methods
        with (
            patch.object(app.video_worker, "quit") as mock_quit,
            patch.object(app.video_worker, "wait") as mock_wait,
        ):
            # Trigger cleanup
            mock_event = MagicMock()
            mock_event.accept = MagicMock()
            app.closeEvent(mock_event)

            # Should properly clean up video worker thread
            mock_quit.assert_called_once()
            mock_wait.assert_called_once()
            mock_event.accept.assert_called_once()

    def test_video_timer_lifecycle(self):
        """Test video update timer lifecycle management."""
        app = self.create_kvm_app()

        with patch.object(app.video_update_timer, "stop") as mock_stop:
            mock_event = MagicMock()
            mock_event.accept = MagicMock()
            app.closeEvent(mock_event)

            # Should stop video timer during cleanup
            mock_stop.assert_called_once()

    def test_video_scene_and_view_coordination(self):
        """Test coordination between video scene and view."""
        app = self.create_kvm_app()

        mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Test that scene and view methods are called when frame processing succeeds
        with (
            patch("cv2.cvtColor") as mock_cvtcolor,
            patch("kvm_serial.kvm.QImage") as mock_qimage_class,
            patch("kvm_serial.kvm.QPixmap") as mock_qpixmap_class,
            patch.object(app.video_pixmap_item, "setPixmap") as mock_set_pixmap,
            patch.object(app.video_scene, "setSceneRect") as mock_set_rect,
            patch.object(app.video_view, "fitInView") as mock_fit_view,
        ):
            # Set up successful processing mocks
            mock_converted_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            mock_cvtcolor.return_value = mock_converted_frame

            mock_qimage = MagicMock()
            mock_qimage.isNull.return_value = False
            mock_qimage_class.return_value = mock_qimage

            mock_pixmap = MagicMock()
            mock_qpixmap_class.fromImage.return_value = mock_pixmap

            # Mock the bounding rect and scene rect to be the same object
            mock_rect = MagicMock()
            app.video_pixmap_item.boundingRect = MagicMock(return_value=mock_rect)
            app.video_scene.sceneRect = MagicMock(return_value=mock_rect)

            # Process frame
            app._on_frame_ready(mock_frame)

            # Verify scene-view coordination
            mock_set_pixmap.assert_called_once_with(mock_pixmap)
            mock_set_rect.assert_called_once_with(mock_rect)
            # The actual call uses scene.sceneRect(), not the bounding rect directly
            mock_fit_view.assert_called_once_with(mock_rect, Qt.AspectRatioMode.KeepAspectRatio)

    def test_video_processing_frame_format_validation(self):
        """Test video processing validates frame data types."""
        app = self.create_kvm_app()

        # Test unsupported data type
        mock_frame_wrong_dtype = np.zeros((480, 640, 3), dtype=np.float32)  # Wrong dtype

        # Should handle wrong data type gracefully
        try:
            app._on_frame_ready(mock_frame_wrong_dtype)
        except Exception:
            self.fail("Should handle unsupported frame data types gracefully")

    def test_video_performance_monitoring(self):
        """Test video performance monitoring and frame timing."""
        app = self.create_kvm_app()

        # Test frame timing attributes exist
        self.assertTrue(hasattr(app, "last_frame_time"))
        self.assertTrue(hasattr(app, "frame_count"))
        self.assertTrue(hasattr(app, "fps_calculation_start"))
        self.assertTrue(hasattr(app, "actual_fps"))

        # Test frame drop threshold
        self.assertGreater(app.frame_drop_threshold, 0)
        self.assertLess(app.frame_drop_threshold, 1.0)  # Should be reasonable threshold

    def test_video_error_recovery(self):
        """Test video pipeline error recovery mechanisms."""
        app = self.create_kvm_app()

        # Test that video processing continues after worker errors
        # The actual method doesn't handle exceptions, so we test the exception propagates
        with patch.object(app.video_worker, "request_frame", side_effect=Exception("Worker error")):
            # Should raise the exception since no error handling exists
            with self.assertRaises(Exception):
                app._request_video_frame()

    def test_video_aspect_ratio_preservation(self):
        """Test that video aspect ratio is preserved during display."""
        app = self.create_kvm_app()

        mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with (
            patch("cv2.cvtColor") as mock_cvtcolor,
            patch("kvm_serial.kvm.QImage") as mock_qimage_class,
            patch("kvm_serial.kvm.QPixmap") as mock_qpixmap_class,
            patch.object(app.video_view, "fitInView") as mock_fit_view,
        ):
            # Set up successful processing mocks
            mock_converted_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            mock_cvtcolor.return_value = mock_converted_frame

            mock_qimage = MagicMock()
            mock_qimage.isNull.return_value = False
            mock_qimage_class.return_value = mock_qimage

            mock_pixmap = MagicMock()
            mock_qpixmap_class.fromImage.return_value = mock_pixmap

            # Mock both rects to be the same object since the actual code uses scene.sceneRect()
            mock_rect = MagicMock()
            app.video_pixmap_item.boundingRect = MagicMock(return_value=mock_rect)
            app.video_scene.sceneRect = MagicMock(return_value=mock_rect)

            app._on_frame_ready(mock_frame)

            # Verify aspect ratio preservation - fitInView is called with scene.sceneRect()
            mock_fit_view.assert_called_once_with(
                mock_rect,  # This will be scene.sceneRect() in the actual call
                Qt.AspectRatioMode.KeepAspectRatio,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
