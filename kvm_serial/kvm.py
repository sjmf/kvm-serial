#!/usr/bin/env python
import os
import sys
import logging
import time
import math
from typing import cast, Optional
from serial import Serial, SerialException
from PyQt5.QtCore import Qt, QTimer, QSizeF, QEvent, QLocale, pyqtSignal
from PyQt5.QtGui import (
    QIcon,
    QMouseEvent,
    QPixmap,
    QKeyEvent,
    QFocusEvent,
    QWheelEvent,
    QPainter,
)
from PyQt5.QtMultimedia import QCamera, QCameraViewfinderSettings
from PyQt5.QtMultimediaWidgets import QGraphicsVideoItem
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QLabel,
    QAction,
    QMenu,
    QStatusBar,
    QMessageBox,
    QFileDialog,
    QGraphicsView,
    QGraphicsScene,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

try:
    import kvm_serial.utils.settings as settings_util
    from kvm_serial.utils.communication import list_serial_ports
    from kvm_serial.utils import scancode_to_ascii, string_to_scancodes
    from kvm_serial.backend.video import CameraProperties, enumerate_cameras
    from kvm_serial.backend.implementations.qtop import QtOp
    from kvm_serial.backend.implementations.mouseop import MouseOp, MouseButton

except ModuleNotFoundError:
    # Allow running as a script directly
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    import utils.settings as settings_util
    from utils.communication import list_serial_ports
    from utils import scancode_to_ascii, string_to_scancodes
    from backend.video import CameraProperties, enumerate_cameras
    from backend.implementations.qtop import QtOp
    from backend.implementations.mouseop import MouseOp, MouseButton


