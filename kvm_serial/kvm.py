#!/usr/bin/env python
import sys
import os
import tkinter as tk
from tkinter import messagebox
from typing import List, Callable
from functools import wraps
from PIL import Image, ImageTk
from serial import Serial
import logging
import time

try:
    from kvm_serial.utils.communication import list_serial_ports
    from kvm_serial.backend.video import CameraProperties, CaptureDevice
    from kvm_serial.backend.implementations.tkop import TkOp
    from kvm_serial.backend.implementations.mouseop import MouseOp, MouseButton
    import kvm_serial.utils.settings as settings_util
except ModuleNotFoundError:
    # Allow running as a script directly
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from utils.communication import list_serial_ports
    from backend.video import CameraProperties, CaptureDevice
    from backend.implementations.tkop import TkOp
    from backend.implementations.mouseop import MouseOp, MouseButton
    import utils.settings as settings_util

logger = logging.getLogger(__name__)


def chainable(func):
    """
    Decorator to allow chaining of callables via a 'chain' argument, using Tkinter's after().
    """

    @wraps(func)
    def wrapper(self, chain: List[Callable] = [], *args, **kwargs):
        """
        Wrapper for chainable functions. Executes the function and, if a chain is provided,
        schedules the next function in the chain using Tkinter's event loop.
        Args:
            chain (List[Callable]): List of callables to execute in sequence.
        """
        result = func(self, chain, *args, **kwargs)
        if chain:
            next_func = chain.pop(0)
            # Schedule the next function in the chain using Tkinter's event loop
            self.after(0, lambda: next_func(chain))
        return result

    return wrapper


