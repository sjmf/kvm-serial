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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Bitmask of currently-held mouse buttons. Updated by on_click and
        # carried through on_move/on_scroll so that drags (button held while
        # moving) preserve the held button on the target. Without this every
        # move event during a drag would clear the button bit and the target
        # would see release-on-first-motion.
        self._buttons = 0

    @property
    def name(self):
        return "mouse"

    def run(self):
        raise Exception("Run not supported for MouseOp mode. Call from handler class")

    def on_move(self, x, y, width, height):
        # Carry the current held-button state so drags work.
        self.hid_serial_out.send_mouse_absolute(self._buttons, x, y, width, height)
        logging.debug(f"Mouse moved to ({x}, {y}) buttons={self._buttons:#x}")

        return True

    def on_click(self, x, y, button: MouseButton, down):
        # Update held-button bitmask: set on press, clear on release. Other
        # buttons remain held -- supports e.g. middle-click held while
        # left-click is pressed.
        bit = button.value[0]
        if down:
            self._buttons |= bit
        else:
            self._buttons &= ~bit & 0xFF
        # Click events ride the relative-mouse path with zero motion deltas.
        self.hid_serial_out.send_mouse_relative(self._buttons, 0, 0, 0)
        logging.debug(
            f"Mouse click at ({x}, {y}) with {button} (down={down}) "
            f"-> buttons={self._buttons:#x}"
        )
        return True  # Suppress the click event (pynput)

    def on_scroll(self, x, y, dx, dy):
        # CH9329 has a single wheel axis (vertical); horizontal dx is dropped.
        # Clamping happens in the comm layer. Carry held-button state so that
        # button-held-while-scrolling is preserved (uncommon but valid).
        self.hid_serial_out.send_mouse_relative(self._buttons, 0, 0, int(dy))
        logging.debug(f"Mouse scroll ({x}, {y}, {dx}, {dy}) buttons={self._buttons:#x}")
        return True
