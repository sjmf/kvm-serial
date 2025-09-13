#!/usr/bin/env python
import os
import sys
import logging
import time
import cv2
from typing import cast
from serial import Serial, SerialException
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QMutex, QMutexLocker, QEvent
from PyQt5.QtGui import QImage, QPixmap, QKeyEvent, QFocusEvent, QWheelEvent
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QLabel,
    QAction,
    QMenuBar,
    QMenu,
    QStatusBar,
    QMessageBox,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
)

try:
    import kvm_serial.utils.settings as settings_util
    from kvm_serial.utils.communication import list_serial_ports
    from kvm_serial.backend.video import CameraProperties, CaptureDevice
    from kvm_serial.backend.implementations.qtop import QtOp
    from kvm_serial.backend.implementations.mouseop import MouseOp, MouseButton

except ModuleNotFoundError:
    # Allow running as a script directly
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    import utils.settings as settings_util
    from utils.communication import list_serial_ports
    from backend.video import CameraProperties, CaptureDevice
    from backend.implementations.qtop import QtOp
    from backend.implementations.mouseop import MouseOp, MouseButton


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
        self.camera_initialised = False
        self.video_device_idx = video_device_idx
        self.mutex = QMutex()
        self.should_capture = False

        # Connect internal signal to capture method
        self.capture_requested.connect(self._capture_frame)

    def set_camera_index(self, idx):
        with QMutexLocker(self.mutex):
            self.video_device_idx = idx
            self.camera_initialised = False

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
            # Initialise camera if needed
            if not self.camera_initialised:
                try:
                    self.video_device.setCamera(self.video_device_idx)
                    self.camera_initialised = True
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


