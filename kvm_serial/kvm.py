#!/usr/bin/env python
import sys
import os
import subprocess
import configparser
import logging
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
from typing import List, Callable
from functools import wraps

try:
    from kvm_serial.utils.communication import list_serial_ports
    from kvm_serial.backend.video import CameraProperties, CaptureDevice
except ModuleNotFoundError:
    # Allow running as a script directly
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from utils.communication import list_serial_ports
    from backend.video import CameraProperties, CaptureDevice

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
    """
    A graphical user interface (GUI) for controlling a CH9329-based software KVM (Keyboard, Video, Mouse) switch.
    This class provides a Tkinter-based window that allows users to select various options for keyboard, video, and mouse control,
    configure serial port settings, and start or stop the KVM functionalities. It supports different keyboard backends, serial port selection,
    baud rate configuration, and toggling of windowed mode and verbose logging.

    Attributes:
        kb_backends (list): Available keyboard backend options.
        serial_ports (list): List of detected serial ports.
        baud_rates (list): Supported baud rates for serial communication.
        keyboard_var (tk.BooleanVar): State of the keyboard checkbox.
        video_var (tk.BooleanVar): State of the video checkbox.
        mouse_var (tk.BooleanVar): State of the mouse checkbox.
        kb_backend_var (tk.StringVar): Selected keyboard backend.
        serial_port_var (tk.StringVar): Selected serial port.
        video_device_var (tk.StringVar): Selected video device.
        baud_rate_var (tk.IntVar): Selected baud rate.
        window_var (tk.BooleanVar): State of the windowed mode checkbox.
        verbose_var (tk.BooleanVar): State of the verbose logging checkbox.
        process (subprocess.Popen): Handle of the subprocess launched
    Methods:
        __init__():
            Initializes the KVMGui window, widgets, and variables.
        on_start():
            Handles the logic for starting the KVM functionalities based on user selections.
            Sets up logging, establishes serial connection, and starts selected listeners or capture devices.
        stop_threads():
            Stops and cleans up any running listener or capture device threads.
        on_exit():
            Stops all running threads and closes the GUI window.
    """

    CONFIG_FILE = ".kvm_settings.ini"

    kb_backends: list[str]
    baud_rates: list[int]
    serial_ports: list[str]
    video_devices: list[CameraProperties]

    keyboard_var: tk.BooleanVar
    video_var: tk.BooleanVar
    mouse_var: tk.BooleanVar
    kb_backend_var: tk.StringVar
    serial_port_var: tk.StringVar
    video_device_var: tk.StringVar
    baud_rate_var: tk.IntVar
    window_var: tk.BooleanVar
    verbose_var: tk.BooleanVar
    process: subprocess.Popen | None

    keyboard_checkbox: tk.Checkbutton
    video_checkbox: tk.Checkbutton
    mouse_checkbox: tk.Checkbutton

    backend_combo: ttk.Combobox
    serial_port_combo: ttk.Combobox
    baud_rate_combo: ttk.Combobox
    video_device_combo: ttk.Combobox
    start_button: tk.Button

    def __init__(self) -> None:
        super().__init__()

        TYPEFACE = tkfont.nametofont("TkDefaultFont").actual("family")

        # Dropdown values
        self.kb_backends = ["pynput", "curses", "tty", "usb"]
        self.baud_rates = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]
        self.serial_ports = []
        self.video_devices = []

        # Window characteristics
        self.title("Serial KVM")
        self.resizable(False, False)

        # UI element backing data vars
        self.keyboard_var = tk.BooleanVar(value=True)
        self.video_var = tk.BooleanVar(value=True)
        self.mouse_var = tk.BooleanVar(value=True)
        self.kb_backend_var = tk.StringVar(value=self.kb_backends[0])
        self.serial_port_var = tk.StringVar(value="Loading serial...")
        self.video_device_var = tk.StringVar(value="Loading cameras...")
        self.baud_rate_var = tk.IntVar(value=self.baud_rates[3])
        self.window_var = tk.BooleanVar(value=False)
        self.verbose_var = tk.BooleanVar(value=False)

        # Title row
        e = tk.Label(self, text="KVM Controller", font=(TYPEFACE, 14, "bold"))
        e.grid(row=0, column=0, padx=(10, 10), pady=(10, 10))

        # Vertical bar between columns 0 and 1, spanning rows 1-4
        bar = tk.Frame(self, width=1, height=140, bg="gray")
        bar.grid(row=1, column=0, rowspan=4, sticky="ne", padx=(0, 10), pady=(10, 0))

        # Checkboxes
        self.keyboard_checkbox = tk.Checkbutton(self, text="Keyboard", variable=self.keyboard_var)
        self.keyboard_checkbox.grid(row=1, column=0, sticky="w", padx=10, pady=5)
        self.video_checkbox = tk.Checkbutton(self, text="Video", variable=self.video_var)
        self.video_checkbox.grid(row=2, column=0, sticky="w", padx=10, pady=5)
        self.mouse_checkbox = tk.Checkbutton(self, text="Mouse", variable=self.mouse_var)
        self.mouse_checkbox.grid(row=3, column=0, sticky="w", padx=10, pady=5)

        e = tk.Checkbutton(self, text="Windowed", variable=self.window_var)
        e.grid(row=4, column=0, sticky="w", padx=10, pady=5)
        e = tk.Checkbutton(self, text="Verbose Logging (term)", variable=self.verbose_var)
        e.grid(row=0, column=2, sticky="w", padx=10, pady=5)

        # Keyboard backend dropdown
        e = tk.Label(self, text="Keyboard backend")
        e.grid(row=1, column=1, sticky="w", padx=10)
        self.backend_combo = ttk.Combobox(
            self, textvariable=self.kb_backend_var, values=self.kb_backends, state="readonly"
        )
        self.backend_combo.grid(row=1, column=2, padx=10, pady=5)

        # Serial port dropdown
        e = tk.Label(self, text="Serial Port")
        e.grid(row=2, column=1, sticky="w", padx=10)
        self.serial_port_combo = ttk.Combobox(self, textvariable=self.serial_port_var, values=[])
        self.serial_port_combo.grid(row=2, column=2, padx=10, pady=5)

        # Baud rate dropdown
        e = tk.Label(self, text="Baud rate")
        e.grid(row=3, column=1, sticky="w", padx=10)
        self.baud_rate_combo = ttk.Combobox(
            self,
            textvariable=self.baud_rate_var,
            values=[str(b) for b in self.baud_rates],
            state="readonly",
        )
        self.baud_rate_combo.grid(row=3, column=2, padx=10, pady=5)

        # Video Capture device dropdown
        e = tk.Label(self, text="Video Device")
        e.grid(row=4, column=1, sticky="w", padx=10)

        self.video_device_combo = ttk.Combobox(
            self, textvariable=self.video_device_var, values=[], state="readonly"
        )
        self.video_device_combo.grid(row=4, column=2, padx=10, pady=5)

        # Start and Exit buttons
        self.start_button = tk.Button(
            self, text="Start", width=15, command=self.on_start, disabledforeground="black"
        )
        self.start_button.grid(row=5, column=1, pady=20, padx=(0, 5))
        tk.Button(self, text="Exit", width=15, command=self.on_exit).grid(
            row=5, column=2, pady=20, padx=(5, 10)
        )

        # Footer row
        footer = tk.Label(self, text="To exit, press Ctrl + ESC", font=(TYPEFACE, 11), fg="gray")
        footer.grid(row=6, column=0, columnspan=3, pady=(0, 20))

        # Tie combobox state to checkboxes
        self.keyboard_var.trace_add(
            "write", lambda *args: self._on_checkbox_changed(self.keyboard_var, self.backend_combo)
        )
        self.video_var.trace_add(
            "write",
            lambda *args: self._on_checkbox_changed(self.video_var, self.video_device_combo),
        )

        # Run deferred tasks
        self.after(
            100,
            self._run_chained,
            [self._populate_serial_ports, self._populate_video_devices, self._load_settings],
        )

        logging.debug("Initialised Window")

    def _on_checkbox_changed(self, var, combo):
        if var.get():
            combo.config(state="readonly")
        else:
            combo.config(state="disabled")

    @chainable
    def _run_chained(self, chain: List[Callable] = []) -> None:
        pass

    @chainable
    def _populate_serial_ports(self, chain: List[Callable] = []) -> None:
        # Populate the serial devices dropdown
        self.serial_ports = list_serial_ports()
        logging.info(self.serial_ports)

        if len(self.serial_ports) == 0:
            messagebox.showerror("Start-up Error!", "No serial ports found.")
            return

        self.serial_port_combo["values"] = self.serial_ports
        self.serial_port_var.set(value=self.serial_ports[-1])

    @chainable
    def _populate_video_devices(self, chain: List[Callable] = []) -> None:
        # Populate the video devices dropdown
        self.video_devices = CaptureDevice.getCameras()

        video_strings = [str(v) for v in self.video_devices]
        self.video_device_combo["values"] = video_strings
        logging.info("\n".join(video_strings))

        if len(self.video_devices) > 0:
            self.video_device_var.set(str(self.video_devices[0]))
        else:
            self.video_device_var.set("None found")
            self.video_device_combo.config(state="disabled")
            self.video_checkbox.config(state="disabled")
            self.video_var.set(False)
            messagebox.showerror("Start-up Error!", "No video devices found.")

    @chainable
    def _load_settings(self, chain: List[Callable] = []) -> None:
        config = configparser.ConfigParser()
        if not os.path.exists(self.CONFIG_FILE):
            return
        config.read(self.CONFIG_FILE)
        if "KVM" not in config:
            return
        kvm = config["KVM"]

        # Only set if present in current options
        if kvm.get("kb_backend", "") in self.kb_backends:
            self.kb_backend_var.set(kvm.get("kb_backend", ""))
        if kvm.get("serial_port") in self.serial_ports:
            self.serial_port_var.set(kvm.get("serial_port", ""))
        if kvm.get("video_device") is not None:
            try:
                idx = int(kvm.get("video_device", ""))
                if 0 <= idx < len(self.video_devices):
                    self.video_device_combo.current(idx)
            except (ValueError, TypeError):
                pass
        if kvm.get("baud_rate") and int(kvm.get("baud_rate", "")) in self.baud_rates:
            self.baud_rate_var.set(int(kvm.get("baud_rate", "")))

        # Booleans
        self.keyboard_var.set(kvm.get("keyboard", "True") == "True")
        self.video_var.set(kvm.get("video", "True") == "True")
        self.mouse_var.set(kvm.get("mouse", "True") == "True")
        self.window_var.set(kvm.get("windowed", "False") == "True")
        self.verbose_var.set(kvm.get("verbose", "False") == "True")
        logging.info("Settings loaded from INI file.")

    @chainable
    def _save_settings(self, chain: List[Callable] = []) -> None:
        config = configparser.ConfigParser()
        config["KVM"] = {
            "keyboard": str(self.keyboard_var.get()),
            "video": str(self.video_var.get()),
            "mouse": str(self.mouse_var.get()),
            "kb_backend": self.kb_backend_var.get(),
            "serial_port": self.serial_port_var.get(),
            "video_device": str(self.video_device_combo.current()),
            "baud_rate": str(self.baud_rate_var.get()),
            "windowed": str(self.window_var.get()),
            "verbose": str(self.verbose_var.get()),
        }
        with open(self.CONFIG_FILE, "w") as f:
            config.write(f)
        logging.info("Settings saved to INI file.")

    def on_start(self) -> None:
        # Disable Start button and set text to "Running..."
        self.start_button.config(text="Running...", state="disabled")
        self._save_settings()
        self.update_idletasks()

        # Launch KVM
        logging.info(
            f"""
            Starting Serial KVM with parameters:
                Camera:           {self.video_device_var.get()}
                Serial port:      {self.serial_port_var.get()} 
                Baud rate:        {self.baud_rate_var.get()}
                Keyboard backend: {self.kb_backend_var.get()}
                Keyboard:         {self.keyboard_var.get()}
                Video:            {self.video_var.get()}
                Mouse:            {self.mouse_var.get()}
                Windowed:         {self.window_var.get()}
                Verbose:          {self.verbose_var.get()}
            """
        )

        try:
            # Enormous threading issues. Need to call ./control.py as a subprocess
            # This is a workaround for crash:
            # [1] 47591 illegal hardware instruction ... python kvm.py
            env = os.environ.copy()
            env["PYTHONPATH"] = "."

            args = [
                sys.executable,
                os.path.join(os.path.dirname(__file__), "control.py"),
                str(self.serial_port_var.get()),
            ]
            if self.keyboard_var.get():
                args.append(f"--baud={str(self.baud_rate_var.get())}")
                args.append(f"--mode={str(self.kb_backend_var.get())}")
            if self.video_var.get():
                args.append("--video")
                camIndex = self.video_devices[self.video_device_combo.current()].index
                args.append(f"--camindex={camIndex}")
                if self.window_var.get():
                    args.append("--windowed")
            if self.mouse_var.get():
                args.append("--mouse")
            if self.verbose_var.get():
                args.append("--verbose")
            if not self.keyboard_var.get():
                args.append("--no-keyboard")

            logging.debug(f"Subprocess args: {args}")
            self.process = subprocess.Popen(args, env=env)

            # Start polling for process end
            self.after(500, self.check_subprocess)

        except Exception as e:
            logging.error(f"Exception occurred: {e}")
            messagebox.showerror("Error", f"An unexpected error occurred:\n{e}")
            self.on_exit()
        finally:
            logging.info("Done launching KVM")

    def check_subprocess(self):
        if self.process and self.process.poll() is None:
            # Still running, check again after 500ms
            self.after(500, self.check_subprocess)
        else:
            # Process ended, reset Start button
            self.start_button.config(text="Start", state="normal")
            self.process = None

    def stop_subprocess(self) -> None:
        # Terminate the control.py subprocess if it exists
        if hasattr(self, "process") and self.process is not None:
            try:
                logging.info("Stopping control.py subprocess")
                self.process.terminate()
                self.process.wait(timeout=2)  # Wait up to 2 seconds for subprocess to exit
            except subprocess.TimeoutExpired:
                logging.warning("Subprocess did not exit in time, killing it.")
                self.process.kill()
                self.process.wait()
            except Exception as e:
                logging.error(f"Failed to terminate control.py subprocess: {e}")
            self.process = None

    def on_exit(self) -> None:
        self.stop_subprocess()
        self.destroy()


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    app = KVMGui()
    app.mainloop()


if __name__ == "__main__":
    main()
