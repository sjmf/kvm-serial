#!/usr/bin/env python
import sys
import os
import tkinter as tk
from tkinter import messagebox
import logging
from typing import List, Callable
from functools import wraps
from PIL import Image, ImageTk
import time

try:
    from kvm_serial.utils.communication import list_serial_ports
    from kvm_serial.backend.video import CameraProperties, CaptureDevice
    from kvm_serial.backend.implementations.tkop import TkOp
    import kvm_serial.utils.settings as settings_util
except ModuleNotFoundError:
    # Allow running as a script directly
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from utils.communication import list_serial_ports
    from backend.video import CameraProperties, CaptureDevice
    from backend.implementations.tkop import TkOp
    import utils.settings as settings_util

logger = logging.getLogger(__name__)


def chainable(func):
    """
    Decorator to allow chaining of callables via a 'chain' argument, using Tkinter's after().
    """

    @wraps(func)
    def wrapper(self, chain: List[Callable] = [], *args, **kwargs):
        result = func(self, chain, *args, **kwargs)
        if chain:
            next_func = chain.pop(0)
            # Schedule the next function in the chain using Tkinter's event loop
            self.after(10, lambda: next_func(chain))
        return result

    return wrapper


class KVMGui(tk.Tk):

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
    verbose_var: tk.BooleanVar

    pos_x: tk.IntVar
    pos_y: tk.IntVar

    def __init__(self) -> None:
        super().__init__()

        self.video_device = CaptureDevice()

        # Dropdown values
        self.baud_rates = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]
        self.serial_ports = []
        self.video_devices = []

        # Window characteristics
        self.canvas_width = 1280
        self.canvas_height = 720
        self.status_bar_height = 24  # Typical status bar height in pixels
        self.title("Serial KVM")
        self.resizable(True, True)
        self.geometry(f"{self.canvas_width}x{self.canvas_height + self.status_bar_height}")

        # UI element backing data vars
        self.keyboard_var = tk.BooleanVar(value=False)
        self.video_var = tk.IntVar(value=-1)
        self.mouse_var = tk.BooleanVar(value=False)
        self.serial_port_var = tk.StringVar(value="Loading serial...")
        self.video_device_var = tk.StringVar(value="Loading cameras...")
        self.baud_rate_var = tk.IntVar(value=self.baud_rates[3])
        self.window_var = tk.BooleanVar(value=False)
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

        # Baud Rate submenu
        self.baud_menu = tk.Menu(options_menu, tearoff=0)
        self.baud_rate_var = tk.IntVar(value=self.baud_rates[0])
        for rate in self.baud_rates:
            self.baud_menu.add_radiobutton(label=str(rate), variable=self.baud_rate_var, value=rate)
        options_menu.add_cascade(label="Baud Rate", menu=self.baud_menu)

        # Serial Port submenu
        self.serial_port_menu = tk.Menu(options_menu, tearoff=0)
        options_menu.add_cascade(label="Serial Port", menu=self.serial_port_menu)

        # Video Device submenu
        self.video_device_menu = tk.Menu(options_menu, tearoff=0)
        options_menu.add_cascade(label="Video Device", menu=self.video_device_menu)

        self.config(menu=menubar)

        # Status Bar
        self.status_var = tk.StringVar(value="Initialising...")
        status_bar = tk.Label(
            self,
            textvariable=self.status_var,
            bd=1,
            relief=tk.SUNKEN,
            anchor=tk.W,
            height=1,  # height in text lines, not pixels
        )
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

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
                self._update_status_bar,
                self._update_video,
            ],
        )

        self._last_video_update = time.time()

    @chainable
    def _run_chained(self, chain: List[Callable] = []) -> None:
        pass

    def _populate_serial_port_menu(self):
        self.serial_port_menu.delete(0, tk.END)
        for port in self.serial_ports:
            self.serial_port_menu.add_radiobutton(
                label=port,
                variable=self.serial_port_var,
                value=port,
                command=lambda p=port: self._on_serial_port_selected(p),
            )

    def _populate_video_device_menu(self):
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
        self.serial_port_var.set(port)

    def _on_video_device_selected(self, device):
        self.video_device_var.set(device)
        idx = int(self.video_device_var.get()[0])
        self.video_device.setCamera(idx)
        self.video_var.set(idx)
        # doesn't update window size though:
        # self.canvas_width = self.video_devices[idx].width
        # self.canvas_height = self.video_devices[idx].height

    @chainable
    def _populate_serial_ports(self, chain: List[Callable] = []) -> None:
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
        kvm = settings_util.load_settings(self.CONFIG_FILE, "KVM")
        # Only set if present in current options
        if kvm.get("serial_port") in self.serial_ports:
            self.serial_port_var.set(kvm.get("serial_port", ""))
        if kvm.get("baud_rate") and int(kvm.get("baud_rate", "")) in self.baud_rates:
            self.baud_rate_var.set(int(kvm.get("baud_rate", "")))

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
        logging.info("Settings loaded from INI file.")

    @chainable
    def _save_settings(self, chain: List[Callable] = []) -> None:
        settings_dict = {
            "serial_port": self.serial_port_var.get(),
            "video_device": str(self.video_var.get()),
            "baud_rate": str(self.baud_rate_var.get()),
            "windowed": str(self.window_var.get()),
            "verbose": str(self.verbose_var.get()),
        }
        settings_util.save_settings(self.CONFIG_FILE, "KVM", settings_dict)
        logging.info("Settings saved to INI file.")

    @chainable
    def _update_status_bar(self, chain: List[Callable] = []) -> None:
        # Track status bar updates
        status_parts = []

        if self.serial_port_var.get():
            status_parts.append(f"Serial: {self.serial_port_var.get()}")

        if self.keyboard_var.get():
            status_parts.append(f"Keyboard: Captured")
        else:
            status_parts.append("Keyboard: Idle")

        idx = self.video_var.get()
        if idx >= 0 and idx < len(self.video_devices):
            video_str = f"Video: {str(self.video_devices[idx])}"
            if hasattr(self, "_actual_fps"):
                video_str += f" [{self._actual_fps:.1f} fps]"
            status_parts.append(video_str)
        else:
            status_parts.append("Video: Idle")

        mouse_pos = f"[x:{self.pos_x.get()} y:{self.pos_y.get()}]"

        if self.mouse_var.get():
            status_parts.append(f"Mouse: {mouse_pos} Captured")
        else:
            status_parts.append(f"Mouse: {mouse_pos} Idle")

        self.status_var.set(" | ".join(status_parts))
        self.after(250, self._update_status_bar)

    @chainable
    def _update_video(self, chain: List[Callable] = []) -> None:
        idx = self.video_var.get()
        start_time = time.time()

        if self.video_device.cam is None:
            self.video_device.setCamera(idx)

        frame = self.video_device.getFrame(resize=(self.canvas_width, self.canvas_height))
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
        # Only update if the size actually changed
        if event.widget == self:
            new_width = event.width
            new_height = event.height - self.status_bar_height
            if new_width != self.canvas_width or new_height != self.canvas_height:
                self.canvas_width = new_width
                self.canvas_height = new_height
                self.main_canvas.config(width=self.canvas_width, height=self.canvas_height)

    def _on_mouse_move(self, event):
        # Bound to movement event. Only update inside canvas
        def inside_x(event):
            return event.x >= 0 and event.x <= self.canvas_width

        def inside_y(event):
            return event.y >= 0 and event.y <= self.canvas_height

        if inside_x(event) and inside_y(event):
            self.pos_x.set(event.x)
            self.pos_y.set(event.y)
            self.mouse_var.set(True)
        else:
            self.mouse_var.set(False)

    def _on_mouse_event(self, event):
        if event.type == tk.EventType.ButtonPress:
            if event.num == 1:
                logging.info(f"Left click at {event.x}, {event.y}")
            elif event.num == 2:
                logging.info(f"Right click at {event.x}, {event.y}")
            elif event.num == 3:
                logging.info(f"Middle click at {event.x}, {event.y}")
        elif event.type == tk.EventType.ButtonRelease:
            logging.info(f"Mouse button {event.num} released at {event.x}, {event.y}")

    def _on_mouse_scroll(self, event):
        logging.info(f"Mouse wheel scroll delta {event.delta} at {event.x}, {event.y}")

    def _on_key_event(self, event):
        if event.type == tk.EventType.KeyPress:
            logging.info(f"Key pressed: {event.keysym} (char: {event.char})")
        elif event.type == tk.EventType.KeyRelease:
            logging.info(f"Key released: {event.keysym} (char: {event.char})")

    def _on_focus_in(self, event):
        logging.info("Window focused")
        self.keyboard_var.set(True)

    def _on_focus_out(self, event):
        logging.info("Window unfocused")
        self.keyboard_var.set(False)


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    app = KVMGui()
    app.mainloop()


if __name__ == "__main__":
    main()
