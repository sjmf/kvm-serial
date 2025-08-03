# mouse implementation
import logging
from enum import Enum
from .baseop import BaseOp

logger = logging.getLogger(__name__)


class MouseButton(Enum):
    """
    Represents mouse buttons.
    """

    RELEASE = b"\x00"  # Release
    LEFT = b"\x01"  # Left click
    RIGHT = b"\x02"  # Right click
    MIDDLE = b"\x04"  # Centre Click


class MouseOp(BaseOp):
    """
    Mouse operation mode: handle mouse movement
    """

    @property
    def name(self):
        return "mouse"

    def run(self):
        raise Exception("Run not supported for MouseOp mode. Call from handler class")

    def on_move(self, x, y, width, height):
        # Prepare data payload
        data = bytearray(b"\x02\x00")  # Absolute coordinates (0x02); No mouse buttons (0x0)

        # Scale coordinates to device range
        dx = int((4096 * x) // width)
        dy = int((4096 * y) // height)

        # Handle negative coordinates (e.g., dual monitor setups)
        if dx < 0:
            dx = abs(4096 + dx)
        if dy < 0:
            dy = abs(4096 + dy)

        data += dx.to_bytes(2, "little")
        data += dy.to_bytes(2, "little")

        # Ensure data is exactly 7 bytes for abs move
        data = data[:7] if len(data) > 7 else data.ljust(7, b"\x00")

        self.hid_serial_out.send(data, cmd=b"\x04")
        logging.debug(f"Mouse moved to ({x}, {y})")

        return True

    def on_click(self, x, y, button: MouseButton, down):
        data = bytearray(b"\x01")  # Relative coordinates (0x01)
        data += button.value if down else b"\x00"  # Mouse button
        data += b"\x00\x00"  # Rel. mouse position x/y coordinate (2 bytes 0x0)
        data += b"\x00"  # pad to length 5

        self.hid_serial_out.send(data, cmd=b"\x05")

        logging.debug(f"Mouse click at ({x}, {y}) with {button} (down={down})")
        return True  # Suppress the click event (pynput)

    def on_scroll(self, x, y, dx, dy):
        data = bytearray(b"\x01")  # Relative coordinates (0x01)
        data += dx.to_bytes(2, "big", signed=True)
        data += dy.to_bytes(2, "big", signed=True)

        self.hid_serial_out.send(data, cmd=b"\x05")

        logging.debug(f"Mouse scroll ({x}, {y}, {dx}, {dy})")
        return True
