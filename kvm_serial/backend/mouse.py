#!/usr/bin/env python
import logging
from pynput.mouse import Button, Listener
from serial import Serial
from screeninfo import get_monitors

from kvm_serial.utils.communication import DataComm
from .inputhandler import InputHandler

logger = logging.getLogger(__name__)


class MouseListener(InputHandler):
    def __init__(self, serial, block=True):
        self.thread = Listener(
            on_move=self.on_move,
            on_click=self.on_click,
            on_scroll=self.on_scroll,
            suppress=block,  # Suppress mouse events reaching the OS
        )
        self.comm = DataComm(serial)

        # Mouse movement control character
        self.control_chars = {
            "NU": b"\x00",  # Release
            Button.left: b"\x01",  # Left click
            Button.right: b"\x02",  # Right click
            Button.middle: b"\x04",  # Centre Click
        }

        # Get screen dimensions
        monitor = get_monitors()[0]
        self.width = monitor.width
        self.height = monitor.height

    def run(self):
        self.thread.start()
        self.thread.join()

    def start(self):
        self.thread.start()

    def stop(self):
        self.thread.stop()
        self.thread.join()

    def on_move(self, x, y):
        # Prepare data payload
        data = bytearray(b"\x02\x00")  # Absolute coordinates (0x02); No mouse buttons (0x0)

        # Scale coordinates to device range
        dx = int((4096 * x) // self.width)
        dy = int((4096 * y) // self.height)

        # Handle negative coordinates (e.g., dual monitor setups)
        if dx < 0:
            dx = abs(4096 + dx)
        if dy < 0:
            dy = abs(4096 + dy)

        data += dx.to_bytes(2, "little")
        data += dy.to_bytes(2, "little")

        # Ensure data is exactly 7 bytes for abs move
        data = data[:7] if len(data) > 7 else data.ljust(7, b"\x00")

        self.comm.send(data, cmd=b"\x04")
        logging.debug(f"Mouse moved to ({x}, {y})")

        return True

    def on_click(self, x, y, button: Button, down):
        data = bytearray(b"\x01")  # Relative coordinates (0x01)
        data += self.control_chars[button] if down else b"\x00"  # Mouse button
        data += b"\x00\x00"  # Rel. mouse position x/y coordinate (2 bytes 0x0)
        data += b"\x00"  # pad to length 5

        self.comm.send(data, cmd=b"\x05")

        logging.debug(f"Mouse click at ({x}, {y}) with {button} (down={down}) - suppressed.")
        return True  # Suppress the click event

    def on_scroll(self, x, y, dx, dy):
        data = bytearray(b"\x01")  # Relative coordinates (0x01)
        data += dx.to_bytes(2, "big", signed=True)
        data += dy.to_bytes(2, "big", signed=True)

        self.comm.send(data, cmd=b"\x05")

        logging.debug(f"Mouse scroll ({x}, {y}, {dx}, {dy})")
        return True


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
