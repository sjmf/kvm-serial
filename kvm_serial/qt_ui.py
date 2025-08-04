#!/usr/bin/env python
import os
import sys
import logging
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
from PyQt5.QtCore import QTimer, Qt

try:
    import kvm_serial.utils.settings as settings_util
    from kvm_serial.backend.video import CameraProperties, CaptureDevice
except ModuleNotFoundError:
    # Allow running as a script directly
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    import utils.settings as settings_util
    from backend.video import CameraProperties, CaptureDevice


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
    video_timer: QTimer

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

        # Defer settings load
        QTimer.singleShot(0, self._load_settings)

        # Load settings and set camera
        kvm = settings_util.load_settings(self.CONFIG_FILE, "KVM")
        video_device_idx = (
            int(kvm.get("video_device", 0)) if kvm.get("video_device") is not None else 0
        )
        try:
            self.video_device.setCamera(video_device_idx)
        except Exception as e:
            logging.error(f"Failed to set camera index {video_device_idx}: {e}")

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

        # Video update timer (e.g., 30 fps)
        self.video_timer = QTimer(self)
        self.video_timer.timeout.connect(self.update_video_frame)
        self.video_timer.start(33)  # ~30 fps

    def _load_settings(self):
        """
        Load settings and set variables (deferred).
        """
        try:
            import kvm_serial.utils.settings as settings_util
        except ModuleNotFoundError:
            import utils.settings as settings_util
        kvm = settings_util.load_settings(self.CONFIG_FILE, "KVM")
        self.video_device_idx = (
            int(kvm.get("video_device", 0)) if kvm.get("video_device") is not None else 0
        )
        self.camera_initialized = False

    def save_settings(self):
        # Placeholder for save logic
        QMessageBox.information(self, "Save", "Configuration saved (placeholder)")

    def update_video_frame(self):
        """
        Fetch and display the next video frame from the camera device.
        Initialize camera if not already done.
        """
        if not self.camera_initialized:
            try:
                self.video_device.setCamera(self.video_device_idx)
                self.camera_initialized = True
            except Exception as e:
                logging.error(f"Failed to set camera index {self.video_device_idx}: {e}")
                return

        # Get frame from camera
        frame = self.video_device.getFrame(
            resize=(self.canvas_width, self.canvas_height),
            convert_color_space=True,
        )
        if frame is None:
            return

        # Convert frame (numpy array) to QImage
        import numpy as np
        from PyQt5.QtGui import QImage, QPixmap

        if frame.ndim == 3 and frame.shape[2] == 3:
            # RGB image
            h, w, ch = frame.shape
            bytes_per_line = ch * w
            qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
        elif frame.ndim == 2:
            # Grayscale
            h, w = frame.shape
            qimg = QImage(frame.data, w, h, w, QImage.Format_Grayscale8)
        else:
            return  # Unsupported format

        pixmap = QPixmap.fromImage(qimg)
        self.video_pixmap_item.setPixmap(pixmap)


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
