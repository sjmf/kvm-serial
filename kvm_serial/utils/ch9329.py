"""
CH9329 UART-to-USB-HID bridge protocol implementation.

The CH9329 is a host-driven, command-style chip: this module sends framed
commands over the serial port and the chip translates them into USB HID
reports on the target side. Frame layout:

    header(2B: 0x57 0xAB) + addr(1B) + cmd(1B) + len(1B) + data + checksum(1B)
"""

from kvm_serial.utils.communication import DataComm


class CH9329Comm(DataComm):
    """
    CH9329 UART-to-USB-HID bridge.

    Originally derived from beijixiaohu/ch9329Comm:
        https://github.com/beijixiaohu/CH9329_COMM/
    """

    def send(
        self,
        data: bytes,
        head: bytes = b"\x57\xab",
        addr: bytes = b"\x00",
        cmd: bytes = b"\x02",
    ) -> bool:
        """
        Build a CH9329 data packet and write it to the serial port.

        Args:
            data: payload bytes to encapsulate and send
            head: Packet header (2 bytes)
            addr: address byte
            cmd: Data command byte (0x02 = Keyboard; 0x04 = Absolute mouse; 0x05 = Relative mouse) Returns:
        Returns:
            True if successful, otherwise throws an exception
        """
        # Check inputs
        if len(head) != 2 or len(addr) != 1 or len(cmd) != 1:
            raise ValueError("CH9329 packet header MUST have: header 2b; addr 1b; cmd 1b")

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
        Send an 8-byte HID keyboard scancode.
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
        Sends the all-zeros scancode (release all keys).

        Return:
            bool: True if successful
        """
        return self.send(b"\x00" * self.SCANCODE_LENGTH)

    def send_mouse_absolute(
        self, buttons: int, x: int, y: int, width: int, height: int, wheel: int = 0
    ) -> bool:
        """
        Build and send a CH9329 absolute mouse report (cmd=0x04).
        Wire payload (7 bytes): direction(0x02) + buttons + xL xH + yL yH + wheel.
        Source x/y are scaled into the chip's 12-bit absolute space (0..4095).
        """
        # Scale source coordinates into CH9329's 12-bit absolute space.
        dx = int((4096 * x) // max(1, width))
        dy = int((4096 * y) // max(1, height))

        # Wrap negatives (e.g. multi-monitor setups where x or y can be < 0).
        if dx < 0:
            dx = abs(4096 + dx)
        if dy < 0:
            dy = abs(4096 + dy)

        data = bytearray(b"\x02")  # absolute-coordinate marker
        data += bytes([buttons & 0xFF])

        data += dx.to_bytes(2, "little")
        data += dy.to_bytes(2, "little")

        data += _signed_byte(wheel)
        return self.send(bytes(data), cmd=b"\x04")

    def send_mouse_relative(self, buttons: int, dx: int, dy: int, wheel: int = 0) -> bool:
        """
        Build and send a CH9329 relative mouse report (cmd=0x05).
        Wire payload (5 bytes): direction(0x01) + buttons + dx + dy + wheel.
        dx, dy, wheel are 1-byte signed values (-127..+127).
        """
        data = bytearray(b"\x01")  # relative-coordinate marker
        data += bytes([buttons & 0xFF])
        data += _signed_byte(dx)
        data += _signed_byte(dy)
        data += _signed_byte(wheel)
        return self.send(bytes(data), cmd=b"\x05")


def _signed_byte(value: int) -> bytes:
    """Clamp an int to the signed 8-bit range and return its 1-byte encoding."""
    clamped = max(-127, min(127, value))
    return clamped.to_bytes(1, "big", signed=True)