# Subclass QGraphicsView so clicks inside the view can receive focus and
# emit signals that the main window can wire into its focus handlers.
class VideoGraphicsView(QGraphicsView):
    mousePressed = pyqtSignal(float, float, Qt.MouseButton, bool)
    mouseReleased = pyqtSignal(float, float, Qt.MouseButton, bool)
    mouseMoved = pyqtSignal(float, float)

    def __init__(self, scene=None, parent=None):
        super().__init__(scene, parent)
        # Set click focus policy to maintain focus on Tab
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        # Remove this widget from the tab focus chain entirely
        self.setFocusProxy(None)
        # Enable mouse tracking
        self.setMouseTracking(True)
        self.main_window = None

        # Find and store reference to main window
        widget = self
        while widget and not isinstance(widget, KVMQtGui):
            widget = widget.parent()
        self.main_window = widget

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Ensure the view receives focus when clicked so focus events fire
        self.setFocus()
        # Convert to scene coordinates
        scene_pos = self.mapToScene(event.pos())
        self.mousePressed.emit(scene_pos.x(), scene_pos.y(), event.button(), True)
        return super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        scene_pos = self.mapToScene(event.pos())
        self.mouseReleased.emit(scene_pos.x(), scene_pos.y(), event.button(), False)
        return super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        scene_pos = self.mapToScene(event.pos())
        self.mouseMoved.emit(scene_pos.x(), scene_pos.y())
        # logging.debug(f"View mouse move: {scene_pos.x():.1f}, {scene_pos.y():.1f}")
        return super().mouseMoveEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:
        logging.info("Video view focused - keyboard capture enabled")
        if self.main_window:
            self.main_window.keyboard_var = True
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        logging.info("Video view unfocused - keyboard capture disabled")
        if self.main_window:
            self.main_window.keyboard_var = False
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Let the main window handle the key event first
        if self.main_window:
            self.main_window.keyPressEvent(event)
        # Prevent Qt from using arrow keys for scrolling
        event.accept()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if self.main_window:
            self.main_window.keyReleaseEvent(event)
        event.accept()


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
    keyboard_last: str = ""
    video_var: int = -1
    mouse_var: bool = False

    serial_port_var: str = "Loading serial..."
    baud_rate_var: int = -1
    video_device_var: str = "Loading cameras..."
    keyboard_layout_var: str = "en_GB"
    resolution_var: str = ""  # "WIDTHxHEIGHT", empty means auto (from camera enumeration)

    window_var: bool = False
    show_status_var: bool = True
    # Video scale: "fit" (fill view, preserve aspect) or a numeric string parsed as a
    # fixed pixel scale factor (e.g. "0.25", "0.5", "1", "2")
    scale_mode_var: str = "fit"
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
    window_default_width: int = 1280
    window_default_height: int = 720
    window_min_width: int = 512
    window_min_height: int = 320
    status_bar_default_height: int = 24  # Typical status bar height in pixels

    # Video
    video_view: QGraphicsView
    video_scene: QGraphicsScene
    video_item: QGraphicsVideoItem
    qcamera: Optional[QCamera] = None  # Active QCamera instance (None until enumeration completes)

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
        self.setWindowTitle("Serial KVM")
        self.setMinimumSize(
            self.window_min_width, self.window_min_height + self.status_bar_default_height
        )
        self.resize(
            self.window_default_width, self.window_default_height + self.status_bar_default_height
        )

        # Set up main layout
        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Create central widget to hold layout
        self.central_widget = QWidget()
        self.central_widget.setLayout(self.main_layout)
        self.setCentralWidget(self.central_widget)

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

        # About
        about_action = QAction("About Serial KVM", self)
        about_action.triggered.connect(self._show_about)
        file_menu.addAction(about_action)

        # Quit
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._on_quit)
        file_menu.addAction(quit_action)

        # Edit Menu
        edit_menu = menubar.addMenu("Edit")
        edit_menu = cast(QMenu, edit_menu)
        self.paste_action = QAction("Paste", self)
        self.paste_action.triggered.connect(self._on_paste)
        edit_menu.addAction(self.paste_action)

        # Screenshot
        screenshot_action = QAction("Take Screenshot", self)
        screenshot_action.triggered.connect(self._take_screenshot)
        edit_menu.addAction(screenshot_action)

        # Add CTRL+ALT+DEL action
        ctrl_alt_del_action = QAction("Send CTRL+ALT+DEL", self)
        ctrl_alt_del_action.triggered.connect(self._send_ctrl_alt_del)
        edit_menu.addAction(ctrl_alt_del_action)

        # Options Menu
        options_menu = menubar.addMenu("Options")
        options_menu = cast(QMenu, options_menu)  # hush PyLance

        # Serial Port, Baud, Video, Resolution, and Keyboard Layout submenus
        self.serial_port_menu = options_menu.addMenu("Serial Port")
        self.baud_rate_menu = options_menu.addMenu("Baud Rate")
        self.video_device_menu = options_menu.addMenu("Video Device")
        self.resolution_menu = options_menu.addMenu("Resolution")
        self.keyboard_layout_menu = options_menu.addMenu("Keyboard Layout")

        options_menu.addSeparator()

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

        # Hide Mouse Pointer option
        self.mouse_action = QAction("Hide Mouse Pointer", self)
        self.mouse_action.setCheckable(True)
        self.mouse_action.triggered.connect(self._toggle_mouse)
        view_menu.addAction(self.mouse_action)

        # Scale Video submenu
        self.scale_menu = cast(QMenu, view_menu.addMenu("Scale Video"))
        self._scale_actions: dict[str, QAction] = {}
        for label, mode in [
            ("Dynamic (Fit to Window)", "fit"),
            ("1:4 ratio", "0.25"),
            ("1:2 ratio", "0.5"),
            ("1:1 ratio", "1"),
            ("2:1 ratio", "2"),
        ]:
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(mode == self.scale_mode_var)
            action.triggered.connect(lambda _checked, m=mode: self._on_scale_mode_selected(m))
            self.scale_menu.addAction(action)
            self._scale_actions[mode] = action

        resize_action = QAction("Resize Window to Video", self)
        resize_action.triggered.connect(self._on_resize_window_to_resolution)
        view_menu.addAction(resize_action)
        view_menu.addSeparator()

        # Fullscreen toggle (macOS provides its own native fullscreen via the green
        # traffic light button and "Enter Full Screen" menu item automatically)
        if sys.platform != "darwin":
            fullscreen_action = QAction("Fullscreen", self)
            fullscreen_action.setCheckable(True)
            fullscreen_action.setShortcut("F11")

            def _toggle_fullscreen():
                if self.isFullScreen():
                    self.showNormal()
                    fullscreen_action.setChecked(False)
                else:
                    self.showFullScreen()
                    fullscreen_action.setChecked(True)

            fullscreen_action.triggered.connect(_toggle_fullscreen)
            view_menu.addAction(fullscreen_action)

            passthrough_action = QAction("Pass Through F11", self)
            passthrough_action.setCheckable(True)

            def _toggle_passthrough(checked):
                fullscreen_action.setShortcut("" if checked else "F11")

            passthrough_action.triggered.connect(_toggle_passthrough)
            view_menu.addAction(passthrough_action)

        logging.debug(f"Menus created")

    def __init_status_bar(self):
        # Status Bar
        self.status_bar = QStatusBar()

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

        # Set as window's status bar
        self.setStatusBar(self.status_bar)

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
        self.video_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.video_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Make view resize its scene automatically
        self.video_view.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.video_view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.video_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # QGraphicsVideoItem is QtMultimedia's video sink that renders directly into
        # a QGraphicsScene. The QCamera (created later, once enumeration completes)
        # streams frames into it via setViewfinder(self.video_item).
        self.video_item = QGraphicsVideoItem()
        self.video_item.setSize(QSizeF(self.window_default_width, self.window_default_height))
        self.video_scene.addItem(self.video_item)
        self.video_scene.setSceneRect(self.video_item.boundingRect())
        # Native size is reported asynchronously after the camera starts streaming.
        self.video_item.nativeSizeChanged.connect(self._on_video_native_size_changed)

        # Add video view to main layout
        self.main_layout.addWidget(self.video_view, 1)  # 1 = stretch factor

        # Set mouse tracking on video view
        self.video_view.setMouseTracking(True)

        # Give the window a chance to show and lay out its widgets
        QApplication.processEvents()

        # Wire focus signals from the view back to the main window handlers.
        # Connect view-local focus signals to dedicated handlers so the
        # keyboard capture state is only affected by focusing inside the view.
        try:
            # Connect mouse signals from view to handlers
            self.video_view.mousePressed.connect(self._on_mouse_click)
            self.video_view.mouseReleased.connect(self._on_mouse_click)
            self.video_view.mouseMoved.connect(self._on_mouse_move)
        except Exception:
            pass

    def __init_timers(self):
        # QtMultimedia owns the frame pipeline; no per-frame Python timer is needed.
        # Defer device enumeration and settings load past the event-loop start.
        QTimer.singleShot(0, self.__init_devices)
        QTimer.singleShot(100, lambda: self._load_settings(self.CONFIG_FILE))

        # Status bar timer
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status_bar)
        self.status_timer.start(500)  # Update every half second

    def __init_devices(self):
        """
        Initialise and populate device lists (serial ports, video devices, keyboard layouts)
        """
        self._populate_serial_ports()
        self._populate_baud_rates()
        self._populate_video_devices()
        self._populate_keyboard_layouts()

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
        self.status_keyboard_label.setText(f"Keyboard: {captured} {self.keyboard_last}")

        camera_width, camera_height = self._camera_resolution()
        report = f"Mouse: [x:{self.pos_x} y:{self.pos_y}] in [{camera_width}x{camera_height}]"
        self.status_mouse_label.setText(report)
        idx = self.video_var

        if idx >= 0 and idx < len(self.video_devices):
            self.status_video_label.setText(f"Video: {str(self.video_devices[idx])}")
        else:
            # Show video_device_var status (e.g., "Initialising...", "None found", "Error")
            # instead of hardcoded "Idle" when no camera is selected
            self.status_video_label.setText(f"Video: {self.video_device_var}")

    def _toggle_verbose(self):
        """Toggle verbose logging and update log level."""
        self.verbose_var = not self.verbose_var
        self.verbose_action.setChecked(self.verbose_var)
        self._apply_log_level()

    def _apply_log_level(self):
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
            or self.resolution_menu is None
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
                    self._set_camera(self.video_devices[idx])
                    # Update menu selection
                    for action in self.video_device_menu.actions():
                        action.setChecked(action.text() == self.video_device_var)
            except (ValueError, TypeError, IndexError):
                logging.warning(
                    f"Invalid video device index in settings: {kvm.get('video_device')}"
                )
        elif self.video_devices:
            # Use default (first device)
            self._set_camera(self.video_devices[0])

        # Load resolution setting — store for use when the resolution menu is populated.
        # The menu may be empty here because camera enumeration is asynchronous;
        # _populate_resolution_menu applies the stored value once cameras are found.
        saved_res = kvm.get("resolution", "")
        if saved_res:
            parts = saved_res.split("x")
            try:
                w, h = int(parts[0]), int(parts[1])
                self.resolution_var = saved_res
                # If the menu is already populated (camera enum finished before settings
                # load), apply immediately so the camera uses the right dimensions.
                available = [a.text() for a in self.resolution_menu.actions()]
                if saved_res in available:
                    self._on_resolution_selected(w, h)
            except (ValueError, IndexError):
                logging.warning(f"Invalid resolution in settings: {saved_res}")

        # Load other boolean settings
        self.window_var = kvm.get("windowed", "False") == "True"
        self.verbose_var = kvm.get("verbose", "False") == "True"
        self.show_status_var = kvm.get("statusbar", "True") == "True"
        self.hide_mouse_var = kvm.get("hide_mouse", "False") == "True"

        # Load keyboard layout, auto-detect if not previously configured
        if "keyboard_layout" in kvm:
            self.keyboard_layout_var = kvm.get("keyboard_layout")
        else:
            # Auto-detect from system locale on first run
            self.keyboard_layout_var = self._detect_system_keyboard_layout()
            logging.info(f"Auto-detected keyboard layout: {self.keyboard_layout_var}")

        # Apply mouse cursor state if needed
        if hasattr(self, "video_view"):
            if self.hide_mouse_var:
                self.video_view.setCursor(Qt.CursorShape.BlankCursor)
            else:
                self.video_view.setCursor(Qt.CursorShape.ArrowCursor)
        # Set the checked state of the menu item if it exists
        if hasattr(self, "mouse_action"):
            self.mouse_action.setChecked(self.hide_mouse_var)
        # And for verbose logging
        if hasattr(self, "verbose_action"):
            self.verbose_action.setChecked(self.verbose_var)
            self._apply_log_level()
        # And for keyboard layout
        if hasattr(self, "keyboard_layout_menu"):
            for action in self.keyboard_layout_menu.actions():
                action.setChecked(action.text() == self.keyboard_layout_var)

        # Initialise serial operations with loaded settings
        self.__init_serial()

        logging.info("Settings loaded from configuration file.")

    def _take_screenshot(self):
        """
        Capture the current video frame and save to clipboard/file.

        Copies the frame to the clipboard, then opens a file dialog for
        saving to disk. If the user cancels the dialog, the frame is
        still available on the clipboard.
        """
        # Grab whatever's currently rendered in the video view (post-scaling).
        # Renders at the camera's native resolution when available, fitting the
        # scene rect set by _on_video_native_size_changed.
        pixmap = self._grab_video_frame()
        if pixmap is None or pixmap.isNull():
            QMessageBox.warning(self, "Screenshot", "No video frame available to capture.")
            return

        # Copy to clipboard
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setPixmap(pixmap)

        # Offer file save dialog
        default_name = time.strftime("kvm_screenshot_%Y%m%d_%H%M%S.png")
        default_dir = os.path.expanduser("~")
        default_path = os.path.join(default_dir, default_name)

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Save Screenshot",
            default_path,
            "PNG Image (*.png)",
        )

        if filepath:
            if pixmap.save(filepath, "PNG"):
                QMessageBox.information(
                    self,
                    "Screenshot",
                    f"Screenshot saved to:\n{filepath}\n\n"
                    "The image has also been copied to the clipboard.",
                )
            else:
                logging.error(f"Failed to save screenshot to {filepath}")
                QMessageBox.warning(
                    self,
                    "Screenshot",
                    f"Failed to save screenshot to:\n{filepath}\n\n"
                    "The image has been copied to the clipboard.",
                )
        else:
            QMessageBox.information(
                self,
                "Screenshot",
                "Screenshot copied to clipboard.",
            )

    def _save_settings(self):
        """
        Save current application settings to the configuration file.
        """
        settings_dict = {
            "serial_port": self.serial_port_var,
            "video_device": str(self.video_var),
            "baud_rate": str(self.baud_rate_var),
            "resolution": self.resolution_var,
            "windowed": str(self.window_var),
            "statusbar": str(self.show_status_var),
            "verbose": str(self.verbose_var),
            "hide_mouse": str(self.hide_mouse_var),
            "keyboard_layout": str(self.keyboard_layout_var),
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

            if len(self.serial_ports) == 0:
                self.serial_port_var = "None found"
                self._populate_serial_port_menu()
                QMessageBox.warning(
                    self,
                    "Start-up Warning",
                    "No serial ports found.\n\n"
                    "Please ensure your USB serial device is connected and drivers are installed.\n"
                    "See documentation for driver installation and troubleshooting instructions.",
                )
            else:
                # Default to the last port found. Set BEFORE menu build so the
                # checkmark loop in _populate_serial_port_menu sees it.
                self.serial_port_var = self.serial_ports[-1]
                self._populate_serial_port_menu()

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

    def _populate_keyboard_layouts(self):
        """
        Populate the keyboard layout menu with available layouts.
        """
        if self.keyboard_layout_menu is None:
            raise TypeError(
                "Initialise keyboard_layout_menu before calling _populate_keyboard_layouts()"
            )

        from kvm_serial.utils import get_available_layouts

        self.keyboard_layout_menu.clear()
        for layout in get_available_layouts():
            action = QAction(layout, self)
            action.setCheckable(True)
            action.triggered.connect(lambda checked, l=layout: self._on_keyboard_layout_selected(l))
            self.keyboard_layout_menu.addAction(action)

            # Check the current selection
            if layout == self.keyboard_layout_var:
                action.setChecked(True)

    def _on_keyboard_layout_selected(self, layout):
        """
        Handle selection of a keyboard layout.
        """
        if self.keyboard_layout_menu is None:
            raise TypeError(
                "Initialise keyboard_layout_menu before calling _on_keyboard_layout_selected()"
            )

        # Uncheck all other layout actions
        for action in self.keyboard_layout_menu.actions():
            action.setChecked(action.text() == layout)

        self.keyboard_layout_var = layout
        logging.info(f"Selected keyboard layout: {layout}")
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
                self.keyboard_op = QtOp(self.serial_port, layout=self.keyboard_layout_var)
                self.mouse_op = MouseOp(self.serial_port)
                logging.info("Initialised keyboard and mouse operations")

            except Exception as e:
                logging.error(f"Failed to initialise serial operations: {e}")
                QMessageBox.critical(
                    self, "Serial Error", f"Failed to open serial port {self.serial_port_var}:\n{e}"
                )
                # Reset to None if initialisation failed
                self.serial_port = None
                self.keyboard_op = None
                self.mouse_op = None

    def _detect_system_keyboard_layout(self) -> str:
        """
        Auto-detect keyboard layout based on system locale using QLocale.
        Recognizes en_US and en_GB variants. Extend in future to detect more keyboards.

        Returns:
            str: Detected keyboard layout ('en_US' or 'en_GB'), defaults to 'en_GB'
        """

        default_layout = "en_GB"
        try:
            # Use QLocale for detection
            system_locale = QLocale.system()
            language = system_locale.language()  # 31 - English
            country = system_locale.country()  # 225- US; 224- GB

            # Map Qt locale to keyboard layout
            if language == QLocale.English:
                # US English -> en_US layout
                if country == QLocale.UnitedStates:
                    return "en_US"
                # All other English variants default to en_GB
                return default_layout
            else:
                # Non-English locales default to en_GB
                logging.debug(
                    f"System locale {system_locale.name()} is not English, defaulting to {default_layout}"
                )
                return default_layout
        except Exception as e:
            logging.warning(
                f"Failed to auto-detect keyboard layout: {e}, defaulting to {default_layout}"
            )
            # Fallback: Scrape environment variables for locale information:
            # Format is typically "en_US.UTF-8" or "en_GB"
            # This isn't really needed with working QLocale option, so commented out.
            # locale_env = os.environ.get("LANG") or os.environ.get("LC_ALL") or ""
            # if locale_env:
            #     # Extract the locale code (e.g., "en_US" from "en_US.UTF-8")
            #     locale_code = locale_env.split(".")[0]
            #     logging.debug(f"Detected locale from environment: {locale_code}")

            #     if locale_code.startswith("en_US"):
            #         return "en_US"
            #     elif locale_code.startswith("en_"):
            #         # en_GB, en_AU, en_CA, etc. all map to en_GB
            #         return default_layout

            return default_layout

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
        Enumerate cameras via QtMultimedia and populate the device menu.

        Enumeration is synchronous on the main thread. QCamera lifecycle
        objects must be created in a thread with a running event loop, and Qt
        spins one in the QApplication main thread, so we don't move this off-
        thread (the legacy background enumerator existed for the pyobjc/comtypes
        probe path that this commit removes).
        """
        self.video_device_var = "Initialising..."
        try:
            cameras = enumerate_cameras()
        except Exception as e:
            logging.error(f"Error discovering video devices: {e}")
            QMessageBox.critical(self, "Error", f"Failed to discover video devices: {e}")
            self.video_devices = []
            self.video_device_var = "Error"
            return

        self.video_devices = cameras
        logging.info(f"Found video devices: {[str(v) for v in cameras]}")

        if cameras:
            # Set the active selection BEFORE populating the menu so the menu
            # builder can render the checkmark on the correct entry.
            self.video_device_var = str(cameras[0])
            self.video_var = 0
            self._populate_video_device_menu()
            self._set_camera(cameras[0])
            self._populate_resolution_menu(0)
        else:
            self._populate_video_device_menu()
            self.video_device_var = "None found"
            message = (
                "No video devices found.\n\n"
                "Ensure a video capture device is connected and recognised by the system."
                "\n\nIf you have just granted camera permissions, please restart the "
                "application for the changes to take effect."
            )
            QMessageBox.warning(self, "Start-up Warning", message)

    def _on_camera_initialization_error(self, error_msg):
        """
        Callback when camera load/start fails.
        Shows error to user and allows them to select a different camera.
        """
        logging.error(f"Camera initialization error: {error_msg}")
        QMessageBox.critical(
            self,
            "Camera Error",
            f"{error_msg}\n\nPlease select a different camera from the Video menu.",
        )
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

        selected_camera = (
            self.video_devices[device_idx] if 0 <= device_idx < len(self.video_devices) else None
        )

        if selected_camera:
            self._set_camera(selected_camera)
            logging.info(
                f"Selected video device: {device_label} "
                f"({selected_camera.width}x{selected_camera.height})"
            )
        else:
            logging.warning(f"Selected video device: {device_label} (no CameraProperties)")

        self._populate_resolution_menu(device_idx)

    def _populate_resolution_menu(self, position: int):
        """
        Populate the resolution menu from the cached CameraProperties at position.

        Reads resolutions from self.video_devices[position].resolutions, populated
        by Qt at enumeration time. The current resolution_var selection is preserved
        when repopulating.
        """
        if self.resolution_menu is None:
            raise TypeError("Initialise resolution_menu before calling _populate_resolution_menu()")

        camera = self.video_devices[position] if 0 <= position < len(self.video_devices) else None
        resolutions = list(camera.resolutions) if camera and camera.resolutions else []
        logging.info(
            "Using %d cached resolutions for device at position %d", len(resolutions), position
        )

        self.resolution_menu.clear()

        use_max_action = QAction("Use Default", self)
        use_max_action.setCheckable(True)
        use_max_action.setChecked(self.resolution_var == "")
        use_max_action.triggered.connect(self._on_use_default_selected)
        self.resolution_menu.addAction(use_max_action)

        self.resolution_menu.addSeparator()

        for width, height in resolutions:
            label = f"{width}x{height}"
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(label == self.resolution_var)
            action.triggered.connect(
                lambda checked, w=width, h=height: self._on_resolution_selected(w, h)
            )
            self.resolution_menu.addAction(action)

        # Apply any resolution loaded from settings (or carried over from a prior
        # device selection) now that the menu exists and the camera is ready.
        # If the requested resolution is not supported by this device, fall back
        # to the device default rather than handing QCamera a value it will reject
        # with "Failed to configure preview format" — this happens when the user
        # picks a custom resolution on one camera and then switches to a camera
        # whose viewfinder settings don't include that resolution.
        if self.resolution_var and camera is not None:
            try:
                w, h = (int(x) for x in self.resolution_var.split("x"))
            except (ValueError, IndexError):
                return
            if (w, h) in camera.resolutions:
                self._set_camera(camera, width=w, height=h)
            else:
                logging.info(
                    f"Resolution {self.resolution_var} not supported by {camera.name}; "
                    "falling back to device default"
                )
                self.resolution_var = ""
                for action in self.resolution_menu.actions():
                    action.setChecked(action.text() == "Use Default")

    def _on_use_default_selected(self):
        """
        Clear any explicit resolution override, reverting to the device's default resolution.
        """
        if self.resolution_menu is None:
            raise TypeError("Initialise resolution_menu before calling _on_use_default_selected()")

        for action in self.resolution_menu.actions():
            action.setChecked(action.text() == "Use Default")

        self.resolution_var = ""

        selected_camera = self._selected_camera()
        if selected_camera:
            w, h = selected_camera.default_resolution
            self._set_camera(selected_camera, width=w, height=h)
        logging.info("Resolution set to device default")

    def _on_resolution_selected(self, width: int, height: int):
        """
        Handle selection of an explicit capture resolution.
        """
        if self.resolution_menu is None:
            raise TypeError("Initialise resolution_menu before calling _on_resolution_selected()")

        label = f"{width}x{height}"
        for action in self.resolution_menu.actions():
            action.setChecked(action.text() == label)

        self.resolution_var = label
        selected_camera = self._selected_camera()
        if selected_camera:
            self._set_camera(selected_camera, width=width, height=height)
        logging.info(f"Selected resolution: {label}")

    def _on_scale_mode_selected(self, mode: str):
        """
        Switch video scaling mode. "fit" scales the pixmap to fill the view while preserving
        aspect ratio (current default); "1"/"2"/"4" lock the view to an integer pixel ratio
        and show scrollbars/black borders as needed.
        """
        self.scale_mode_var = mode
        for m, action in self._scale_actions.items():
            action.setChecked(m == mode)

        if mode == "fit":
            policy = Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        else:
            policy = Qt.ScrollBarPolicy.ScrollBarAsNeeded
        self.video_view.setHorizontalScrollBarPolicy(policy)
        self.video_view.setVerticalScrollBarPolicy(policy)

        self._apply_scale_mode()
        logging.info(f"Video scale mode set to: {mode}")

    def _apply_scale_mode(self):
        """Apply the currently selected scale mode to the video view's transform."""
        if self.scale_mode_var == "fit":
            self.video_view.resetTransform()
            self.video_view.fitInView(
                self.video_scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio
            )
        else:
            factor = float(self.scale_mode_var)
            self.video_view.resetTransform()
            self.video_view.scale(factor, factor)

    def _on_resize_window_to_resolution(self):
        """
        Resize the main window so the video view matches the camera resolution scaled
        by the current scale factor. "fit" mode resizes to native (1:1) resolution;
        fixed-ratio modes multiply by their factor (e.g. 2:1 doubles, 1:2 halves).
        """
        if self._is_window_expanded():
            self.showNormal()
            QTimer.singleShot(0, self._resize_window_to_scaled_video)
            return

        self._resize_window_to_scaled_video()

    def _scaled_video_size(self) -> tuple[int, int]:
        """Return the scaled scene size that should fit inside the viewport."""
        camera_width, camera_height = self._camera_resolution()
        factor = 1.0 if self.scale_mode_var == "fit" else float(self.scale_mode_var)
        return (
            int(math.ceil(camera_width * factor)),
            int(math.ceil(camera_height * factor)),
        )

    def _resize_window_to_scaled_video(self):
        """Resize the window so the viewport matches the scaled video size."""
        target_w, target_h = self._scaled_video_size()

        viewport = self.video_view.viewport()
        viewport_w = viewport.width() if viewport is not None else self.video_view.width()
        viewport_h = viewport.height() if viewport is not None else self.video_view.height()

        # Measure the chrome overhead (menubar + statusbar + any margins)
        chrome_w = self.width() - viewport_w
        chrome_h = self.height() - viewport_h

        self.resize(target_w + chrome_w, target_h + chrome_h)
        factor = 1.0 if self.scale_mode_var == "fit" else float(self.scale_mode_var)
        logging.info(
            f"Window resized to {target_w}x{target_h} "
            f"(camera scaled by {factor}x into viewport)"
        )

    def _is_window_expanded(self) -> bool:
        """Return whether the window is fullscreen or maximized."""
        try:
            return self.isFullScreen() or self.isMaximized()
        except RuntimeError:
            return False

    def _on_video_native_size_changed(self, size: QSizeF):
        """
        Update the scene rect and video item size when the camera reports its
        native frame size. QGraphicsVideoItem emits this once the first frame is
        decoded, which is the authoritative resolution (the requested viewfinder
        settings are not always honoured exactly).
        """
        if not size.isValid() or size.width() <= 0 or size.height() <= 0:
            return
        self.video_item.setSize(size)
        self.video_scene.setSceneRect(self.video_item.boundingRect())
        self._apply_scale_mode()
        logging.debug(f"Video native size: {size.width()}x{size.height()}")

    def resizeEvent(self, event):
        """
        Handle window resize events and re-apply the current scale mode so the
        video item refits the new viewport.
        """
        super().resizeEvent(event)
        if hasattr(self, "video_view"):
            self._apply_scale_mode()

    def _selected_camera(self) -> Optional[CameraProperties]:
        if 0 <= self.video_var < len(self.video_devices):
            return self.video_devices[self.video_var]
        return None

    def _camera_resolution(self) -> tuple[int, int]:
        """Native resolution of the running camera, or default from CameraProperties.

        Prefers QGraphicsVideoItem.nativeSize() (what's actually streaming),
        falls back to the CameraProperties default, and finally to the window
        defaults if no camera is active yet.
        """
        if hasattr(self, "video_item"):
            native = self.video_item.nativeSize()
            if native.isValid() and native.width() > 0 and native.height() > 0:
                return int(native.width()), int(native.height())
        cam = self._selected_camera()
        if cam is not None:
            return cam.width, cam.height
        return self.window_default_width, self.window_default_height

    def _set_camera(
        self,
        camera: CameraProperties,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> None:
        """Open `camera` (a CameraProperties) via QCamera and stream into video_item.

        Stops any previously-active QCamera. If width/height are provided, sets
        viewfinder settings to that resolution; otherwise uses the camera default.
        """
        if camera.info is None:
            logging.warning(f"Camera {camera.name} has no QCameraInfo; cannot open")
            return

        # Tear down any previous camera
        if self.qcamera is not None:
            try:
                self.qcamera.stop()
                self.qcamera.unload()
            except Exception as e:
                logging.debug(f"Error stopping previous QCamera: {e}")

        self.qcamera = QCamera(camera.info)
        self.qcamera.setViewfinder(self.video_item)

        # Surface camera errors to the user via the existing error path.
        # Bind the camera into the closure so a deferred error from a previously
        # active QCamera can't read errorString() off whatever's in self.qcamera now.
        self.qcamera.error.connect(
            lambda c=self.qcamera: self._on_camera_initialization_error(c.errorString())
        )

        # Apply viewfinder settings (resolution). Must be set before start().
        target_w = width if width is not None else camera.default_resolution[0]
        target_h = height if height is not None else camera.default_resolution[1]
        if target_w > 0 and target_h > 0:
            settings = QCameraViewfinderSettings()
            settings.setResolution(target_w, target_h)
            self.qcamera.load()
            self.qcamera.setViewfinderSettings(settings)
            logging.info(f"Camera {camera.name} viewfinder set to {target_w}x{target_h}")

        self.qcamera.start()

    def _grab_video_frame(self) -> Optional[QPixmap]:
        """Render the current video item to a QPixmap at native resolution.

        Used by the screenshot path. Falls back to grabbing the view widget if
        the video item has no native size yet (camera hasn't streamed a frame).
        """
        if not hasattr(self, "video_item"):
            return None
        native = self.video_item.nativeSize()
        if native.isValid() and native.width() > 0:
            from PyQt5.QtGui import QPainter as _QPainter

            pixmap = QPixmap(int(native.width()), int(native.height()))
            pixmap.fill(Qt.GlobalColor.black)
            painter = _QPainter(pixmap)
            try:
                self.video_scene.render(
                    painter,
                    target=pixmap.rect(),
                    source=self.video_item.boundingRect(),
                )
            finally:
                painter.end()
            return pixmap
        # No native size yet — grab whatever the view is showing.
        return self.video_view.grab()

    def _on_mouse_click(self, x, y, button, down=True):
        """
        Handle mouse button press and release events, logging and triggering mouse operations.
        Args:
            event: QMouseEvent object containing mouse button and position.
        """
        pressed = "pressed" if down else "released"
        logging.info(f"Mouse {self.BUTTON_MAP[button]} {pressed} at {int(x)},{int(y)}")

        if self.mouse_op:
            self.mouse_op.on_click(x, y, MouseButton[self.BUTTON_MAP[button]], down)

    def _on_mouse_move(self, x, y):
        # Store original scene coordinates
        self.pos_x = int(x)
        self.pos_y = int(y)
        self.mouse_var = True

        # Get the native camera resolution
        camera_width, camera_height = self._camera_resolution()

        if 0 > self.pos_x or self.pos_x >= camera_width:
            logging.debug(f"X coordinate out of bounds: 0 <= {x} >= {camera_width}")
            return False
        elif 0 > self.pos_y or self.pos_y >= camera_height:
            logging.debug(f"Y coordinate out of bounds: 0 <= {y} >= {camera_height}")
            return False

        report = f"Mouse: [x:{self.pos_x} y:{self.pos_y}] in [{camera_width}x{camera_height}]"
        logging.debug(report)
        self.status_mouse_label.setText(report)

        if self.mouse_op:
            try:
                self.mouse_op.on_move(self.pos_x, self.pos_y, camera_width, camera_height)
            except (OverflowError, ValueError) as e:
                logging.error(e)
                logging.error(f"{self.pos_x}, {self.pos_y}, {camera_width}, {camera_height}")

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
        logging.debug(f"Key pressed: {event.key()} (0x{event.key():02x})")

        if self.keyboard_op:
            try:
                # parse_key returns True on successful parse
                self.keyboard_var = self.keyboard_op.parse_key(event)
                if (
                    event.type() == QEvent.Type.KeyPress
                    and event.key() >= Qt.Key.Key_Space
                    and event.key() <= Qt.Key.Key_AsciiTilde
                ):
                    self.keyboard_last = "alphanumeric"
                else:
                    self.keyboard_last = "modifier"
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
        logging.debug(f"Key released: {event.key()} (0x{event.key():02x})")

        try:
            if self.keyboard_op:
                self.keyboard_op.parse_key(event)
        except SerialException as e:
            QMessageBox.critical(self, "Error", f"Error writing to serial port: {e}")
            self._on_quit()

        super().keyReleaseEvent(event)

    def _get_version(self):
        import toml

        try:
            pyproject_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "pyproject.toml"
            )
            with open(pyproject_path, "r") as f:
                data = toml.load(f)
            return data["project"]["version"]
        except Exception as e:
            logging.warning(f"Could not read version from pyproject.toml: {e}")
            return "?"

    def _show_about(self):
        version = self._get_version()
        QMessageBox.about(
            self,
            "About Serial KVM",
            f"<p><b>Serial KVM</b><br/>Version {version}</p>\n"
            "<p>Keyboard/Mouse over Serial using CH9329.<p>\n"
            "<p>(c) 2024-2025 Samantha Finnigan <a href='https://github.com/sjmf'>@sjmf</a> and contributors.</p>"
            "<p>Available under <a href='https://github.com/sjmf/kvm-serial/blob/main/LICENSE.md'>"
            "MIT License</a></p>",
        )

    def _send_ctrl_alt_del(self):
        """Send CTRL+ALT+DEL key combination"""
        if not self.keyboard_op:
            logging.warning("No keyboard operation available")
            return

        try:
            # On macOS, Qt maps Cmd to Control and Ctrl to Meta
            # We want to send actual Control key, so we use Meta on macOS
            ctrl_key = Qt.Key.Key_Control
            if sys.platform == "darwin":
                ctrl_key = Qt.Key.Key_Meta

            # Create synthetic key events
            ctrl_alt_del = [ctrl_key, Qt.Key.Key_Alt, Qt.Key.Key_Delete]

            # Press and release all keys
            for action in [QEvent.Type.KeyPress, QEvent.Type.KeyRelease]:
                for key in ctrl_alt_del:
                    self.keyboard_op.parse_key(
                        QKeyEvent(action, key, Qt.KeyboardModifier.NoModifier)
                    )

            logging.info("Sent CTRL+ALT+DEL")
        except Exception as e:
            logging.error(f"Error sending CTRL+ALT+DEL: {e}")

    def _on_paste(self):
        """Paste text from clipboard to remote machine, transmitting char-wise"""
        if not self.keyboard_op:
            logging.warning("No keyboard operation available")
            return

        try:
            clipboard = QApplication.clipboard()
            if clipboard is None:
                logging.warning("Could not access clipboard")
                return

            paste_text = clipboard.text()
            if not paste_text:
                logging.info("Clipboard is empty")
                return

            # Convert string to scancodes with key-up signals between characters
            scancodes = string_to_scancodes(paste_text, key_repeat=1, key_up=1)

            # Disable paste action while transmitting
            self.paste_action.setEnabled(False)

            # Start transmitting scancodes asynchronously
            self._send_next_scancode(scancodes, 0, len(paste_text))
        except Exception as e:
            logging.error(f"Error pasting from clipboard: {e}")
            self.paste_action.setEnabled(True)

    def _send_next_scancode(self, scancodes: list, index: int, char_count: int):
        """Send the next scancode in the paste buffer, scheduling the next one via QTimer"""
        if index >= len(scancodes):
            logging.info(f"Pasted {char_count} characters")
            self.paste_action.setEnabled(True)
            return

        try:
            scancode = scancodes[index]
            char_repr = scancode_to_ascii(scancode) or "?"
            logging.debug(
                f"Paste [{index}]: {char_repr!r} -> ({', '.join(hex(b) for b in scancode)})"
            )
            self.keyboard_op.hid_serial_out.send_scancode(bytes(scancode))  # type: ignore
        except Exception as e:
            logging.error(f"Error during paste at index {index}: {e}")
            self.paste_action.setEnabled(True)
            return

        # Schedule the next scancode after 10ms delay:
        # I'm tracking `index` here - arguably we could use a deque for scancodes, and
        #  do .popleft() instead. I've implemented it this way out of performance concerns,
        #  plus, it's more debuggable if we don't mutate state every time we hit the function.
        QTimer.singleShot(10, lambda: self._send_next_scancode(scancodes, index + 1, char_count))

    def closeEvent(self, event):
        """Clean up resources when closing the application"""
        # Stop and tear down the active QCamera (QtMultimedia owns the threading
        # internally, so no manual quit/wait is needed)
        if self.qcamera is not None:
            try:
                self.qcamera.stop()
                self.qcamera.unload()
            except Exception as e:
                logging.debug(f"Error stopping QCamera on close: {e}")
            self.qcamera = None

        # Close serial port if open
        self._close_serial_port()

        event.accept()

    def _on_quit(self) -> None:
        self._quitting = True
        self.close()


def _resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller.

    PyInstaller onefile builds extract bundled data files to a temporary
    directory and expose its path via sys._MEIPASS. When running from source,
    resolve relative to the project root instead.
    """
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", relative_path)


def main():
    """
    Entry point for the application. Configures logging and shows the KVMQtGui main window.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    app = QApplication(sys.argv)

    # Set application icon (used for title bar and taskbar)
    icon_path = _resource_path(os.path.join("assets", "icon.png"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = KVMQtGui()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
