import sys
import logging
from abc import ABC, abstractmethod
from serial import Serial, SerialException
from serial.tools import list_ports

# termios is Unix-only, not available on Windows
try:
    import termios
except ImportError:
    termios = None


class DataComm(ABC):
    """
    Abstract base for protocol implementations that drive a UART-to-USB-HID
    bridge chip from kvm-serial. Subclasses implement the wire framing for a
    specific chip family (CH9329, CH9350L, ...).

    Callers interact through the high-level methods below; concrete subclasses
    handle packet construction and any chip-specific state (pairing handshake,
    descriptor announce, working-state selection, etc.).
    """

    SCANCODE_LENGTH = 8

    def __init__(self, port: Serial):
        self.port = port

    @abstractmethod
    def send_scancode(self, scancode: bytes) -> bool:
        """Send an 8-byte USB HID boot-protocol keyboard report."""

    @abstractmethod
    def release(self) -> bool:
        """Send an empty (all keys released) keyboard report."""

    @abstractmethod
    def send_mouse_absolute(
        self, buttons: int, x: int, y: int, width: int, height: int, wheel: int = 0
    ) -> bool:
        """Send an absolute-positioning mouse report.

        x, y are in source pixel coordinates; width, height bound the source
        surface so subclasses can scale into the chip's native coordinate
        space (CH9329: 0..4095; CH9350 state 3/4: 0..0xFFFF).
        """

    @abstractmethod
    def send_mouse_relative(self, buttons: int, dx: int, dy: int, wheel: int = 0) -> bool:
        """Send a relative-motion mouse report.

        dx, dy, wheel are signed 8-bit deltas (-127..+127); callers pass 0 for
        unused fields (e.g. button-only events or pure scroll events).
        """


def list_serial_ports():
    """
    List available serial port names on Windows, Mac, and Linux.
    Uses pyserial's list_ports API for cross-platform enumeration.
    """
    result = []

    # Use pyserial's list_ports to enumerate actual available ports
    ports_info = list_ports.comports()

    for port_info in ports_info:
        port = port_info.device
        try:
            # Verify we can open the port - only import if working
            s = Serial(port)
            s.close()
            result.append(port)
        except (OSError, ImportError, FileNotFoundError, SerialException) as e:
            # Don't append ports we can't open
            logging.error(f"{port} could not be opened: {e}")
        except Exception as e:
            # Handle termios.error on Unix systems (termios is None on Windows)
            if termios and type(e).__name__ == "error" and type(e).__module__ == "termios":
                logging.warning(f"{port} didn't open at 9600 baud, but a different rate may work!")
                result.append(port)
            else:
                raise e

    # On macOS, prioritize cu.* ports over usbserial
    if sys.platform.startswith("darwin"):
        # On macOS, /dev/tty.* are "call-in" devices (used for incoming connections, e.g., modems waiting for a call),
        # and /dev/cu.* are "call-out" devices (used for outgoing connections, e.g., when your program initiates a connection).
        # /dev/cu.* is usually preferred for initiating connections from user programs.
        usbserial_ports = [p for p in result if "cu.usbserial-" in p]
        # Move cu.usbserial-xxxxxx ports to the start of the list
        other_ports = [p for p in result if "cu.usbserial-" not in p]
        result = other_ports + usbserial_ports

    return result
