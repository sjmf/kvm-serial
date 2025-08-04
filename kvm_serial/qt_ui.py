#!/usr/bin/env python
import os
import sys
import logging
import time
import cv2
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QMutex, QMutexLocker
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QAction,
    QMenuBar,
    QStatusBar,
    QMessageBox,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
)

try:
    import kvm_serial.utils.settings as settings_util
    from kvm_serial.backend.video import CameraProperties, CaptureDevice
except ModuleNotFoundError:
    # Allow running as a script directly
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    import utils.settings as settings_util
    from backend.video import CameraProperties, CaptureDevice


class VideoCaptureWorker(QThread):
    """
    Background thread for video frame capture.
    Captures frames on-demand rather than continuously looping.
    """

    frame_ready = pyqtSignal(object)
    capture_requested = pyqtSignal()

    def __init__(self, canvas_width, canvas_height, video_device_idx=0):
        super().__init__()
        self.video_device = CaptureDevice()
        self.canvas_width = canvas_width
        self.canvas_height = canvas_height
        self.camera_initialized = False
        self.video_device_idx = video_device_idx
        self.mutex = QMutex()
        self.should_capture = False

        # Connect internal signal to capture method
        self.capture_requested.connect(self._capture_frame)

    def set_camera_index(self, idx):
        with QMutexLocker(self.mutex):
            self.video_device_idx = idx
            self.camera_initialized = False

    def set_canvas_size(self, width, height):
        with QMutexLocker(self.mutex):
            self.canvas_width = width
            self.canvas_height = height

    def request_frame(self):
        """Request a frame capture from the main thread"""
        self.capture_requested.emit()

    def _capture_frame(self):
        """Internal method to capture a single frame"""
        with QMutexLocker(self.mutex):
            # Initialize camera if needed
            if not self.camera_initialized:
                try:
                    self.video_device.setCamera(self.video_device_idx)
                    self.camera_initialized = True
                except Exception as e:
                    logging.error(f"Failed to set camera index {self.video_device_idx}: {e}")
                    return

            # Capture frame - avoid color conversion if not necessary
            try:
                # Get frame without automatic color conversion for efficiency
                frame = self.video_device.getFrame(
                    resize=(self.canvas_width, self.canvas_height),
                    convert_color_space=False,  # Handle color conversion in display thread if needed
                )
                if frame is not None:
                    self.frame_ready.emit(frame)
            except Exception as e:
                logging.error(f"Error capturing frame: {e}")

    def run(self):
        """Run the event loop for this thread"""
        self.exec_()


