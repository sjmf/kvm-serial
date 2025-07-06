import sys
import glob
import termios
import logging
from serial import Serial, SerialException


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
    List serial port names on Windows, Mac, and Linux.
    """
    if sys.platform.startswith("win"):
        ports = [f"COM{i + 1}" for i in range(256)]
    elif sys.platform.startswith("linux") or sys.platform.startswith("cygwin"):
        ports = glob.glob("/dev/tty[A-Za-z]*")
    elif sys.platform.startswith("darwin"):
        # On macOS, /dev/tty.* are "call-in" devices (used for incoming connections, e.g., modems waiting for a call),
        # and /dev/cu.* are "call-out" devices (used for outgoing connections, e.g., when your program initiates a connection).
        # /dev/cu.* is usually preferred for initiating connections from user programs.
        ports = glob.glob("/dev/cu.*")
        # Move cu.usbserial-xxxxxx ports to the end of the list
        usbserial_ports = [p for p in ports if "cu.usbserial-" in p]
        other_ports = [p for p in ports if "cu.usbserial-" not in p]
        ports = other_ports + usbserial_ports
    else:
        raise EnvironmentError("Unsupported platform")

    result = []
    for port in ports:
        try:
            # Only import if working
            s = Serial(port)
            s.close()
            result.append(port)
        except (OSError, ImportError, FileNotFoundError, SerialException) as e:
            # Don't append ports we can't open
            logging.error(f"{port} could not be opened: {e}")
        except termios.error as e:
            logging.warning(f"{port} didn't open at 9600 baud, but a different rate may work!")
            result.append(port)
        except Exception as e:
            raise e
    return result
