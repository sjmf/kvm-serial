#!/usr/bin/env python
import logging
from pynput.mouse import Button, Listener
from serial import Serial
from screeninfo import get_monitors

from kvm_serial.backend.implementations.mouseop import MouseOp, MouseButton
from .inputhandler import InputHandler

logger = logging.getLogger(__name__)


class MouseListener(InputHandler):
    def __init__(self, serial, block=True):
        self.op = MouseOp(serial)

        self.thread = Listener(
            on_move=self.on_move,
            on_click=self.on_click,
            on_scroll=self.op.on_scroll,
            suppress=block,  # Suppress mouse events reaching the OS
        )

        self.pynput_button_mapping = {
            Button.unknown: MouseButton.RELEASE,
            Button.left: MouseButton.LEFT,
            Button.right: MouseButton.RIGHT,
            Button.middle: MouseButton.MIDDLE,
        }

        # Get screen dimensions
        monitor = get_monitors()[0]
        self._width = monitor.width
        self._height = monitor.height

        @property
        def width(self):
            return self._width

        @width.setter
        def width(self, value):
            self._width = value

        @property
        def height(self):
            return self._height

        @height.setter
        def height(self, value):
            self._height = value

    def run(self):
        self.thread.start()
        self.thread.join()

    def start(self):
        self.thread.start()

    def stop(self):
        self.thread.stop()
        self.thread.join()

    def on_move(self, x, y):
        return self.op.on_move(x, y, self._width, self._height)

    def on_click(self, x, y, button: Button, down):
        return self.op.on_click(x, y, self.pynput_button_mapping[button], down)

    def on_scroll(self, x, y, dx, dy):
        return self.op.on_scroll(x, y, dx, dy)


def mouse_main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("port", action="store")
    parser.add_argument(
        "-b",
        "--baud",
        help="Set baud rate for serial device",
        default=9600,
        type=int,
    )
    parser.add_argument(
        "-x",
        "--block",
        help="Block mouse input from host OS",
        action="store_true",
    )
    args = parser.parse_args()

    try:
        se = Serial(args.port, args.baud)
        ml = MouseListener(se, block=args.block)
        ml.start()
        while ml.thread.is_alive():
            ml.thread.join(timeout=0.1)
    except KeyboardInterrupt:
        logging.info("Stopping mouse listener...")
        ml.stop()


if __name__ == "__main__":
    mouse_main()
