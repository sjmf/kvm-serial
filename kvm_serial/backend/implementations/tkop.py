# passthrough implementation
import logging
from kvm_serial.utils import ascii_to_scancode, merge_scancodes
from .baseop import BaseOp

import tkinter as tk
from tkinter import EventType

logger = logging.getLogger(__name__)

MODIFIER_TO_VALUE = {
    "Alt_L": 0x04,
    "Alt_R": 0x40,
    "Shift_L": 0x02,
    "Shift_R": 0x20,
    "Meta_L": 0x08,
    "Meta_R": 0x80,
    "Control_L": 0x01,
    "Control_L": 0x01,
    "Control_R": 0x10,
}

KEYS_WITH_CODES = {
    "Up": 0x52,
    "Down": 0x51,
    "Left": 0x50,
    "Right": 0x4F,
    "Home": 0x4A,
    "Prior": 0x4B,  # pageup
    "Delete": 0x4C,
    "End": 0x4D,
    "Next": 0x4E,  # pagedown
    "BackSpace": 0x2A,
    "F1": 0x3B,
    "F2": 0x3C,
    "F3": 0x3D,
    "F4": 0x3E,
    "F5": 0x3F,
    "F6": 0x40,
    "F7": 0x41,
    "F8": 0x42,
    "F9": 0x43,
    "F10": 0x44,
    "F11": 0x57,
    "F12": 0x58,
    "space": 0x2C,
    "Tab": 0x2B,
    "Return": 0x28,
    "Caps_Lock": 0x3A,
    # Key.media_play_pause: None,
    # Key.media_volume_mute: None,
    # Key.media_volume_down: None,
    # Key.media_volume_up: None,
    # Key.media_previous: None,
    # Key.media_next: None,
    "Escape": 0x29,
}


class TkOp(BaseOp):
    """
    Tk operation mode: parse Tk keys to hid_serial_out
    """

    @property
    def name(self):
        return "tk"

    def __init__(self, serial_port):
        super().__init__(serial_port)
        self.modifier_map = {}

    def run(self):
        raise Exception("Run not supported for Tk mode. Call _parse_key from Tk window")

    def parse_key(self, event: tk.Event) -> bool:
        key = event.char
        if key == "":
            key = event.keysym
        if event.type == EventType.KeyPress:
            self._on_press(key)
        elif event.type == EventType.KeyRelease:
            self._on_release(key)

        return True

    def _nonalphanumeric_key_to_scancode(self, key: str):
        """
        Converts a non-alphanumeric key to its corresponding scancode representation.

        Args:
            key (Key): The non-alphanumeric key to convert.
        Returns:
            list: A list of 8 bytes representing the scancode.
        Raises:
            KeyError: If the provided key is not found in MODIFIER_TO_VALUE or KEYS_WITH_CODES.
        """
        scancode = [b for b in b"\x00" * 8]

        if key in MODIFIER_TO_VALUE:
            value = MODIFIER_TO_VALUE[key]
            scancode[0] = value
            self.modifier_map[key] = scancode
        else:
            value = KEYS_WITH_CODES[key]
            scancode[2] = value

        return scancode

    def _on_press(self, key: str):
        """
        Function which runs when a key is pressed down
        :param key:
        :return:
        """
        scancode = [b for b in b"\x00" * 8]

        try:
            # Collect modifiers
            try:
                scancode = self._nonalphanumeric_key_to_scancode(key)
            except KeyError as e:
                # This may be an alphanumeric instead
                scancode = ascii_to_scancode(key)

            scan_modifiers = merge_scancodes(self.modifier_map.values())
            scancode = merge_scancodes([scan_modifiers, scancode])

        except AttributeError as e:
            logging.error("Key not found: " + str(e))

        # Merge keys in the modifier_keys_map and send over serial
        logging.debug(f"{scancode}\t({', '.join([hex(i) for i in scancode])})")
        self.hid_serial_out.send_scancode(bytes(scancode))

    def _on_release(self, key: str):
        """
        Function which runs when a key is released
        :param key:
        :return:
        """
        try:
            self.modifier_map.pop(key)
        except KeyError:
            pass  # It might not be a modifier. Ask forgiveness, not permission

        # Send key release (null scancode) layered with remaining modifiers
        scancode = [b for b in b"\x00" * 8]
        scan_modifiers = merge_scancodes(self.modifier_map.values())
        scancode = merge_scancodes([scan_modifiers, scancode])
        self.hid_serial_out.send_scancode(bytes(scancode))
