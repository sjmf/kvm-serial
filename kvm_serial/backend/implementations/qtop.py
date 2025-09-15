# Qt Keyboard input implementation
import sys
import logging
from typing import cast
from kvm_serial.utils import ascii_to_scancode, merge_scancodes
from .baseop import BaseOp

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeyEvent

logger = logging.getLogger(__name__)

# Qt modifier keys to HID modifier values
MODIFIER_TO_VALUE = {
    Qt.Key.Key_Control: 0x01,
    Qt.Key.Key_Shift: 0x02,
    Qt.Key.Key_Alt: 0x04,
    Qt.Key.Key_Super_L: 0x08,
    Qt.Key.Key_Meta: 0x08,
    # RControl not implemented in Qt: 0x10
    # RShift not implemented in Qt: 0x20
    Qt.Key.Key_AltGr: 0x40,
    Qt.Key.Key_Super_R: 0x80,
}

# Fix for macOS: swap Control and Meta (Command) keys
if sys.platform == "darwin":
    MODIFIER_TO_VALUE[Qt.Key.Key_Control], MODIFIER_TO_VALUE[Qt.Key.Key_Meta] = (
        MODIFIER_TO_VALUE[Qt.Key.Key_Meta],
        MODIFIER_TO_VALUE[Qt.Key.Key_Control],
    )

# Qt special keys to USB HID scan codes
# NB: USB HID Scancodes DIFFER from PS/2 scan codes!
KEYS_WITH_CODES = {
    ## Alphanumeric keys not listed - handled by character handling
    # Basic keys
    Qt.Key.Key_Enter: 0x28,
    Qt.Key.Key_Return: 0x28,
    Qt.Key.Key_Escape: 0x29,
    Qt.Key.Key_Backspace: 0x2A,
    Qt.Key.Key_Tab: 0x2B,
    Qt.Key.Key_Space: 0x2C,
    # 0x2D-0x38 are punctuation and symbols, handled by character handling
    # - = [ ] \ # ; ' ` , . /
    # Lock keys and function keys
    Qt.Key.Key_CapsLock: 0x39,
    Qt.Key.Key_F1: 0x3A,
    Qt.Key.Key_F2: 0x3B,
    Qt.Key.Key_F3: 0x3C,
    Qt.Key.Key_F4: 0x3D,
    Qt.Key.Key_F5: 0x3E,
    Qt.Key.Key_F6: 0x3F,
    Qt.Key.Key_F7: 0x40,
    Qt.Key.Key_F8: 0x41,
    Qt.Key.Key_F9: 0x42,
    Qt.Key.Key_F10: 0x43,
    Qt.Key.Key_F11: 0x44,
    Qt.Key.Key_F12: 0x45,
    # System and navigation keys
    Qt.Key.Key_Print: 0x46,
    Qt.Key.Key_SysReq: 0x46,
    Qt.Key.Key_ScrollLock: 0x47,
    Qt.Key.Key_Pause: 0x48,
    Qt.Key.Key_Insert: 0x49,  # 0x1000006
    0x1000058: 0x49,  # Also appears to be "Insert"
    Qt.Key.Key_Home: 0x4A,
    Qt.Key.Key_PageUp: 0x4B,
    Qt.Key.Key_Delete: 0x4C,
    Qt.Key.Key_End: 0x4D,
    Qt.Key.Key_PageDown: 0x4E,
    Qt.Key.Key_Right: 0x4F,
    Qt.Key.Key_Left: 0x50,
    Qt.Key.Key_Down: 0x51,
    Qt.Key.Key_Up: 0x52,
    Qt.Key.Key_NumLock: 0x53,
    # Additional keys
    Qt.Key.Key_Menu: 0x65,
    # Numpad keys
    Qt.Key.Key_Slash: 0x54,
    Qt.Key.Key_Asterisk: 0x55,
    Qt.Key.Key_Minus: 0x56,
    Qt.Key.Key_Plus: 0x57,
    Qt.Key.Key_Return: 0x58,
    Qt.Key.Key_1: 0x59,
    Qt.Key.Key_2: 0x5A,
    Qt.Key.Key_3: 0x5B,
    Qt.Key.Key_4: 0x5C,
    Qt.Key.Key_5: 0x5D,
    Qt.Key.Key_6: 0x5E,
    Qt.Key.Key_7: 0x5F,
    Qt.Key.Key_8: 0x60,
    Qt.Key.Key_9: 0x61,
    Qt.Key.Key_0: 0x62,
    Qt.Key.Key_Period: 0x63,
}


