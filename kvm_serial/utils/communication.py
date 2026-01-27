import sys
import logging
from serial import Serial, SerialException
from serial.tools import list_ports

# termios is Unix-only, not available on Windows
try:
    import termios
except ImportError:
    termios = None


class DataComm:
    """
    DataComm class based on beijixiaohu/ch9329Comm module; simplified and commented
    Original: https://github.com/beijixiaohu/CH9329_COMM/ / https://pypi.org/project/ch9329Comm/
    """

    SCANCODE_LENGTH = 8

    def __init__(self, port: Serial):
        self.port = port

    def send(
        self,
        data: bytes,
        head: bytes = b"\x57\xab",
        addr: bytes = b"\x00",
        cmd: bytes = b"\x02",
    ) -> bool:
        """
        Convert input to data packet and send command over serial.

        Args:
            data: data packet to encapsulate and send
            head: Packet header
            addr: Address
            cmd: Data command (0x02 = Keyboard; 0x04 = Absolute mouse; 0x05 = Relative mouse)
        Returns:
            True if successful, otherwise throws an exception
        """
        # Check inputs
        if len(head) != 2 or len(addr) != 1 or len(cmd) != 1:
            raise ValueError("DataComm packet header MUST have: header 2b; addr 1b; cmd 1b")

        length = len(data).to_bytes(1, "little")

        # Calculate checksum
        checksum = (
            sum(head)
            + int.from_bytes(addr, "big")
            + int.from_bytes(cmd, "big")
            + int.from_bytes(length, "big")
            + sum(data)
        ) % 256

        # Build data packet
        packet = head + addr + cmd + length + data + bytes([checksum])

        # Write command to serial port
        self.port.write(packet)

        return True

    def send_scancode(self, scancode: bytes) -> bool:
        """
        Send function for use with scancodes
        Does additional length checking and returns False if long

        Args:
            scancode: An 8-byte scancode representing keyboard state
        Returns:
            bool: True if successful, False otherwise
        """
        if len(scancode) < self.SCANCODE_LENGTH:
            return False

        return self.send(scancode)

    def release(self):
        """
        Release the button.

        Return:
            bool: True if successful
        """
        return self.send(b"\x00" * self.SCANCODE_LENGTH)


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