class KVMGui(tk.Tk):
    """
    Main GUI class for the Serial KVM application.

    A graphical user interface (GUI) for controlling a CH9329-based software KVM (Keyboard, Video, Mouse) switch.

    Provides a Tkinter-based interface for configuring and controlling serial, video, keyboard,
    and mouse devices. Handles device selection, status display, event processing, and persistent
    settings management for the SerialKVM tool.
    """

    CONFIG_FILE = ".kvm_settings.ini"

    baud_rates: list[int]
    serial_ports: list[str]
    video_devices: list[CameraProperties]

    keyboard_var: tk.BooleanVar
    video_var: tk.IntVar
    mouse_var: tk.BooleanVar

    serial_port_var: tk.StringVar
    video_device_var: tk.StringVar

    baud_rate_var: tk.IntVar
    window_var: tk.BooleanVar
    show_status_var: tk.BooleanVar
    status_var: tk.StringVar
    verbose_var: tk.BooleanVar

    pos_x: tk.IntVar
    pos_y: tk.IntVar

    serial_port: Serial | None
    keyboard_op: TkOp | None
    mouse_op: MouseOp | None

    def __init__(self) -> None:
        """
        Initialize the KVMGui application window, UI elements, variables, menus, and event bindings.
        """
        super().__init__()

        self.video_device = CaptureDevice()
        self.serial_port = None
        self.mouse_op = None
        self.keyboard_op = None

        # Dropdown values
        self.baud_rates = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]
        self.serial_ports = []
        self.video_devices = []

        # Window characteristics
        self.canvas_width = 1280
        self.canvas_height = 720
        self.status_bar_default_height = 24  # Typical status bar height in pixels
        self.status_bar_height = self.status_bar_default_height
        self.title("Serial KVM")
        self.resizable(True, True)
        self.minsize(400, 320)
        self.geometry(f"{self.canvas_width}x{self.canvas_height + self.status_bar_height}")

        # UI element backing data vars
        self.keyboard_var = tk.BooleanVar(value=False)
        self.video_var = tk.IntVar(value=-1)
        self.mouse_var = tk.BooleanVar(value=False)
        self.serial_port_var = tk.StringVar(value="Loading serial...")
        self.video_device_var = tk.StringVar(value="Loading cameras...")
        self.baud_rate_var = tk.IntVar(value=self.baud_rates[3])
        self.window_var = tk.BooleanVar(value=False)
        self.show_status_var = tk.BooleanVar(value=True)
        self.verbose_var = tk.BooleanVar(value=False)

        self.pos_x = tk.IntVar(value=0)
        self.pos_y = tk.IntVar(value=0)

        # Menu Bar
        menubar = tk.Menu(self)

        # File Menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Save Configuration", command=self._save_settings)
        file_menu.add_command(label="Quit", command=self.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        # Options Menu
        options_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Options", menu=options_menu)

        # View Menu
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_checkbutton(
            label="Show Status Bar",
            variable=self.show_status_var,
            command=self._toggle_status_bar,
        )
        menubar.add_cascade(label="View", menu=view_menu)

        # Baud Rate submenu
        self.baud_menu = tk.Menu(options_menu, tearoff=0)
        self.baud_rate_var = tk.IntVar(value=self.baud_rates[0])
        for rate in self.baud_rates:
            self.baud_menu.add_radiobutton(
                label=str(rate),
                variable=self.baud_rate_var,
                value=rate,
                command=lambda r=rate: self._on_baud_rate_selected(r),
            )
        options_menu.add_cascade(label="Baud Rate", menu=self.baud_menu)

        # Serial Port submenu
        self.serial_port_menu = tk.Menu(options_menu, tearoff=0)
        options_menu.add_cascade(label="Serial Port", menu=self.serial_port_menu)

        # Video Device submenu
        self.video_device_menu = tk.Menu(options_menu, tearoff=0)
        options_menu.add_cascade(label="Video Device", menu=self.video_device_menu)

        self.config(menu=menubar)

        # Status Bar
        self.status_bar = tk.Frame(self, bd=1, relief=tk.SUNKEN, height=1)
        self.status_serial_label = tk.Label(self.status_bar, anchor=tk.W)
        self.status_keyboard_label = tk.Label(self.status_bar, anchor=tk.W)
        self.status_mouse_label = tk.Label(self.status_bar, anchor=tk.W)
        self.status_video_label = tk.Label(self.status_bar, anchor=tk.W)
        self.status_serial_label.pack(side=tk.LEFT, padx=8)
        self.status_keyboard_label.pack(side=tk.LEFT, padx=8)
        self.status_mouse_label.pack(side=tk.LEFT, padx=8)
        self.status_video_label.pack(side=tk.LEFT, padx=8)
        if self.show_status_var.get():
            self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # Main Window Area (black canvas)
        self.main_canvas = tk.Canvas(
            self, width=self.canvas_width, height=self.canvas_height, bg="black"
        )
        self.main_canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Input event handling
        self.bind("<Configure>", self._on_resize)
        self.bind("<Motion>", self._on_mouse_move)
        self.bind("<Button-1>", self._on_mouse_event)
        self.bind("<Button-2>", self._on_mouse_event)
        self.bind("<Button-3>", self._on_mouse_event)
        self.bind("<ButtonRelease-1>", self._on_mouse_event)
        self.bind("<ButtonRelease-2>", self._on_mouse_event)
        self.bind("<ButtonRelease-3>", self._on_mouse_event)
        self.bind("<MouseWheel>", self._on_mouse_scroll)
        self.bind("<KeyPress>", self._on_key_event)
        self.bind("<KeyRelease>", self._on_key_event)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)

        # Run deferred tasks
        self.after(
            100,
            self._run_chained,
            [
                self._populate_video_devices,
                self._populate_serial_ports,
                self._load_settings,
                self._toggle_status_bar,
                self._update_status_bar,
                self._update_video,
            ],
        )

        self._last_video_update = time.time()

    @chainable
    def _run_chained(self, chain: List[Callable] = []) -> None:
        """
        Placeholder for running a chain of deferred startup tasks using the chainable decorator.
        Args:
            chain (List[Callable]): List of callables to execute in sequence.
        """
        pass

    def _populate_serial_port_menu(self):
        """
        Populate the serial port dropdown menu with available serial ports.
        """
        self.serial_port_menu.delete(0, tk.END)
        for port in self.serial_ports:
            self.serial_port_menu.add_radiobutton(
                label=port,
                variable=self.serial_port_var,
                value=port,
                command=lambda p=port: self._on_serial_port_selected(p),
            )

    def _populate_video_device_menu(self):
        """
        Populate the video device dropdown menu with available video devices.
        """
        self.video_device_menu.delete(0, tk.END)
        for device in self.video_devices:
            label = str(device)
            self.video_device_menu.add_radiobutton(
                label=label,
                variable=self.video_device_var,
                value=label,
                command=lambda d=label: self._on_video_device_selected(d),
            )

    def _on_serial_port_selected(self, port):
        """
        Handle selection of a serial port, update the serial port variable, and initialise
        keyboard and mouse operations.
        Args:
            port (str): The selected serial port.
        """
        self.serial_port_var.set(port)
        if self.serial_port is not None:
            self.serial_port.close()
            self.serial_port = None

        self.serial_port = Serial(port, self.baud_rate_var.get())
        self.keyboard_op = TkOp(self.serial_port)
        self.mouse_op = MouseOp(self.serial_port)

    def _on_baud_rate_selected(self, baud):
        """
        Handle selection of a baud rate, update the baud rate variable, and reinitialise the serial
        port and operations classes that rely on it.
        Args:
            baud (int): The selected baud rate.
        """
        self.baud_rate_var.set(baud)
        if self.serial_port is not None:
            self.serial_port.close()
            self.serial_port = None

        self.serial_port = Serial(self.serial_port_var.get(), baud)
        self.keyboard_op = TkOp(self.serial_port)
        self.mouse_op = MouseOp(self.serial_port)

    def _on_video_device_selected(self, device):
        """
        Handle selection of a video device, update the video device variable, and set the camera index.
        Args:
            device (str): The selected video device label.
        """
        self.video_device_var.set(device)
        idx = int(self.video_device_var.get()[0])
        self.video_device.setCamera(idx)
        self.video_var.set(idx)
        # doesn't update window size though:
        # self.canvas_width = self.video_devices[idx].width
        # self.canvas_height = self.video_devices[idx].height

    @chainable
    def _populate_serial_ports(self, chain: List[Callable] = []) -> None:
        """
        Populate the list of available serial ports and update the UI. Show an error if none are found.
        """
        # Populate the serial devices dropdown
        self.serial_ports = list_serial_ports()
        logging.info(self.serial_ports)
        self._populate_serial_port_menu()
        if len(self.serial_ports) == 0:
            messagebox.showerror("Start-up Error!", "No serial ports found.")
            return
        self.serial_port_var.set(value=self.serial_ports[-1])

    @chainable
    def _populate_video_devices(self, chain: List[Callable] = []) -> None:
        """
        Populate the list of available video devices and update the UI. Show an error if none are found.
        """
        # Populate the video devices dropdown
        self.video_devices = CaptureDevice.getCameras()
        video_strings = [str(v) for v in self.video_devices]
        self._populate_video_device_menu()
        logging.info("\n".join(video_strings))
        if len(self.video_devices) > 0:
            self.video_device_var.set(str(self.video_devices[0]))
            # self._on_video_device_selected()
        else:
            self.video_device_var.set("None found")
            messagebox.showerror("Start-up Error!", "No video devices found.")

    @chainable
    def _load_settings(self, chain: List[Callable] = []) -> None:
        """
        Load application settings from the configuration file and apply them to the UI and device selections.
        """
        kvm = settings_util.load_settings(self.CONFIG_FILE, "KVM")
        # Only set if present in current options
        if kvm.get("serial_port") in self.serial_ports:
            self.serial_port_var.set(kvm.get("serial_port", ""))
        if kvm.get("baud_rate") and int(kvm.get("baud_rate", "")) in self.baud_rates:
            self.baud_rate_var.set(int(kvm.get("baud_rate", "")))

        self._on_serial_port_selected(self.serial_port_var.get())

        if kvm.get("video_device") is not None:
            try:
                # Set video device by its index
                idx = int(kvm.get("video_device", ""))
                if 0 <= idx < len(self.video_devices):
                    self.video_device_var.set(str(self.video_devices[idx]))
                    self.video_var.set(idx)
            except (ValueError, TypeError):
                pass

        # Booleans
        self.window_var.set(kvm.get("windowed", "False") == "True")
        self.verbose_var.set(kvm.get("verbose", "False") == "True")
        self.show_status_var.set(kvm.get("statusbar", "False") == "True")
        logging.info("Settings loaded from INI file.")

    @chainable
    def _save_settings(self, chain: List[Callable] = []) -> None:
        """
        Save current application settings to the configuration file.
        """
        settings_dict = {
            "serial_port": self.serial_port_var.get(),
            "video_device": str(self.video_var.get()),
            "baud_rate": str(self.baud_rate_var.get()),
            "windowed": str(self.window_var.get()),
            "statusbar": str(self.show_status_var.get()),
            "verbose": str(self.verbose_var.get()),
        }
        settings_util.save_settings(self.CONFIG_FILE, "KVM", settings_dict)
        logging.info("Settings saved to INI file.")

    @chainable
    def _update_status_bar(self, chain: List[Callable] = []) -> None:
        """
        Update the status bar with current serial, keyboard, mouse, and video device information.
        """
        if not self.show_status_var.get():
            self.after(1000, self._update_status_bar)
            return

        # Update each status bar part
        self.status_serial_label.config(text=f"Serial: {self.serial_port_var.get()}")
        captured = "Captured" if self.keyboard_var.get() else "Idle"
        self.status_keyboard_label.config(text=f"Keyboard: {captured}")
        mouse_pos = f"[x:{self.pos_x.get()} y:{self.pos_y.get()}]"
        captured = "Captured" if self.mouse_var.get() else "Idle"
        self.status_mouse_label.config(text=f"Mouse: {mouse_pos} {captured}")
        idx = self.video_var.get()
        if idx >= 0 and idx < len(self.video_devices):
            video_str = f"Video: {str(self.video_devices[idx])}"
            if hasattr(self, "_actual_fps"):
                video_str += f" [{self._actual_fps:.1f} fps]"
            self.status_video_label.config(text=video_str)
        else:
            self.status_video_label.config(text="Video: Idle")

        self.after(250, self._update_status_bar)

    @chainable
    def _toggle_status_bar(self, chain: List[Callable] = []) -> None:
        """
        Show or hide the status bar and adjust the main canvas height accordingly.
        """
        if self.show_status_var.get():
            self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
            self.status_bar_height = self.status_bar_default_height
        else:
            self.status_bar.pack_forget()
            self.status_bar_height = 0

        # Adjust canvas height
        new_canvas_height = self.winfo_height() - self.status_bar_height
        if new_canvas_height < 1:
            new_canvas_height = 1
        self.canvas_height = new_canvas_height
        self.main_canvas.config(height=self.canvas_height)

    @chainable
    def _update_video(self, chain: List[Callable] = []) -> None:
        """
        Update the main canvas with the latest video frame from the selected camera device,
        maintaining the correct frame rate if possible, but not blocking the UI if not.
        """
        idx = self.video_var.get()
        start_time = time.time()

        if self.video_device.cam is None:
            self.video_device.setCamera(idx)

        frame = self.video_device.getFrame(
            resize=(self.canvas_width, self.canvas_height),
            convert_color_space=True,
        )
        try:
            # Convert frame to PhotoImage and display on canvas
            image = Image.fromarray(frame)
            photo = ImageTk.PhotoImage(image)
            self.main_canvas.image = photo  # type: ignore # Prevent garbage collection
            self.main_canvas.create_image(0, 0, anchor=tk.NW, image=photo)
        except Exception as e:
            logging.error(f"Error displaying video frame: {e}")

        # Process UI thread events (freezes due to busywait otherwise)
        self.update()

        fps = self.video_devices[idx].fps
        frame_period = 1.0 / fps
        elapsed = time.time() - start_time
        wait_ms = max(0, int((frame_period - elapsed) * 1000))

        # Calculate actual FPS
        if not hasattr(self, "_last_frame_time"):
            self._last_frame_time = start_time
            self._actual_fps = fps
        else:
            now = time.time()
            self._actual_fps = (
                1.0 / (now - self._last_frame_time) if (now - self._last_frame_time) > 0 else fps
            )
            self._last_frame_time = now

        self.after(wait_ms, self._update_video)  # use camera fps

    def _on_resize(self, event):
        """
        Handle window resize events and update the canvas size accordingly.
        Args:
            event: Tkinter event object containing new window dimensions.
        """
        # Only update if the size actually changed
        if event.widget == self:
            new_width = event.width
            new_height = event.height - self.status_bar_height
            if (new_width != self.canvas_width or new_height != self.canvas_height) and (
                new_width > 1 and new_height > 1
            ):
                self.canvas_width = new_width
                self.canvas_height = new_height
                self.main_canvas.config(width=self.canvas_width, height=self.canvas_height)

    def _on_mouse_move(self, event):
        """
        Handle mouse movement events within the canvas, update mouse position, and trigger mouse operations.
        Args:
            event: Tkinter event object containing mouse coordinates.
        """

        # Bound to movement event. Only update inside canvas
        def inside_x(event):
            return event.x >= 0 and event.x <= self.canvas_width

        def inside_y(event):
            return event.y >= 0 and event.y <= self.canvas_height

        if not inside_x(event) or not inside_y(event):
            self.mouse_var.set(False)
            return

        self.pos_x.set(event.x)
        self.pos_y.set(event.y)
        self.mouse_var.set(True)

        if self.mouse_op:
            self.mouse_op.on_move(event.x, event.y, self.canvas_width, self.canvas_height)

    def _on_mouse_event(self, event):
        """
        Handle mouse button press and release events, logging and triggering mouse operations.
        Args:
            event: Tkinter event object containing mouse button and position.
        """
        btn = ["RELEASE", "LEFT", "RIGHT", "MIDDLE"]
        pressed = "pressed" if event.type == tk.EventType.ButtonPress else "released"
        logging.info(f"Mouse {btn[event.num]} {pressed} at {event.x}, {event.y}")

        if self.mouse_op:
            self.mouse_op.on_click(
                event.x,
                event.y,
                MouseButton[btn[event.num]],
                event.type == tk.EventType.ButtonPress,
            )

    def _on_mouse_scroll(self, event):
        """
        Handle mouse wheel scroll events and trigger mouse scroll operations.
        Args:
            event: Tkinter event object containing scroll delta and position.
        """
        logging.info(f"Mouse wheel scroll delta {event.delta} at {event.x}, {event.y}")

        if self.mouse_op:
            self.mouse_op.on_scroll(event.x, event.y, 0, 0)

    def _on_key_event(self, event):
        """
        Handle key press and release events, logging and triggering keyboard operations.
        Args:
            event: Tkinter event object containing key information.
        """
        pressed = "pressed" if event.type == tk.EventType.KeyPress else "released"
        logging.info(f"Key {pressed}: {event.keysym} (char: {event.char})")

        if self.keyboard_op:
            self.keyboard_op.parse_key(event)

    def _on_focus_in(self, event):
        """
        Handle window focus-in events, updating keyboard capture state.
        Args:
            event: Tkinter event object.
        """
        logging.info("Window focused")
        self.keyboard_var.set(True)

    def _on_focus_out(self, event):
        """
        Handle window focus-out events, updating keyboard capture state.
        Args:
            event: Tkinter event object.
        """
        logging.info("Window unfocused")
        self.keyboard_var.set(False)


def main():
    """
    Entry point for the application. Configures logging and starts the KVMGui main loop.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    app = KVMGui()
    app.mainloop()


if __name__ == "__main__":
    main()