class QtOp(BaseOp):
    """
    Qt operation mode: parse Qt QKeyEvents to hid_serial_out
    """

    @property
    def name(self):
        return "qt"

    def __init__(self, serial_port):
        super().__init__(serial_port)
        self.modifier_map = {}

    def run(self):
        raise Exception("Run not supported for Qt mode. Call parse_key from Qt window")

    def parse_key(self, event: QKeyEvent) -> bool:
        """
        Parse a QKeyEvent and convert it to the appropriate scancode

        Args:
            event: QKeyEvent from Qt key press/release

        Returns:
            bool: True if key was processed successfully
        """
        # Determine if this is a press or release
        if event.type() == QKeyEvent.Type.KeyPress:
            self._on_press(event)
        elif event.type() == QKeyEvent.Type.KeyRelease:
            self._on_release(event)
        else:
            logging.warning(f"Got unknown event of kind {type(event)}. Ignoring.")
            return False

        return True

    def _nonalphanumeric_key_to_scancode(self, qt_key: Qt.Key):
        """
        Converts a non-alphanumeric Qt key to its corresponding scancode representation.

        Args:
            qt_key (int): The Qt key code to convert.
        Returns:
            list: A list of 8 bytes representing the scancode.
        Raises:
            KeyError: If the provided key is not found in MODIFIER_TO_VALUE or KEYS_WITH_CODES.
        """
        scancode = [b for b in b"\x00" * 8]

        if qt_key in MODIFIER_TO_VALUE:
            value = MODIFIER_TO_VALUE[int(qt_key)]
            scancode[0] = value
            self.modifier_map[qt_key] = scancode
        else:
            value = KEYS_WITH_CODES[qt_key]
            scancode[2] = value

        return scancode

    def _on_press(self, event: QKeyEvent):
        """
        Function which runs when a key is pressed down

        Args:
            event (QKeyEvent): Qt key event for the pressed key
        """
        qt_key = cast(Qt.Key, event.key())
        scancode = [b for b in b"\x00" * 8]

        try:
            # Try non-alphanumeric keys first
            try:
                scancode = self._nonalphanumeric_key_to_scancode(qt_key)
            except KeyError:
                # This may be an alphanumeric character instead
                text = event.text()
                if len(text) == 0:
                    # Backup method as event.text() doesn't return for key combos
                    try:
                        text = chr(qt_key).lower()
                    except ValueError:
                        logger.warning(f"Potentially unhandled key: 0x{qt_key:x}")

                if text and len(text) == 1:
                    scancode = ascii_to_scancode(text)
                else:
                    # Unmapped key - log and skip
                    logger.warning(f"Unmapped Qt key: {qt_key} (0x{qt_key:x}) [0b{qt_key:b}]")
                    return

            scan_modifiers = merge_scancodes(self.modifier_map.values())
            scancode = merge_scancodes([scan_modifiers, scancode])

        except AttributeError as e:
            logging.error("Key not found: " + str(e))
            return

        # Send scancode over serial
        logging.debug(f"{scancode}\t({', '.join([hex(i) for i in scancode])})\t0x{int(qt_key):x}")
        self.hid_serial_out.send_scancode(bytes(scancode))

    def _on_release(self, event: QKeyEvent):
        """
        Function which runs when a key is released

        Args:
            event (QKeyEvent): Qt key event for the released key
        """
        qt_key = event.key()

        try:
            self.modifier_map.pop(qt_key)
        except KeyError:
            pass  # It might not be a modifier. Ask forgiveness, not permission

        # Send key release (null scancode) layered with remaining modifiers
        scancode = [b for b in b"\x00" * 8]
        scan_modifiers = merge_scancodes(self.modifier_map.values())
        scancode = merge_scancodes([scan_modifiers, scancode])
        logging.debug(f"{scancode}\t({', '.join([hex(i) for i in scancode])})")
        self.hid_serial_out.send_scancode(bytes(scancode))
