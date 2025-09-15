# pynput implementation
import logging
from pynput.keyboard import Key, KeyCode, Listener
from kvm_serial.utils import ascii_to_scancode, merge_scancodes
from .baseop import BaseOp

logger = logging.getLogger(__name__)

MODIFIER_TO_VALUE = {
    Key.ctrl: 0x01,
    Key.ctrl_l: 0x01,
    Key.shift: 0x02,
    Key.shift_l: 0x02,
    Key.alt: 0x04,
    Key.alt_l: 0x04,
    Key.cmd: 0x08,
    Key.cmd_l: 0x08,
    Key.ctrl_r: 0x10,
    Key.shift_r: 0x20,
    Key.alt_r: 0x40,
    Key.alt_gr: 0x40,
    Key.cmd_r: 0x80,
}

KEYS_WITH_CODES = {
    Key.enter: 0x28,
    Key.esc: 0x29,
    Key.backspace: 0x2A,
    Key.tab: 0x2B,
    Key.space: 0x2C,
    Key.caps_lock: 0x39,
    Key.f1: 0x3A,
    Key.f2: 0x3B,
    Key.f3: 0x3C,
    Key.f4: 0x3D,
    Key.f5: 0x3E,
    Key.f6: 0x3F,
    Key.f7: 0x40,
    Key.f8: 0x41,
    Key.f9: 0x42,
    Key.f10: 0x43,
    Key.f11: 0x44,
    Key.f12: 0x45,
    Key.scroll_lock: 0x47,
    Key.pause: 0x48,
    Key.insert: 0x49,
    Key.home: 0x4A,
    Key.page_up: 0x4B,
    Key.delete: 0x4C,
    Key.end: 0x4D,
    Key.page_down: 0x4E,
    Key.right: 0x4F,
    Key.left: 0x50,
    Key.down: 0x51,
    Key.up: 0x52,
    Key.num_lock: 0x53,
    # Keypad seems to be missing from Pynput Key enum
    Key.media_play_pause: 0xE8,
    Key.media_previous: 0xEA,
    Key.media_next: 0xEB,
    Key.media_volume_up: 0xED,
    Key.media_volume_down: 0xEE,
    Key.media_volume_mute: 0xEF,
}


class PynputOp(BaseOp):
    @property
    def name(self):
        return "pynput"

    def __init__(self, serial_port):
        super().__init__(serial_port)
        self.modifier_map = {}
        # TODO: implement n-key rollover
        # self.key_rollover_map = {}

    def run(self):
        """
        Main method for control using pynput
        Starting point: https://stackoverflow.com/a/53210441/1681205
        :param serial_port:
        :return:
        """
        logging.info(
            "Using pynput operation mode.\n"
            "Can run as standard user, but Accessibility "
            "permission for input capture is required in Mac OSX.\n"
            "Paste not supported. Modifier keys supported.\n"
            "Input will continue in background without terminal focus.\n"
            "Press Ctrl+ESC or Ctrl+C to exit."
        )

        # Collect events until released
        with Listener(on_press=self.on_press, on_release=self.on_release) as listener:
            listener.join()

    def _nonalphanumeric_key_to_scancode(self, key: Key):
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

    def on_press(self, key: Key | KeyCode | None):
        """
        Function which runs when a key is pressed down
        :param key:
        :return:
        """
        scancode = [b for b in b"\x00" * 8]

        try:
            # Collect modifiers
            try:
                scancode = self._nonalphanumeric_key_to_scancode(key)  # type: ignore
            except KeyError as e:
                # This may be an alphanumeric instead
                scancode = ascii_to_scancode(key.char)  # type: ignore

            scan_modifiers = merge_scancodes(self.modifier_map.values())
            scancode = merge_scancodes([scan_modifiers, scancode])

        except AttributeError as e:
            logging.error("Key not found: " + str(e))

        # Merge keys in the modifier_keys_map and send over serial
        logging.debug(f"{scancode}\t({', '.join([hex(i) for i in scancode])})")
        self.hid_serial_out.send_scancode(bytes(scancode))

    def on_release(self, key):
        """
        Function which runs when a key is released
        :param key:
        :return:
        """
        # Send key release (null scancode)
        self.hid_serial_out.release()

        # Ctrl + ESC escape sequence will stop listener
        if key == Key.esc and Key.ctrl in self.modifier_map:
            raise Listener.StopException()

        try:
            self.modifier_map.pop(key)
        except KeyError:
            pass  # It might not be a modifier. Ask forgiveness, not permission


def main_pynput(serial_port):
    # For backwards compatibility
    return PynputOp(serial_port).run()
