# tty implementation
import sys
import tty
import termios
import logging
import time
from kvm_serial.utils import ascii_to_scancode
from .baseop import BaseOp

logger = logging.getLogger(__name__)


class TtyOp(BaseOp):
    """
    TTY operation mode: basic mode supporting pasted text, no modifier keys.

    Implementation for control using tty (can run as local user)
    This mode may be useful as a fallback if keyboard detection fails.

    TTY operation mode is a very basic mode which can support pasted text, but
    has no support for modifier keys, which will be parsed by the host and NOT
    passed through to the CH9329 HID keyboard
    """

    @property
    def name(self):
        return "tty"

    def run(self):
        logging.info(
            "Using tty operation mode.\n"
            "Paste supported. Modifier keys not supported.\n"
            "Ctrl+C will exit. Console must be focused to input."
        )

        try:
            tty.setcbreak(sys.stdin)
            while self._parse_key():
                time.sleep(0.1)
        except termios.error as e:
            raise Exception("Run this app from a terminal!") from e

    def _parse_key(self) -> bool:
        ascii_val = sys.stdin.read(1)
        scancode = ascii_to_scancode(ascii_val)
        print(ascii_val, end="", flush=True)
        logging.debug(scancode)

        self.hid_serial_out.send_scancode(bytes(scancode))
        self.hid_serial_out.release()

        return True


# For backward compatibility
def main_tty(serial_port):
    return TtyOp(serial_port).run()
