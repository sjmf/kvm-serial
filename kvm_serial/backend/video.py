#!/usr/bin/env python
from typing import List
import sys
import cv2
import numpy
import threading
import logging
import time
from kvm_serial.backend.inputhandler import InputHandler

logger = logging.getLogger(__name__)

CAMERAS_TO_CHECK = 5  # Reduced from 10 - most users have 0-2 cameras
MAX_CAM_FAILURES = 2

# Platform-specific camera backend for better performance and reliability
# Using CAP_ANY lets OpenCV try all backends, which causes 15+ second delays on Windows
if sys.platform == "win32":
    CAMERA_BACKEND = cv2.CAP_DSHOW  # DirectShow on Windows
elif sys.platform == "darwin":
    CAMERA_BACKEND = cv2.CAP_AVFOUNDATION  # AVFoundation on macOS
else:
    CAMERA_BACKEND = cv2.CAP_V4L2  # Video4Linux2 on Linux


class CaptureDeviceException(Exception):
    pass


def _configure_dshow_camera(cam: cv2.VideoCapture, width=1920, height=1080):
    """
    Configure DirectShow camera properties in the correct order.

    On Windows, DirectShow defaults to 640x480 YUY2 and requires explicit
    configuration. Property order matters: dimensions must be set before FOURCC,
    because setting FOURCC auto-populates dimensions from the current device
    state and triggers reconfiguration (see cap_dshow.cpp L3472-L3475).

    Returns True if MJPG was successfully set, False if it fell back to default codec.
    """
    logger.info(f"Configuring DirectShow: requesting {width}x{height} MJPG")
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    mjpg_ok = cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc("M", "J", "P", "G"))
    if not mjpg_ok:
        logger.warning("MJPG not supported by device, using default codec")

    return mjpg_ok


class CameraProperties:
    """
    Describe a reference to a camera attached to the system
    """

    index: int
    width: int
    height: int
    fps: int
    format: int

    FORMAT_STRINGS = ["CV_8U", "CV_8S", "CV_16U", "CV_16S", "CV_32S", "CV_32F", "CV_64F", "Unknown"]
    DTYPE_TO_DEPTH = {
        "uint8": 0,
        "int8": 1,
        "uint16": 2,
        "int16": 3,
        "int32": 4,
        "float32": 5,
        "float64": 6,
    }

    @staticmethod
    def format_from_frame(frame) -> int:
        """Derive OpenCV format (e.g. CV_8UC3=16) from a numpy frame."""
        depth = CameraProperties.DTYPE_TO_DEPTH.get(frame.dtype.name, -1)
        if depth == -1:
            return -1
        channels = frame.shape[2] if frame.ndim == 3 else 1
        return depth + (channels - 1) * 8

    def __init__(self, index, width, height, fps, format):
        self.index = index
        self.width = width
        self.height = height
        self.fps = fps
        self.format = format

    def __getitem__(self, key):
        return getattr(self, key)

    def __str__(self):
        return f"{self.index}: {self.width}x{self.height}@{self.fps}fps ({self.FORMAT_STRINGS[self.format % 8]}/{self.format})"


