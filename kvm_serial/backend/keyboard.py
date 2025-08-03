import threading
from serial import Serial
from enum import Enum
from .inputhandler import InputHandler

try:
    from kvm_serial.backend.implementations.baseop import BaseOp
except ModuleNotFoundError:
    # Allow running as a script directly
    import os, sys

    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from implementations.baseop import BaseOp


class Mode(Enum):
    NONE = 0
    USB = 1
    PYNPUT = 2
    TTY = 3
    CURSES = 4


class KeyboardListener(InputHandler):
    def __init__(self, serial_port: Serial | str, mode: Mode | str = "pynput", baud: int = 9600):

        if isinstance(serial_port, str):
            self.serial_port = Serial(serial_port, baud)
        elif isinstance(serial_port, Serial):
            self.serial_port = serial_port

        if isinstance(mode, str):
            self.mode = Mode[mode.upper()]
        elif isinstance(mode, Mode):
            self.mode = mode

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
        # Select operation mode
        keyboard_handler: BaseOp

        if self.mode is Mode.NONE:
            return  # noop
        elif self.mode is Mode.USB:
            from backend.implementations.pyusbop import PyUSBOp

            keyboard_handler = PyUSBOp(self.serial_port)
        elif self.mode is Mode.PYNPUT:
            from backend.implementations.pynputop import PynputOp

            keyboard_handler = PynputOp(self.serial_port)
        elif self.mode is Mode.TTY:
            from backend.implementations.ttyop import TtyOp

            keyboard_handler = TtyOp(self.serial_port)
        elif self.mode is Mode.CURSES:
            from backend.implementations.cursesop import CursesOp

            keyboard_handler = CursesOp(self.serial_port)
        else:
            raise ValueError(f"Unknown keyboard mode: {self.mode!r}")

        keyboard_handler.run()


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