class KVMQtGui(QMainWindow):
    """
    Main GUI class for the Serial KVM application (Qt version).

    A graphical user interface (GUI) for controlling a CH9329-based software KVM (Keyboard, Video, Mouse) switch.

    Provides a PyQt5-based interface for configuring and controlling serial, video, keyboard,
    and mouse devices. Handles device selection, status display, event processing, and persistent
    settings management for the SerialKVM tool.
    """

    CONFIG_FILE: str = ".kvm_settings.ini"

    baud_rates: list[int] = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]
    serial_ports: list[str] = []
    video_devices: list = []

    keyboard_var: bool
    video_var: int
    mouse_var: bool

    serial_port_var: str
    video_device_var: str

    baud_rate_var: int
    window_var: bool
    show_status_var: bool
    status_var: str
    verbose_var: bool
    hide_mouse_var: bool

    pos_x: int
    pos_y: int

    serial_port: object | None
    keyboard_op: object | None
    mouse_op: object | None

    canvas_width: int = 1280
    canvas_height: int = 720
    canvas_min_width: int = 512
    canvas_min_height: int = 320
    status_bar_default_height: int = 24  # Typical status bar height in pixels

    video_view: QGraphicsView
    video_scene: QGraphicsScene
    video_pixmap_item: QGraphicsPixmapItem
    video_update_timer: QTimer
    video_worker: VideoCaptureWorker
    target_fps: int = 30
    frame_drop_threshold: float = 0.05  # Drop frames if capture takes too long (50ms)
    last_capture_request: float = 0.0  # Track when we last requested a frame

    def __init__(self) -> None:
        """
        Initialize the KVMQtGui application window, UI elements, variables, menus, and event bindings.
        """
        super().__init__()

        # IO
        self.serial_port = None
        self.mouse_op = None
        self.keyboard_op = None

        # Window characteristics
        self.status_bar_height = self.status_bar_default_height
        self.setWindowTitle("Serial KVM")
        self.setMinimumSize(self.canvas_min_width, self.canvas_min_height)
        self.resize(
            self.canvas_width, self.canvas_height + self.status_bar_height
        )  # 720 + 24 status bar height

        # Dropdown values
        self.video_device_idx: int = 0  # type annotation for loaded index
        self.camera_initialized: bool = False  # type annotation for camera state

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        # Menu Bar
        menubar = QMenuBar(self)
        self.setMenuBar(menubar)

        # File Menu
        file_menu = menubar.addMenu("File")
        save_action = QAction("Save Configuration", self)
        save_action.triggered.connect(self.save_settings)
        file_menu.addAction(save_action)

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Video Display Area (QGraphicsView)
        self.video_scene = QGraphicsScene(self)
        self.video_view = QGraphicsView(self.video_scene, self)
        self.video_view.setStyleSheet("background-color: black;")
        self.video_view.setGeometry(0, 0, self.canvas_width, self.canvas_height)
        self.video_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.video_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.video_pixmap_item = QGraphicsPixmapItem()
        self.video_scene.addItem(self.video_pixmap_item)
        self.setCentralWidget(self.video_view)

        # Initialize video capture worker thread
        self.video_worker = VideoCaptureWorker(self.canvas_width, self.canvas_height, 0)
        self.video_worker.frame_ready.connect(self._on_frame_ready)
        self.video_worker.start()

        # Set up QTimer for frame updates (integrates with Qt event loop)
        self.video_update_timer = QTimer()
        self.video_update_timer.timeout.connect(self._request_video_frame)
        self.video_update_timer.start(1000 // self.target_fps)  # Timer interval in ms

        # Frame timing for performance monitoring
        self.last_frame_time = time.time()
        self.last_capture_request = 0.0
        self.actual_fps = 0.0
        self.frame_count = 0
        self.fps_calculation_start = time.time()

        # Defer settings load
        QTimer.singleShot(0, lambda: self._load_settings(self.CONFIG_FILE))

    def _load_settings(self, config_file: str):
        """
        Load settings and set variables (deferred).
        """
        kvm = settings_util.load_settings(config_file, "KVM")
        self.video_device_idx = int(kvm.get("video_device", 0))
        self.video_worker.set_camera_index(self.video_device_idx)

    def save_settings(self):
        # Placeholder for save logic
        QMessageBox.information(self, "Save", "Configuration saved (placeholder)")

    def _request_video_frame(self):
        """
        Request a new frame from the worker thread.
        Called by QTimer at the target frame rate.
        Implements frame dropping if capture is too slow.
        """
        current_time = time.time()

        # Only request new frame if enough time has passed since last request
        # This prevents queue buildup if capture is slower than display rate
        if (current_time - self.last_capture_request) >= (
            1.0 / self.target_fps - self.frame_drop_threshold
        ):
            self.last_capture_request = current_time
            self.video_worker.request_frame()

    def set_target_fps(self, fps):
        """
        Change the target frame rate and update timer accordingly.
        """
        self.target_fps = max(1, min(fps, 120))  # Clamp between 1-120 fps
        timer_interval = 1000 // self.target_fps
        self.video_update_timer.setInterval(timer_interval)

    def _on_frame_ready(self, frame):
        """
        Handle new frame from worker thread.
        Converts frame efficiently and updates display.
        """
        try:
            if frame.ndim != 3:
                logging.error("Frame was not of expected dimensions")
                return

            h, w, ch = frame.shape
            bytes_per_line = ch * w

            # Handle different color formats efficiently
            if ch == 3:
                # Assume BGR from OpenCV, convert to RGB for Qt only when necessary
                if frame.dtype.name == "uint8":
                    # Convert BGR to RGB only if needed
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    qimg = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
                else:
                    logging.error(f"Unsupported frame data type: {frame.dtype}")
                    return
            elif ch == 4:
                # RGBA format
                qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGBA8888)
            else:
                logging.error(f"Unsupported number of channels: {ch}")
                return

            if qimg.isNull():
                logging.error("Failed to create QImage from frame data")
                return

            # Convert to QPixmap and display
            pixmap = QPixmap.fromImage(qimg)
            self.video_pixmap_item.setPixmap(pixmap)

            # Update FPS calculation (rolling average over multiple frames)
            current_time = time.time()
            self.frame_count += 1

            # Calculate FPS every second for more stable reading
            time_elapsed = current_time - self.fps_calculation_start
            if time_elapsed >= 1.0:
                self.actual_fps = self.frame_count / time_elapsed
                self.frame_count = 0
                self.fps_calculation_start = current_time

                # Update status bar with FPS info
                self.status_bar.showMessage(f"Video FPS: {self.actual_fps:.1f}")

            self.last_frame_time = current_time

        except Exception as e:
            logging.error(f"Error processing video frame: {e}")

    def resizeEvent(self, event):
        """
        Handle window resize events and update video capture size accordingly.
        """
        super().resizeEvent(event)

        # Get new size excluding status bar
        new_size = event.size()
        status_bar_height = self.status_bar.height() if self.status_bar.isVisible() else 0
        new_width = new_size.width()
        new_height = new_size.height() - status_bar_height

        # Update canvas dimensions and inform worker thread
        if new_width > 0 and new_height > 0:
            self.canvas_width = new_width
            self.canvas_height = new_height
            self.video_worker.set_canvas_size(new_width, new_height)

            # Update video view size
            self.video_view.setGeometry(0, 0, new_width, new_height)

    def closeEvent(self, event):
        """Clean up resources when closing the application"""
        self.video_update_timer.stop()
        self.video_worker.quit()
        self.video_worker.wait()
        event.accept()


def main():
    """
    Entry point for the application. Configures logging and shows the KVMQtGui main window.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    app = QApplication(sys.argv)
    window = KVMQtGui()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
