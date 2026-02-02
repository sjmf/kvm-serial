import threading
from importlib import import_module
from serial import Serial
from enum import Enum
from .inputhandler import InputHandler

try:
    import_module("kvm_serial.backend.implementations")
except ModuleNotFoundError:
    # Allow running as a script directly: add parent to path so
    # _load_implementation's fallback "backend.implementations.*" resolves
    import os, sys

    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _load_implementation(module_name, class_name):
    """Load a handler class, trying package import first then script-mode fallback."""
    try:
        mod = import_module(f"kvm_serial.backend.implementations.{module_name}")
    except ModuleNotFoundError:
        mod = import_module(f"backend.implementations.{module_name}")
    return getattr(mod, class_name)


class Mode(Enum):
    NONE = 0
    USB = 1
    PYNPUT = 2
    TTY = 3
    CURSES = 4


_MODE_IMPLEMENTATIONS = {
    Mode.USB: ("pyusbop", "PyUSBOp"),
    Mode.PYNPUT: ("pynputop", "PynputOp"),
    Mode.TTY: ("ttyop", "TtyOp"),
    Mode.CURSES: ("cursesop", "CursesOp"),
}


class KeyboardListener(InputHandler):
    def __init__(
        self,
        serial_port: Serial | str,
        mode: Mode | str = "pynput",
        baud: int = 9600,
        layout: str = "en_GB",
    ):

        if isinstance(serial_port, str):
            self.serial_port = Serial(serial_port, baud)
        elif isinstance(serial_port, Serial):
            self.serial_port = serial_port

        if isinstance(mode, str):
            self.mode = Mode[mode.upper()]
        elif isinstance(mode, Mode):
            self.mode = mode

        self.layout = layout
        self.running = False
        self.thread = threading.Thread(target=self.run_keyboard)

    def run(self):
        self.thread.start()
        self.thread.join()

    def start(self):
        self.thread.start()

    def stop(self):
        self.running = False
        self.thread.join()

    def run_keyboard(self):
        if self.mode is Mode.NONE:
            return  # noop
        if self.mode not in _MODE_IMPLEMENTATIONS:
            raise ValueError(f"Unknown keyboard mode: {self.mode!r}")

        module_name, class_name = _MODE_IMPLEMENTATIONS[self.mode]
        Impl = _load_implementation(module_name, class_name)
        Impl(self.serial_port, layout=self.layout).run()


def keyboard_main():
    import sys
    import logging

    if len(sys.argv) < 4:
        print("keyboard.py [SERIAL_PORT] [MODE] [BAUD]")
        return sys.exit(1)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    keeb = KeyboardListener(sys.argv[1], mode=sys.argv[2], baud=int(sys.argv[3]))
    keeb.start()
    keeb.thread.join()


if __name__ == "__main__":
    keyboard_main()
