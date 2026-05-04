"""
CH9350L UART-to-USB-HID extender protocol implementation.

The CH9350L is a paired-chip extender: a *lower computer* (LC, USB host;
reads keyboard/mouse) talks to an *upper computer* (UC, USB device; presents
HID to the target PC) over UART. kvm-serial drives the UART side, replacing
the LC in software, so the CH9350L on the other end of the link enumerates
USB HID devices on the target.

This module currently implements working states 2, 3, and 4 — the
"simple" modes selected by the chip's S0/S1 dipswitches. State 0/1
(paired mode with descriptor announcement and PID-ack handshake) is on
the roadmap; see issue #13 and docs/CH9350L_PROTO.md.

Working states (set on the UC's S0/S1 dipswitches):
    state 2: BIOS keyboard + relative mouse
             — legacy BIOS / UEFI CSM compatible
    state 3: BIOS keyboard + absolute mouse
             — modern OS, single monitor
    state 4: BIOS keyboard + absolute mouse + HID Digitizers
             — modern OS, multi-monitor
"""

from kvm_serial.utils.communication import DataComm

HEADER = b"\x57\xab"


class CH9350Comm(DataComm):
    """
    CH9350L extender, simple-mode (states 2/3/4) implementation.

    Frames carry no SER, no checksum, no per-frame counter — much simpler
    than CH9329's command framing. Each LC→UC frame is a fixed shape per
    its leading command byte:
        0x01: keyboard       — 11 bytes (HEADER + 0x01 + 8-byte HID report)
        0x02: relative mouse —  7 bytes (HEADER + 0x02 + btn dx dy wheel)
        0x04: absolute mouse — 10 bytes (HEADER + 0x04 + 0x01 + btn xL xH yL yH wheel)

    The chosen state determines which mouse path is active on the wire.
    State 2 only emits 0x02; states 3/4 only emit 0x04. The two state-3/4
    UC variants are wire-identical from the LC's perspective; the dipswitch
    selects what HID descriptor the UC advertises to the target host (HID
    Mouse vs HID Digitizers).
    """

    STATE_2 = 2
    STATE_3 = 3
    STATE_4 = 4
    SUPPORTED_STATES = (STATE_2, STATE_3, STATE_4)

    def __init__(self, port, state: int = STATE_2):
        if state not in self.SUPPORTED_STATES:
            raise ValueError(
                f"CH9350Comm currently supports states {self.SUPPORTED_STATES}; "
                f"state 0/1 (paired mode) is not yet implemented"
            )
        super().__init__(port)
        self.state = state
        # Cursor-position bookkeeping. State 3/4 needs the last absolute
        # position so that button/scroll events (which arrive via
        # send_mouse_relative with zero motion) can re-emit it with the new
        # button/wheel state. State 2 uses the previous position to translate
        # send_mouse_absolute calls into on-the-wire relative deltas.
        self._last_x = 0
        self._last_y = 0
        self._last_width = 1
        self._last_height = 1

    def send_scancode(self, scancode: bytes) -> bool:
        """
        Send an 8-byte HID boot-protocol keyboard report.
        Wire frame (11 bytes): HEADER + 0x01 + [mod rsvd k0..k5].

        Identical across states 2/3/4 — the keyboard descriptor on the UC is
        a BIOS keyboard in all three modes; the difference between them is
        purely in mouse semantics.
        """
        if len(scancode) < self.SCANCODE_LENGTH:
            return False
        self.port.write(HEADER + b"\x01" + scancode[: self.SCANCODE_LENGTH])
        return True

    def release(self) -> bool:
        """Release all keys (send the all-zeros HID report)."""
        return self.send_scancode(b"\x00" * self.SCANCODE_LENGTH)

    def send_mouse_absolute(
        self, buttons: int, x: int, y: int, width: int, height: int, wheel: int = 0
    ) -> bool:
        """
        Emit a positional update.

        States 3/4: scale pixel coordinates into the chip's 16-bit absolute
        space and emit a 0x04 frame.
        State 2: no absolute-mouse path exists on the wire. Translate to a
        relative delta from the previous absolute call and emit a 0x02
        frame instead. This means a fresh-from-origin pointer move clamps
        each step to ±127 px (the signed-byte range), but pynput's frequent
        event firing covers the gap in practice.
        """
        if self.state == self.STATE_2:
            dx = x - self._last_x
            dy = y - self._last_y
            self._last_x, self._last_y = x, y
            self._last_width, self._last_height = width, height
            return self._send_relative_frame(buttons, dx, dy, wheel)

        nx = max(0, min(0xFFFF, int((0xFFFF * x) // max(1, width))))
        ny = max(0, min(0xFFFF, int((0xFFFF * y) // max(1, height))))
        self._last_x, self._last_y = x, y
        self._last_width, self._last_height = width, height
        return self._send_absolute_frame(buttons, nx, ny, wheel)

    def send_mouse_relative(self, buttons: int, dx: int, dy: int, wheel: int = 0) -> bool:
        """
        Emit a button or scroll event (or, in state 2, a true relative motion).

        State 2: emit a native 0x02 relative-mouse frame.
        States 3/4: re-emit the last known absolute position with the new
        button/wheel bytes — there's no relative path on the wire, so
        button-only and scroll events ride the absolute frame.
        """
        if self.state == self.STATE_2:
            return self._send_relative_frame(buttons, dx, dy, wheel)

        nx = max(0, min(0xFFFF, int((0xFFFF * self._last_x) // max(1, self._last_width))))
        ny = max(0, min(0xFFFF, int((0xFFFF * self._last_y) // max(1, self._last_height))))
        return self._send_absolute_frame(buttons, nx, ny, wheel)

    def _send_relative_frame(self, buttons: int, dx: int, dy: int, wheel: int) -> bool:
        # dx/dy/wheel are 1-byte signed values; clamp to the signed range
        # and let &0xFF produce the two's-complement encoding on the wire.
        dx_b = max(-127, min(127, dx)) & 0xFF
        dy_b = max(-127, min(127, dy)) & 0xFF
        wh_b = max(-127, min(127, wheel)) & 0xFF
        self.port.write(HEADER + bytes([0x02, buttons & 0xFF, dx_b, dy_b, wh_b]))
        return True

    def _send_absolute_frame(self, buttons: int, x: int, y: int, wheel: int) -> bool:
        # x and y are unsigned 16-bit; the leading 0x01 after the cmd byte is
        # a fixed report-ID prefix matching empirical captures from real LCs.
        wh_b = max(-127, min(127, wheel)) & 0xFF
        self.port.write(
            HEADER
            + bytes(
                [
                    0x04,
                    0x01,
                    buttons & 0xFF,
                    x & 0xFF,
                    (x >> 8) & 0xFF,
                    y & 0xFF,
                    (y >> 8) & 0xFF,
                    wh_b,
                ]
            )
        )
        return True