class CaptureDevice(InputHandler):
    def __init__(self, cam: cv2.VideoCapture = None, fullscreen=False, threaded=False):
        self.cam = cam
        self.fullscreen = fullscreen
        self.running = False
        if threaded:
            self.thread = threading.Thread(target=self.capture)
        else:
            self.thread = None

    def run(self):
        if not isinstance(self.thread, threading.Thread):
            raise CaptureDeviceException("Capture device not running in thread")

        self.thread.start()
        self.thread.join()

    def start(self):
        if not isinstance(self.thread, threading.Thread):
            raise CaptureDeviceException("Capture device not running in thread")

        self.thread.start()

    def stop(self):
        self.running = False

        if isinstance(self.thread, threading.Thread):
            self.thread.join()

    @staticmethod
    def getCameras() -> List[CameraProperties]:
        cameras: List[CameraProperties] = []
        failures = 0

        # Suppress OpenCV logging (available in OpenCV 4.5.5+)
        try:
            cv2.setLogLevel(-1)
        except AttributeError:
            logging.warning("setLogLevel not available in this OpenCV version")

        # check for cameras
        logger.info(f"Enumerating cameras (checking indices 0-{CAMERAS_TO_CHECK-1})...")
        for index in range(0, CAMERAS_TO_CHECK):
            logger.debug(f"Probing camera index {index}...")
            cam = cv2.VideoCapture(index, CAMERA_BACKEND)

            if cam.isOpened():
                # On Windows, DirectShow defaults to 640x480 YUY2 and needs
                # explicit configuration (see issue #19)
                if sys.platform == "win32":
                    _configure_dshow_camera(cam)

                # Read a frame to verify the camera works and get actual dimensions
                ret, frame = cam.read()
                if ret and type(frame) is numpy.ndarray:
                    height, width = frame.shape[:2]
                    fmt = CameraProperties.format_from_frame(frame)
                    if fmt == -1:
                        fmt = int(cam.get(cv2.CAP_PROP_FORMAT))

                    # Use reported FPS if available, otherwise measure it
                    fps = int(cam.get(cv2.CAP_PROP_FPS))
                    if fps <= 0:
                        FPS_SAMPLE_FRAMES = 5
                        t0 = time.perf_counter()
                        for _ in range(FPS_SAMPLE_FRAMES):
                            cam.read()
                        elapsed = time.perf_counter() - t0
                        fps = int(FPS_SAMPLE_FRAMES / elapsed) if elapsed > 0 else 0
                        logger.debug(f"Camera {index} measured FPS: {fps}")

                    cameras.append(
                        CameraProperties(
                            index=index,
                            width=width,
                            height=height,
                            fps=fps,
                            format=fmt,
                        )
                    )
                else:
                    logger.warning(f"Camera {index} opened but failed to read frame")

                cam.release()
            else:
                failures += 1

            if failures >= MAX_CAM_FAILURES:
                break

        logger.info(f"Found {len(cameras)} cameras.")
        logger.debug(cameras)

        return cameras

    def openWindow(self, windowTitle="kvm"):
        windowstring = "fullscreen" if self.fullscreen else "window"
        logger.info(f"Starting video in {windowstring} for window '{windowTitle}'...")

        cv2.namedWindow(windowTitle, cv2.WINDOW_NORMAL)
        if self.fullscreen:
            cv2.setWindowProperty(windowTitle, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    def capture(self, exitKey=27, windowTitle="kvm"):
        # Autonomous capture method can be called to do everything in one
        if not self.cam:
            self.autoSelectCamera()
        self.openWindow()
        self.frameLoop(exitKey=exitKey, windowTitle=windowTitle)

    def autoSelectCamera(self, camIndex=0):
        # Open the default camera
        cameras = CaptureDevice.getCameras()
        self.setCamera(camIndex=cameras[camIndex].index)

    def setCamera(self, camIndex=0):
        self.cam = cv2.VideoCapture(camIndex, CAMERA_BACKEND)

        if not self.cam.isOpened():
            raise CaptureDeviceException(f"Camera {camIndex} failed to open")

        # On Windows, DirectShow defaults to 640x480 YUY2 (see issue #19)
        if sys.platform == "win32":
            _configure_dshow_camera(self.cam)

        # Verify the camera can actually capture frames
        ret, frame = self.cam.read()
        if not ret or type(frame) is not numpy.ndarray:
            logger.warning(f"Camera {camIndex} opened but failed to read frame")
            raise CaptureDeviceException(f"Camera {camIndex} cannot capture frames")

        # Derive actual dimensions from the frame (cam.get() is unreliable on DirectShow)
        self.camera_height, self.camera_width = frame.shape[:2]
        logger.info(f"Camera {camIndex} verified: {self.camera_width}x{self.camera_height}")

    def frameLoop(self, exitKey=27, windowTitle="kvm"):
        try:
            self.running = True
            while self.cam.isOpened():
                # Display the captured frame
                frame = self.getFrame()
                cv2.imshow(windowTitle, frame)

                # Default is 'ESC' to exit the loop
                # 50 = 20fps?
                if cv2.waitKey(50) == exitKey or not self.running:
                    self.cam.release()
        except cv2.error as e:
            logger.error(e)
        finally:
            self.running = False

            # Release the capture and writer objects
            logger.info(f"Camera released. Destroying video window '{windowTitle}'...")
            cv2.destroyWindow(windowTitle)

    def getFrame(self, resize: tuple | None = None, convert_color_space: bool = False):
        if not self.cam:
            raise CaptureDeviceException("No camera configured. Call setCamera(index).")
        _, frame = self.cam.read()
        try:
            if resize:
                frame = cv2.resize(frame, resize)
            if convert_color_space:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return frame
        except cv2.error as e:
            logging.error(e)
            raise e


if __name__ == "__main__":
    cap = CaptureDevice()
    cap.setCamera(1)
    out = cap.getFrame()

    # Test capture device as a script: render as ascii art in terminal
    import sys
    import numpy as np

    term_width = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    out = np.array([[[y[1]] for y in x] for x in out])  # Drop colour channels
    out = cv2.adaptiveThreshold(out, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 11, 2)
    out = cv2.resize(out, (term_width, int(out.shape[0] * (term_width / out.shape[1] / 2))))
    print("\n".join(["".join(["@%#*+=-:. "[pixel // 32] for pixel in row]) for row in out]))