# Subclass QGraphicsView so clicks inside the view can receive focus and
# emit signals that the main window can wire into its focus handlers.
class VideoGraphicsView(QGraphicsView):
    focusGained = pyqtSignal()
    focusLost = pyqtSignal()

    def __init__(self, scene=None, parent=None):
        super().__init__(scene, parent)
        # Accept focus on click so the view becomes the focus widget when clicked
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        # Ensure the view receives focus when clicked so focus events fire
        self.setFocus()
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        try:
            self.focusGained.emit()
        except Exception:
            pass
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        try:
            self.focusLost.emit()
        except Exception:
            pass
        super().focusOutEvent(event)


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

    keyboard_var: bool = False
    video_var: int = -1
    mouse_var: bool = False

    serial_port_var: str = "Loading serial..."
    baud_rate_var: int = -1
    video_device_var: str = "Loading cameras..."

    window_var: bool = False
    show_status_var: bool = True
    status_var: str
    verbose_var: bool = False
    hide_mouse_var: bool = False

    _quitting: bool = False

    pos_x: int = 0
    pos_y: int = 0

    # IO
    serial_port: Serial | None = None
    keyboard_op: QtOp | None = None
    mouse_op: MouseOp | None = None

    # Dimensions
    canvas_width: int = 1280
    canvas_height: int = 720
    canvas_min_width: int = 512
    canvas_min_height: int = 320
    status_bar_default_height: int = 24  # Typical status bar height in pixels

    # Video
    camera_initialised: bool = False  # Camera state
    video_device_idx: int = 0  # Loaded index
    video_view: QGraphicsView
    video_scene: QGraphicsScene
    video_pixmap_item: QGraphicsPixmapItem
    video_update_timer: QTimer
    video_worker: VideoCaptureWorker
    target_fps: int = 30
    frame_drop_threshold: float = 0.05  # Drop frames if capture takes too long (50ms)
    last_capture_request: float = 0.0  # Track when we last requested a frame

    # Status bar labels
    status_bar: QStatusBar
    status_serial_label: QLabel
    status_keyboard_label: QLabel
    status_mouse_label: QLabel
    status_video_label: QLabel

    # Utility dictionary for Mouse button handling
    BUTTON_MAP: dict = {
        Qt.MouseButton.MiddleButton: "MIDDLE",
        Qt.MouseButton.LeftButton: "LEFT",
        Qt.MouseButton.RightButton: "RIGHT",
    }

    def __init__(self) -> None:
        """
        Initialise the KVMQtGui application window, UI elements, variables, menus, and event bindings.
        """
        super().__init__()

        # Initialise state variables
        self.baud_rate_var = self.baud_rates[3]  # Default to 9600

        # Perform initialisation
        self.__init_window()
        self.__init_menu()
        self.__init_status_bar()
        self.__init_video()
        self.__init_timers()

    def __init_window(self):
        # Window characteristics
        self.status_bar_height = self.status_bar_default_height
        self.setWindowTitle("Serial KVM")
        self.setMinimumSize(self.canvas_min_width, self.canvas_min_height)
        self.resize(
            self.canvas_width, self.canvas_height + self.status_bar_height
        )  # 720 + 24 status bar height

        # Make sure the window can receive key events
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def __init_menu(self):

        # Menu Bar
        menubar = self.menuBar()
        # self.setMenuBar(menubar)

        if menubar is None:
            raise TypeError("menubar must be QMenu, not None")

        # addMenu returning None is extremely unlikely in normal desktop apps.
        # The static type stubs for PyQt sometimes mark returns Optional, so
        # type-checkers warn even though runtime None is unlikely.
        # So, while we do check for menubar being None, we can just cast the menus.

        # File Menu
        file_menu = menubar.addMenu("File")
        file_menu = cast(QMenu, file_menu)  # addMenu type annotation is Optional
        save_action = QAction("Save Configuration", self)
        save_action.triggered.connect(self._save_settings)
        file_menu.addAction(save_action)

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._on_quit)
        file_menu.addAction(quit_action)

        # Options Menu
        options_menu = menubar.addMenu("Options")
        options_menu = cast(QMenu, options_menu)  # hush PyLance

        # Serial Port, Baud, and Video submenus
        self.serial_port_menu = options_menu.addMenu("Serial Port")
        self.baud_rate_menu = options_menu.addMenu("Baud Rate")
        self.video_device_menu = options_menu.addMenu("Video Device")

        # Hide Mouse Pointer option
        self.mouse_action = QAction("Hide Mouse Pointer", self)
        self.mouse_action.setCheckable(True)
        self.mouse_action.triggered.connect(self._toggle_mouse)
        options_menu.addAction(self.mouse_action)

        # Verbose Logging option
        self.verbose_action = QAction("Verbose Logging", self)
        self.verbose_action.setCheckable(True)
        self.verbose_action.setChecked(self.verbose_var)
        self.verbose_action.triggered.connect(self._toggle_verbose)
        options_menu.addAction(self.verbose_action)

        # View menu
        view_menu = menubar.addMenu("View")
        view_menu = cast(QMenu, view_menu)  # hush PyLance
        status_action = QAction("Show Status Bar", self)
        status_action.setCheckable(True)
        status_action.setChecked(self.show_status_var)

        def _toggle_status():
            logging.info("Toggling status bar visibility")
            self.show_status_var = not self.show_status_var
            self.status_bar.setVisible(self.show_status_var)

        status_action.triggered.connect(_toggle_status)
        view_menu.addAction(status_action)

        logging.debug(f"Menus created")

    def __init_status_bar(self):
        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Create 4 labels for the sections
        self.status_serial_label = QLabel(self.serial_port_var)
        self.status_keyboard_label = QLabel("Keyboard: Idle")
        self.status_mouse_label = QLabel("Mouse: Idle")
        self.status_video_label = QLabel(self.video_device_var)

        # Add labels to status bar with equal stretch
        self.status_bar.addWidget(self.status_serial_label, 1)
        self.status_bar.addWidget(self.status_keyboard_label, 1)
        self.status_bar.addWidget(self.status_mouse_label, 1)
        self.status_bar.addWidget(self.status_video_label, 1)

        # Style the labels for better visibility
        for label in [
            self.status_serial_label,
            self.status_keyboard_label,
            self.status_mouse_label,
            self.status_video_label,
        ]:
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            label.setStyleSheet("QLabel { border: 1px solid gray; }")

    def __init_video(self):
        # Video Display Area (QGraphicsView)
        self.video_scene = QGraphicsScene(self)
        # Use subclassed view so clicks/focus inside the view can be handled explicitly
        self.video_view = VideoGraphicsView(self.video_scene, self)
        self.video_view.setStyleSheet("background-color: black;")
        self.video_view.setGeometry(0, 0, self.canvas_width, self.canvas_height)
        self.video_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.video_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.video_pixmap_item = QGraphicsPixmapItem()
        self.video_scene.addItem(self.video_pixmap_item)
        self.setCentralWidget(self.video_view)

        # Install event filter to intercept graphics view events
        self.video_scene.installEventFilter(self)
        self.video_view.setMouseTracking(True)

        # Initialise video capture worker thread
        self.video_worker = VideoCaptureWorker(self.canvas_width, self.canvas_height, 0)
        self.video_worker.frame_ready.connect(self._on_frame_ready)
        self.video_worker.start()

        # Wire focus signals from the view back to the main window handlers.
        # Connect view-local focus signals to dedicated handlers so the
        # keyboard capture state is only affected by focusing inside the view.
        try:
            self.video_view.focusGained.connect(self._on_view_focus_gained)
            self.video_view.focusLost.connect(self._on_view_focus_lost)
        except Exception:
            pass

    def __init_timers(self):
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

        # Defer initialisation tasks
        QTimer.singleShot(0, self.__init_devices)
        QTimer.singleShot(100, lambda: self._load_settings(self.CONFIG_FILE))

        # Status bar timer
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status_bar)
        self.status_timer.start(500)  # Update every half second

    def __init_devices(self):
        """
        Initialise and populate device lists (serial ports, video devices)
        """
        self._populate_serial_ports()
        self._populate_baud_rates()
        self._populate_video_devices()

    def _update_status_bar(self):
        """
        Update the status bar with current serial, keyboard, mouse, and video device information.
        """
        if not self.show_status_var:
            return

        # Update each status bar part
        self.status_serial_label.setText(
            f"Serial: {self.serial_port_var} @{self.baud_rate_var} baud"
        )

        captured = "Captured" if self.keyboard_var else "Idle"
        self.status_keyboard_label.setText(f"Keyboard: {captured}")

        self.status_mouse_label.setText(f"Mouse: [x:{self.pos_x} y:{self.pos_y}]")
        idx = self.video_var

        if idx >= 0 and idx < len(self.video_devices):
            video_str = f"Video: {str(self.video_devices[idx])}"
            if hasattr(self, "_actual_fps"):
                video_str += f" [{self._actual_fps:.1f} fps]"
            self.status_video_label.setText(video_str)
        else:
            self.status_video_label.setText("Video: Idle")

    def _toggle_verbose(self):
        """Toggle verbose logging and update log level."""
        self.verbose_var = not self.verbose_var
        self.verbose_action.setChecked(self.verbose_var)
        if self.verbose_var:
            logging.getLogger().setLevel(logging.DEBUG)
            logging.debug("Verbose logging enabled.")
        else:
            logging.getLogger().setLevel(logging.INFO)
            logging.info("Verbose logging disabled.")

    def _load_settings(self, config_file: str):
        """
        Load settings and set variables (deferred).
        """
        kvm = settings_util.load_settings(config_file, "KVM")

        if (
            self.video_device_menu is None
            or self.baud_rate_menu is None
            or self.serial_port_menu is None
        ):
            raise TypeError("Initialise all menus before calling _load_settings")

        # Load serial port setting (only if present in current options)
        if kvm.get("serial_port") in self.serial_ports:
            self.serial_port_var = kvm.get("serial_port", self.serial_ports[-1])
            # Update menu selection
            for action in self.serial_port_menu.actions():
                action.setChecked(action.text() == self.serial_port_var)

        # Load baud rate setting (only if valid)
        if kvm.get("baud_rate") and int(kvm.get("baud_rate", "")) in self.baud_rates:
            self.baud_rate_var = int(kvm.get("baud_rate", ""))
            # Update menu selection
            for action in self.baud_rate_menu.actions():
                action.setChecked(action.text() == str(self.baud_rate_var))

        # Load video device setting
        if kvm.get("video_device") is not None:
            try:
                idx = int(kvm.get("video_device", 0))
                if 0 <= idx < len(self.video_devices):
                    self.video_var = idx
                    self.video_device_var = str(self.video_devices[idx])
                    self.video_worker.set_camera_index(idx)
                    # Update menu selection
                    for action in self.video_device_menu.actions():
                        action.setChecked(action.text() == self.video_device_var)
            except (ValueError, TypeError, IndexError):
                logging.warning(
                    f"Invalid video device index in settings: {kvm.get('video_device')}"
                )
        else:
            # Use default (first device)
            self.video_device_idx = 0
            self.video_worker.set_camera_index(0)

        # Load other boolean settings
        self.window_var = kvm.get("windowed", "False") == "True"
        self.verbose_var = kvm.get("verbose", "False") == "True"
        self.show_status_var = kvm.get("statusbar", "True") == "True"
        self.hide_mouse_var = kvm.get("hide_mouse", "False") == "True"

        # Apply mouse cursor state if needed
        if hasattr(self, "video_view"):
            if self.hide_mouse_var:
                self.video_view.setCursor(Qt.CursorShape.BlankCursor)
            else:
                self.video_view.setCursor(Qt.CursorShape.ArrowCursor)
        # Set the checked state of the menu item if it exists
        if hasattr(self, "mouse_action"):
            self.mouse_action.setChecked(self.hide_mouse_var)

        # Initialise serial operations with loaded settings
        self.__init_serial()

        logging.info("Settings loaded from configuration file.")

    def _save_settings(self):
        """
        Save current application settings to the configuration file.
        """
        settings_dict = {
            "serial_port": self.serial_port_var,
            "video_device": str(self.video_var),
            "baud_rate": str(self.baud_rate_var),
            "windowed": str(self.window_var),
            "statusbar": str(self.show_status_var),
            "verbose": str(self.verbose_var),
            "hide_mouse": str(self.hide_mouse_var),
        }
        settings_util.save_settings(self.CONFIG_FILE, "KVM", settings_dict)
        logging.info("Settings saved to INI file.")
        QMessageBox.information(self, "Save", "Configuration saved.")

    def _populate_serial_ports(self):
        """
        Populate the list of available serial ports and update the menu.
        """
        try:
            self.serial_ports = list_serial_ports()
            logging.info(f"Found serial ports: {self.serial_ports}")
            self._populate_serial_port_menu()

            if len(self.serial_ports) == 0:
                QMessageBox.warning(self, "Start-up Warning", "No serial ports found.")
                self.serial_port_var = "None found"
            else:
                # Default to the last port found
                self.serial_port_var = self.serial_ports[-1]

        except Exception as e:
            logging.error(f"Error discovering serial ports: {e}")
            QMessageBox.critical(self, "Error", f"Failed to discover serial ports: {e}")
            self.serial_ports = []
            self.serial_port_var = "Error"

    def _populate_serial_port_menu(self):
        """
        Populate the serial port dropdown menu with available serial ports.
        """
        if self.serial_port_menu is None:
            raise TypeError(
                "Initialise serial_port_menu before calling _populate_serial_port_menu()"
            )

        self.serial_port_menu.clear()
        for port in self.serial_ports:
            action = QAction(port, self)
            action.setCheckable(True)
            action.triggered.connect(lambda checked, p=port: self._on_serial_port_selected(p))
            self.serial_port_menu.addAction(action)

            # Check the current selection
            if port == self.serial_port_var:
                action.setChecked(True)

    def _populate_baud_rates(self):
        """
        Populate the baud rate menu with available baud rates.
        """
        if self.baud_rate_menu is None:
            raise TypeError("Initialise baud_rate_menu before calling _populate_baud_rates()")

        self.baud_rate_menu.clear()
        for rate in self.baud_rates:
            action = QAction(str(rate), self)
            action.setCheckable(True)
            action.triggered.connect(lambda checked, r=rate: self._on_baud_rate_selected(r))
            self.baud_rate_menu.addAction(action)

            # Check the current selection
            if rate == self.baud_rate_var:
                action.setChecked(True)

    def _on_serial_port_selected(self, port):
        """
        Handle selection of a serial port.
        """
        if self.serial_port_menu is None:
            raise TypeError("Initialise serial_port_menu before calling _on_serial_port_selected()")

        # Uncheck all other serial port actions
        for action in self.serial_port_menu.actions():
            action.setChecked(action.text() == port)

        self.serial_port_var = port
        logging.info(f"Selected serial port: {port}")
        self.__init_serial()

    def _on_baud_rate_selected(self, baud_rate):
        """
        Handle selection of a baud rate.
        """
        if self.baud_rate_menu is None:
            raise TypeError("Initialise baud_rate_menu before calling _on_baud_rate_selected()")

        # Uncheck all other baud rate actions
        for action in self.baud_rate_menu.actions():
            action.setChecked(action.text() == str(baud_rate))

        self.baud_rate_var = baud_rate
        logging.info(f"Selected baud rate: {baud_rate}")
        self.__init_serial()

    def __init_serial(self):
        """
        Initialise or reinitialise serial port and keyboard/mouse operations.
        """
        # Close existing serial connection if open
        self._close_serial_port()

        # Clear existing operations
        self.keyboard_op = None
        self.mouse_op = None

        # Only initialise if we have both port and valid baud rate
        if (
            self.serial_port_var
            and self.serial_port_var not in ["Loading serial...", "None found", "Error"]
            and self.baud_rate_var in self.baud_rates
        ):

            try:
                # Initialise serial port
                self.serial_port = Serial(self.serial_port_var, self.baud_rate_var)
                logging.info(
                    f"Opened serial port {self.serial_port_var} at {self.baud_rate_var} baud"
                )

                # Initialise keyboard and mouse operations
                self.keyboard_op = QtOp(self.serial_port)
                self.mouse_op = MouseOp(self.serial_port)
                logging.info("Initialised keyboard and mouse operations")

            except Exception as e:
                logging.error(f"Failed to initialise serial operations: {e}")
                QMessageBox.critical(
                    self, "Serial Error", f"Failed to open serial port {self.serial_port_var}:\n{e}"
                )
                # Reset to None if initialization failed
                self.serial_port = None
                self.keyboard_op = None
                self.mouse_op = None

    def _close_serial_port(self):
        """
        Utility method to safely close the serial port connection.
        """
        if self.serial_port is not None:
            try:
                self.serial_port.close()
                logging.info("Closed serial port connection")
            except Exception as e:
                logging.error(f"Error closing serial port: {e}")
            self.serial_port = None

    def _populate_video_devices(self):
        """
        Populate the list of available video devices and update the menu.
        """
        try:
            self.video_devices = CaptureDevice.getCameras()
            video_strings = [str(v) for v in self.video_devices]
            logging.info(f"Found video devices: {video_strings}")
            self._populate_video_device_menu()

            if len(self.video_devices) > 0:
                self.video_device_var = str(self.video_devices[0])
                self.video_var = 0  # Default to first device
            else:
                self.video_device_var = "None found"
                QMessageBox.warning(self, "Start-up Warning", "No video devices found.")

        except Exception as e:
            logging.error(f"Error discovering video devices: {e}")
            QMessageBox.critical(self, "Error", f"Failed to discover video devices: {e}")
            self.video_devices = []
            self.video_device_var = "Error"

    def _populate_video_device_menu(self):
        """
        Populate the video device dropdown menu with available video devices.
        """
        if self.video_device_menu is None:
            raise TypeError(
                "Initialise video_device_menu before calling _populate_video_device_menu()"
            )

        self.video_device_menu.clear()
        for i, device in enumerate(self.video_devices):
            label = str(device)
            action = QAction(label, self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _, idx=i, lbl=label: self._on_video_device_selected(idx, lbl)
            )
            self.video_device_menu.addAction(action)

            # Check the current selection
            if i == self.video_var:
                action.setChecked(True)

    def _on_video_device_selected(self, device_idx, device_label):
        """
        Handle selection of a video device.
        """
        if self.video_device_menu is None:
            raise TypeError(
                "Initialise video_device_menu before calling _on_video_device_selected()"
            )

        # Uncheck all other video device actions
        for action in self.video_device_menu.actions():
            action.setChecked(action.text() == device_label)

        self.video_device_var = device_label
        self.video_var = device_idx
        self.video_worker.set_camera_index(device_idx)
        logging.info(f"Selected video device: {device_label} (index: {device_idx})")

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
                self.video_device_var = f"Video FPS: {self.actual_fps:.1f}"

            self.last_frame_time = current_time

        except Exception as e:
            logging.error(f"Error processing video frame: {e}")

    def resizeEvent(self, event):
        """
        Handle window resize events and update video capture size accordingly.
        Args:
            event: Qt event object containing new window dimensions.
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

    def eventFilter(self, source, event):
        """
        Handle mouse movement events within the video_scene, update mouse position.
        This filter receives all events and could be used for other things too.

        Args:
            event: QEvent object – an event that was fired.
        """

        try:
            if source == self.video_scene:
                if event.type() == QEvent.Type.GraphicsSceneMouseMove:
                    pos = event.scenePos()
                    self._on_mouse_move(pos.x(), pos.y())
                elif event.type() == QEvent.Type.GraphicsSceneMousePress:
                    pos = event.scenePos()
                    self._on_mouse_click(pos.x(), pos.y(), event.button(), down=True)
                elif event.type() == QEvent.Type.GraphicsSceneMouseRelease:
                    pos = event.scenePos()
                    self._on_mouse_click(pos.x(), pos.y(), event.button(), down=False)
        except SerialException as e:
            if self._quitting:
                return True # Indicate the event should not be further processed
            
            QMessageBox.critical(self, "Error", f"Error writing to serial port: {e}")
            self._on_quit()

        # Let event continue to original handler
        return super().eventFilter(source, event)

    def _on_mouse_click(self, x, y, button, down=True):
        """
        Handle mouse button press and release events, logging and triggering mouse operations.
        Args:
            event: QMouseEvent object containing mouse button and position.
        """
        pressed = "pressed" if down else "released"
        logging.info(f"Mouse {self.BUTTON_MAP[button]} {pressed} at {x},{y}")

        if self.mouse_op:
            self.mouse_op.on_click(x, y, MouseButton[self.BUTTON_MAP[button]], down)

    def _on_mouse_move(self, x, y):

        self.pos_x = int(x)
        self.pos_y = int(y)
        self.mouse_var = True

        logging.debug(f"Mouse at ({self.pos_x}, {self.pos_y})")
        self.status_mouse_label.setText(f"Mouse: [x:{self.pos_x} y:{self.pos_y}]")

        if self.mouse_op:
            self.mouse_op.on_move(self.pos_x, self.pos_y, self.canvas_width, self.canvas_height)

    def _toggle_mouse(self):
        logging.info("Toggling mouse pointer visibility")
        self.hide_mouse_var = not self.hide_mouse_var
        if self.hide_mouse_var:
            self.video_view.setCursor(Qt.CursorShape.BlankCursor)
        else:
            self.video_view.setCursor(Qt.CursorShape.ArrowCursor)

    def wheelEvent(self, event: QWheelEvent):
        """
        Handle mouse wheel scroll events and trigger mouse scroll operations.
        Args:
            event: Tkinter event object containing scroll delta and position.
        """
        x = event.x()
        y = event.y()
        dx = event.angleDelta().x()
        dy = event.angleDelta().y()

        logging.info(f"Mouse wheel scroll delta {dx} {dy} at {x}, {y}")

        if self.mouse_op:
            self.mouse_op.on_scroll(x, y, dx, dy)

        super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        """
        Handle KeyPress events, logging and triggering keyboard operations.
        Args:
            event: QKeyEvent event object containing key information.
        """
        logging.debug(f"Key pressed: {event.key()}")

        if self.keyboard_op:
            try:
                self.keyboard_op.parse_key(event)
            except SerialException as e:
                QMessageBox.critical(self, "Error", f"Error writing to serial port: {e}")
                self._on_quit()

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent):
        """
        Handle KeyRelease events.
        Args:
            event: QKeyEvent event object containing key information.
        """
        logging.debug(f"Key released: {event.key()}")

        try:
            if self.keyboard_op:
                self.keyboard_op.parse_key(event)
        except SerialException as e:
            QMessageBox.critical(self, "Error", f"Error writing to serial port: {e}")
            self._on_quit()
            
        super().keyReleaseEvent(event)

    def focusInEvent(self, event: QFocusEvent):
        logging.info("Window focused")
        # Do not change keyboard capture state here; the video view manages that.
        super(KVMQtGui, self).focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent):
        logging.info("Window unfocused")
        # Do not change keyboard capture state here; the video view manages that.
        super(KVMQtGui, self).focusOutEvent(event)

    # View-local focus handlers (only affect keyboard capture when the
    # video view receives or loses focus).
    def _on_view_focus_gained(self):
        logging.info("Video view focused")
        self.keyboard_var = True

    def _on_view_focus_lost(self):
        logging.info("Video view unfocused")
        self.keyboard_var = False

    def closeEvent(self, event):
        """Clean up resources when closing the application"""
        # Stop video components
        self.video_update_timer.stop()
        self.video_worker.quit()
        self.video_worker.wait()

        # Close serial port if open
        self._close_serial_port()

        event.accept()

    def _on_quit(self) -> None:
        self._quitting = True
        self.close()


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
