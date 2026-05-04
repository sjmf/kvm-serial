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
        # No buttons, no wheel — pure positional update.
        self.hid_serial_out.send_mouse_absolute(0, x, y, width, height)
        logging.debug(f"Mouse moved to ({x}, {y})")

        return True

    def on_click(self, x, y, button: MouseButton, down):
        # Click events ride the relative-mouse path with zero motion deltas.
        # MouseButton enum values are single-byte bitmasks; release decays to 0.
        button_byte = button.value[0] if down else 0
        self.hid_serial_out.send_mouse_relative(button_byte, 0, 0, 0)
        logging.debug(f"Mouse click at ({x}, {y}) with {button} (down={down})")
        return True  # Suppress the click event (pynput)

    def on_scroll(self, x, y, dx, dy):
        # CH9329 has a single wheel axis (vertical); horizontal dx is dropped.
        # Clamping happens in the comm layer.
        self.hid_serial_out.send_mouse_relative(0, 0, 0, int(dy))
        logging.debug(f"Mouse scroll ({x}, {y}, {dx}, {dy})")
        return True
