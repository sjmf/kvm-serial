"""
CH9350L UART-to-USB-HID extender protocol implementation.

The CH9350L is a paired-chip extender: a *lower computer* (LC, USB host;
reads keyboard/mouse) talks to an *upper computer* (UC, USB device; presents
HID to the target PC) over UART. kvm-serial drives the UART side, replacing
the LC in software, so the CH9350L on the other end of the link enumerates
USB HID devices on the target.

This module covers all four working states (selected on the UC's S0/S1
dipswitches):

    state 0/1: paired mode with descriptor announce + PID-ack handshake
               — full HID Report Descriptor passthrough
    state 2:   BIOS keyboard + relative mouse
               — legacy BIOS / UEFI CSM compatible
    state 3:   BIOS keyboard + absolute mouse
               — modern OS, single monitor
    state 4:   BIOS keyboard + absolute mouse + HID Digitizers
               — modern OS, multi-monitor

State 0/1 is a single user choice (the chip boots into state 0 and
transitions to state 1 internally once the UC has acknowledged every
announced PID). States 2/3/4 are dipswitch-fixed and need no handshake.
See docs/CH9350L_PROTO.md for the on-the-wire framing detail.
"""

import logging
import threading
import time

from kvm_serial.utils.communication import DataComm

logger = logging.getLogger(__name__)

HEADER = b"\x57\xab"

# LC -> UC heartbeat. Low nibble = IO pin state; a real LC sends 0xA3
# (IO0/IO1 high). The UC also accepts 0xA0.
HEARTBEAT_FRAME = HEADER + bytes([0x82, 0xA3])

# Captured HID Report Descriptors from a real CH9350L LC. The LC announces
# these over 0x81 frames so the UC can present matching descriptors to the
# target. PIDs are reflected back in the UC's 0x12 keep-alive once each
# descriptor has been processed; the LC waits for that ack before
# transitioning state 0 -> state 1.
DEFAULT_MOUSE_DESC = bytes.fromhex(
    # ---- Relative mouse application ----
    "05010902a101"  # Usage Page (Generic Desktop), Usage (Mouse), Collection (Application)
    "8501"  # Report ID 1
    "0901a100"  # Usage (Pointer), Collection (Physical)
    "0509190129031500250175019503810275059501"  # 5 buttons + X/Y relative + wheel
    "810105010930093109381581257f750895038106c0"  # Extended features
    "05ff09021500250175019501b12275079501b101c0"  # Vendor-specific
)
DEFAULT_MOUSE_PID = bytes.fromhex("4000")
DEFAULT_KBD_DESC = bytes.fromhex(
    # ---- Keyboard application ----
    "05010906a101"  # Generic Desktop / Keyboard
    "8501050719e029e7150025017501950881029501750881019503750105081901"  # Report ID 1: modifiers + keycodes
    "2903910295017505910195067508150026ff000507190029918100c0"
    # ---- System Control application ----
    "05010980a101"  # Generic Desktop / System Control
    "850219812983150025019503750181029501750581"
    "01c0"
    # ---- Consumer Control application ----
    "050c0901a101"  # Consumer / Consumer Control
    "85031500250109e909ea09e209cd19b529b87501950881020a8a010a21"
    "020a2a021a23022a270281020a83010a96010a92010a9e010a94010a060209b2"
    "09b48102c0"
)
DEFAULT_KBD_PID = bytes.fromhex("0315")

# Known fixed payload lengths (bytes after the cmd byte) for UC -> LC
# decode. 0x83/0x88 are length-prefixed and 0x81 has its own 2-byte LE
# length field; both are handled separately in _parse_frames.
_PAYLOAD_LEN = {
    0x82: 1,  # heartbeat (IO status byte)
    0x12: 8,  # UC keep-alive (8 bytes after cmd)
    0x01: 8,  # state-2 keyboard (8-byte HID boot report)
    0x02: 4,  # state-2 relative mouse (btn, dx, dy, wheel)
    0x04: 7,  # state-3/4 absolute mouse (id, btn, xL, xH, yL, yH, wheel)
    0x80: 1,  # LED status / "unknown" (0xFF or 0x3N)
    0x86: 0,  # device-notify (no payload)
    0x89: 0,  # status announce (no payload)
}


def _split_relative_delta(dx: int, dy: int, max_step: int = 127):
    """
    Yield (chunk_dx, chunk_dy) tuples, each within ±max_step, summing to (dx, dy).

    State-0/1/2 mouse frames carry signed-byte deltas; a single send for
    |delta| > 127 would clamp at the comm layer and lose displacement. Splitting
    proportionally lets a single absolute target translate to a short burst of
    relative frames that the host integrates back into the requested motion --
    same approach as Wacom's on-device pen-to-mouse conversion. Frames-per-axis
    is ceil(max(|dx|, |dy|) / max_step); each yielded chunk respects max_step
    by construction.
    """
    if abs(dx) <= max_step and abs(dy) <= max_step:
        yield dx, dy
        return
    n = (max(abs(dx), abs(dy)) - 1) // max_step + 1
    sent_dx = sent_dy = 0
    for i in range(1, n + 1):
        target_dx = dx * i // n
        target_dy = dy * i // n
        yield target_dx - sent_dx, target_dy - sent_dy
        sent_dx, sent_dy = target_dx, target_dy


def _parse_frames(buf: bytearray) -> tuple[list[tuple[int, bytes]], bytearray]:
    """
    Extract complete frames from buf. Returns (frames, remaining_buf) where
    frames is a list of (cmd, payload) tuples. cmd == -1 represents bytes
    skipped while resyncing on HEADER (logged as a hint that something is
    off in the receive stream).
    """
    frames: list[tuple[int, bytes]] = []
    while True:
        idx = buf.find(HEADER)
        if idx == -1:
            # No header in buf: keep the last byte in case it starts a header.
            buf = bytearray(buf[-1:]) if buf else bytearray()
            break
        if idx > 0:
            # Pre-header bytes are framing noise (mid-frame sniff start, a
            # corrupted byte, etc.); surface them so the caller can log.
            skipped = bytes(buf[:idx])
            buf = buf[idx:]
            frames.append((-1, skipped))

        if len(buf) < 3:
            break  # need at least header + cmd

        cmd = buf[2]

        if cmd in (0x83, 0x88):
            # Length-prefixed: payload[0] = LEN, total payload = 1 + LEN bytes.
            if len(buf) < 4:
                break
            plen = buf[3]
            needed = 4 + plen
            if len(buf) < needed:
                break
            payload = bytes(buf[3:needed])
            buf = buf[needed:]
            frames.append((cmd, payload))
            continue

        if cmd == 0x81:
            # Device Connection: 57 AB 81 [PORT:1] [LEN:2 LE] [PAYLOAD] [PID:2] [CHK:1]
            if len(buf) < 6:
                break
            plen = buf[4] | (buf[5] << 8)
            needed = 9 + plen  # 3 (hdr+cmd) + 1 (PORT) + 2 (LEN) + plen + 2 (PID) + 1 (CHK)
            if len(buf) < needed:
                break
            payload = bytes(buf[3:needed])
            buf = buf[needed:]
            frames.append((cmd, payload))
            continue

        known_len = _PAYLOAD_LEN.get(cmd)
        if known_len is not None:
            needed = 3 + known_len
            if len(buf) < needed:
                break
            payload = bytes(buf[3:needed])
            buf = buf[needed:]
            frames.append((cmd, payload))
        else:
            # Unknown cmd: scan for next header to bound the frame.
            next_hdr = buf.find(HEADER, 3)
            if next_hdr == -1:
                if len(buf) > 128:
                    payload = bytes(buf[3:])
                    frames.append((cmd, payload))
                    buf = bytearray()
                else:
                    break
            else:
                payload = bytes(buf[3:next_hdr])
                frames.append((cmd, payload))
                buf = buf[next_hdr:]

    return frames, buf


class CH9350Comm(DataComm):
    """
    CH9350L extender — supports all four working states.

    State 0/1 (paired mode) requires a full attach handshake against a real
    UC: send 0x86 -> 0x80 x2 -> 0x89, wait for the UC's 0x12 keep-alive, then
    announce the LC's HID Report Descriptors via 0x81 xN. The state machine
    transitions 0 -> 1 once every announced PID is reflected back in the
    UC's keep-alive. Frames after that point use cmd 0x83 (paired); before
    it, cmd 0x88 (unpaired) — payloads are otherwise identical.

    States 2/3/4 are dipswitch-fixed simple modes with no handshake; LC->UC
    frames carry no SER, no checksum, no per-frame counter.

    For state 0/1 callers must invoke ``start()`` to spawn the rx and
    maintenance threads and run the attach sequence; ``stop()`` halts them.
    States 2/3/4 don't need start/stop — those calls are no-ops there.
    """

    STATE_0 = 0
    STATE_1 = 1
    STATE_2 = 2
    STATE_3 = 3
    STATE_4 = 4

    # State 1 is reached internally via the state-0 handshake; not user-selectable.
    SUPPORTED_STATES = (STATE_0, STATE_2, STATE_3, STATE_4)

    # State-0/1 frame SER + report-ID bytes. These must agree with the
    # announced descriptors' Report ID items — RID values prefix each
    # 0x83/0x88 payload.
    KB_SER = 0x13  # keyboard / HID / port 2
    KB_RID = 0x01  # 8-byte boot keyboard report follows
    MOU_SER = 0x22  # mouse / HID / port 1
    MOU_RID = 0x01  # 4-byte relative mouse report follows

    # How long to wait between 0x81 retransmits while a PID remains un-acked.
    _ANNOUNCE_RETRY_INTERVAL = 2.0
    _HEARTBEAT_INTERVAL = 1.0

    def __init__(
        self,
        port,
        state: int = STATE_2,
        mouse_desc: bytes | None = None,
        mouse_pid: bytes | None = None,
        kbd_desc: bytes | None = None,
        kbd_pid: bytes | None = None,
    ):
        if state not in self.SUPPORTED_STATES:
            raise ValueError(
                f"CH9350Comm supports states {self.SUPPORTED_STATES}; "
                f"state 1 is reached internally via the state-0 handshake "
                f"and is not user-selectable"
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

        # State 0/1 plumbing — irrelevant for states 2/3/4 but cheap to set
        # up unconditionally and keeps the attribute access uniform.
        self.mouse_desc = mouse_desc if mouse_desc is not None else DEFAULT_MOUSE_DESC
        self.kbd_desc = kbd_desc if kbd_desc is not None else DEFAULT_KBD_DESC
        self.mouse_pid = mouse_pid if mouse_pid is not None else DEFAULT_MOUSE_PID
        self.kbd_pid = kbd_pid if kbd_pid is not None else DEFAULT_KBD_PID
        if len(self.mouse_pid) != 2 or len(self.kbd_pid) != 2:
            raise ValueError("mouse_pid and kbd_pid must each be exactly 2 bytes")
        self._kbd_counter = 0
        self._mou_counter = 0
        self._uc_p1 = b"\x00\x00"
        self._uc_p2 = b"\x00\x00"
        self._uc_status = 0x00
        self._last_hb = 0.0
        self._last_mouse_announce = 0.0
        self._last_kbd_announce = 0.0
        self._stop = threading.Event()
        self._uc_seen = threading.Event()
        self._reattach_needed = threading.Event()
        # Last LED byte echoed back to the UC via 0x80 0x3N (states 2/3/4).
        # Sentinel 0xFF means "nothing echoed yet"; the UC's pre-enum default
        # is also 0xFF and we deliberately do not echo that.
        self._echoed_led = 0xFF
        # Serialise port writes — rx callbacks (LED echo), tx maintenance
        # (heartbeat / retransmit), and user sends all converge on port.write.
        self._tx_lock = threading.Lock()
        self._rx_thread: threading.Thread | None = None
        self._tx_thread: threading.Thread | None = None

    # ------------------------------------------------------------------ public

    def start(self) -> None:
        """
        Spawn the rx thread, plus (state 0 only) the tx-maintenance thread
        that drives the attach handshake, heartbeats, and reattach replay.

        State 0:    rx + tx-maintenance.
        States 2/3/4: rx only - there's no handshake, but the rx loop drives
                     LED echo back to the source keyboard from the UC's 0x12
                     keep-alive.
        """
        if self._rx_thread is not None:
            raise RuntimeError("CH9350Comm.start() called twice")
        self._stop.clear()
        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self._rx_thread.start()
        if self.state == self.STATE_0:
            # Run the initial attach in the maintenance thread so start()
            # returns immediately; the caller is then free to send frames
            # (which will emit 0x88 unpaired until the UC acks all PIDs and
            # we transition to state 1).
            self._tx_thread = threading.Thread(target=self._tx_maint_loop, daemon=True)
            self._tx_thread.start()

    def stop(self) -> None:
        """Halt the rx (and, in state 0, tx-maintenance) threads."""
        self._stop.set()
        if self._tx_thread is not None:
            self._tx_thread.join(timeout=2.0)
            self._tx_thread = None
        if self._rx_thread is not None:
            self._rx_thread.join(timeout=2.0)
            self._rx_thread = None

    def send_scancode(self, scancode: bytes) -> bool:
        """
        Send an 8-byte HID boot-protocol keyboard report.
        State 0/1 wraps it in a SER + counter framed payload (cmd 0x83/0x88);
        states 2/3/4 use the simple 11-byte 0x01 frame.
        """
        if len(scancode) < self.SCANCODE_LENGTH:
            return False
        if self.state in (self.STATE_0, self.STATE_1):
            modifier = scancode[0]
            keys = list(scancode[2 : self.SCANCODE_LENGTH])
            frame = self._build_state01_kbd_frame(modifier, keys)
            return self._send_locked(frame)
        self._send_locked(HEADER + b"\x01" + scancode[: self.SCANCODE_LENGTH])
        return True

    def release(self) -> bool:
        """Release all keys (send the all-zeros HID report)."""
        return self.send_scancode(b"\x00" * self.SCANCODE_LENGTH)

    def send_mouse_absolute(
        self, buttons: int, x: int, y: int, width: int, height: int, wheel: int = 0
    ) -> bool:
        """
        Emit a positional update.

        States 3/4: native absolute path. Pixel coords scale into the chip's
        16-bit absolute space and emit a 0x04 frame.
        States 0/1 and 2: no absolute path exists on the wire (UC firmware
        silently drops LEN=0x0A in state 0/1; state 2's BIOS boot mouse is
        relative-only by design — see docs/CH9350L_PROTO.md §Divergences).
        Translate to a relative delta from the last reported absolute
        position. When |delta| > 127 in either axis (e.g. cursor teleport,
        focus-into-window from far away) the displacement fans out into a
        short burst of consecutive frames so the cursor reaches the true
        target rather than stopping ~127 px short — equivalent to what a
        Wacom-style device does on-chip in pen-to-mouse mode.
        """
        if self.state in (self.STATE_0, self.STATE_1, self.STATE_2):
            dx = int(x - self._last_x)
            dy = int(y - self._last_y)
            self._last_x, self._last_y = x, y
            self._last_width, self._last_height = width, height
            ok = True
            for i, (chunk_dx, chunk_dy) in enumerate(_split_relative_delta(dx, dy)):
                # Wheel rides only the first chunk so a multi-frame fan-out
                # doesn't multiply a single scroll request.
                chunk_wheel = wheel if i == 0 else 0
                ok = self._send_relative_frame(buttons, chunk_dx, chunk_dy, chunk_wheel) and ok
            return ok

        nx = max(0, min(0xFFFF, int((0xFFFF * x) // max(1, width))))
        ny = max(0, min(0xFFFF, int((0xFFFF * y) // max(1, height))))
        self._last_x, self._last_y = x, y
        self._last_width, self._last_height = width, height
        return self._send_absolute_frame(buttons, nx, ny, wheel)

    @property
    def supports_absolute_mouse(self) -> bool:
        """
        True if this comm forwards absolute-mouse reports natively to the
        target host (states 3/4); False if `send_mouse_absolute` translates
        the requested position into relative deltas (states 0/1/2). Useful
        for application code surfacing mode information or selecting
        different UX for absolute-aware vs relative-only modes.
        """
        return self.state in (self.STATE_3, self.STATE_4)

    def send_mouse_relative(self, buttons: int, dx: int, dy: int, wheel: int = 0) -> bool:
        """
        Emit a button or scroll event (or, in state 0/1/2, a true relative motion).

        States 0/1 and 2: emit a native relative-mouse frame.
        States 3/4: re-emit the last known absolute position with the new
        button/wheel bytes — there's no relative path on the wire, so
        button-only and scroll events ride the absolute frame.
        """
        if self.state in (self.STATE_0, self.STATE_1, self.STATE_2):
            return self._send_relative_frame(buttons, dx, dy, wheel)

        nx = max(0, min(0xFFFF, int((0xFFFF * self._last_x) // max(1, self._last_width))))
        ny = max(0, min(0xFFFF, int((0xFFFF * self._last_y) // max(1, self._last_height))))
        return self._send_absolute_frame(buttons, nx, ny, wheel)

    # ------------------------------------------------------------- frame builders

    def _send_relative_frame(self, buttons: int, dx: int, dy: int, wheel: int) -> bool:
        if self.state in (self.STATE_0, self.STATE_1):
            frame = self._build_state01_mou_frame(buttons, dx, dy, wheel)
        else:
            # State 2 simple frame: 7 bytes total.
            dx_b = max(-127, min(127, int(dx))) & 0xFF
            dy_b = max(-127, min(127, int(dy))) & 0xFF
            wh_b = max(-127, min(127, int(wheel))) & 0xFF
            frame = HEADER + bytes([0x02, buttons & 0xFF, dx_b, dy_b, wh_b])
        return self._send_locked(frame)

    def _send_absolute_frame(self, buttons: int, x: int, y: int, wheel: int) -> bool:
        # x and y are unsigned 16-bit; the leading 0x01 after the cmd byte is
        # a fixed report-ID prefix matching empirical captures from real LCs.
        wh_b = max(-127, min(127, wheel)) & 0xFF
        frame = HEADER + bytes(
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
        return self._send_locked(frame)

    def _build_state01_kbd_frame(self, modifier: int, keycodes: list[int]) -> bytes:
        """
        State-0/1 keyboard frame:
            HEADER + cmd + LEN + SER + RID + [mod rsvd k0..k5] + CTR + CTRSUM
        cmd is 0x88 in state 0 (unpaired) or 0x83 in state 1 (paired).
        CTR is a per-SER counter (mod-256) and CTRSUM = (CTR + sum(hid)) & 0xFF.
        """
        cmd = 0x83 if self.state == self.STATE_1 else 0x88
        keys = (keycodes + [0] * 6)[:6]
        hid = bytes([self.KB_RID, modifier & 0xFF, 0x00] + keys)
        ctr = self._kbd_counter & 0xFF
        self._kbd_counter += 1
        ctr_sum = (ctr + sum(hid)) & 0xFF
        plen = 1 + len(hid) + 2  # SER + hid + CTR + CTRSUM
        return HEADER + bytes([cmd, plen, self.KB_SER]) + hid + bytes([ctr, ctr_sum])

    def _build_state01_mou_frame(self, btn: int, dx: int, dy: int, wheel: int) -> bytes:
        """
        State-0/1 relative mouse frame:
            HEADER + cmd + LEN + SER + RID + [btn dx dy wheel] + CTR + CTRSUM
        cmd is 0x88 (state 0) or 0x83 (state 1). dx/dy clamp to ±127.
        """
        cmd = 0x83 if self.state == self.STATE_1 else 0x88
        dx_b = max(-127, min(127, int(dx))) & 0xFF
        dy_b = max(-127, min(127, int(dy))) & 0xFF
        data = bytes([self.MOU_RID, btn & 0xFF, dx_b, dy_b, wheel & 0xFF])
        ctr = self._mou_counter & 0xFF
        self._mou_counter += 1
        ctr_sum = (ctr + sum(data)) & 0xFF
        plen = 1 + len(data) + 2
        return HEADER + bytes([cmd, plen, self.MOU_SER]) + data + bytes([ctr, ctr_sum])

    def _build_device_connect_frame(
        self, descriptor: bytes, port_id: int, device_pid: bytes
    ) -> bytes:
        """
        Build a 0x81 Device Connection Frame:
            HEADER + 0x81 + [PORT:1] + [LEN:2 LE] + DESCRIPTOR + [PID:2] + [CHK:1]
        CHK = (sum(DESCRIPTOR) + sum(PID)) & 0xFF.
        """
        if len(device_pid) != 2:
            raise ValueError("device_pid must be 2 bytes")
        plen = len(descriptor)
        chk = (sum(descriptor) + sum(device_pid)) & 0xFF
        return (
            HEADER
            + bytes([0x81, port_id, plen & 0xFF, (plen >> 8) & 0xFF])
            + descriptor
            + device_pid
            + bytes([chk])
        )

    # ------------------------------------------------------------------ tx helpers

    def _send_locked(self, data: bytes) -> bool:
        """Serialised port write — used by user sends, rx callbacks, and the
        tx maintenance thread."""
        with self._tx_lock:
            self.port.write(data)
        return True

    def _heartbeat(self) -> None:
        self._send_locked(HEARTBEAT_FRAME)
        self._last_hb = time.time()

    def _send_announce(self) -> None:
        """Send a 0x89 status announce. Real LCs emit ~3 of these during
        attach; the LC sends one as part of the attach sequence here."""
        self._send_locked(HEADER + bytes([0x89]))

    def _announce_descriptors(self) -> None:
        """Send 0x81 Device Connection Frames for each configured device."""
        now = time.time()
        if self.mouse_desc:
            self._send_locked(
                self._build_device_connect_frame(
                    self.mouse_desc, port_id=0x00, device_pid=self.mouse_pid
                )
            )
            self._last_mouse_announce = now
            time.sleep(0.05)
        if self.kbd_desc:
            self._send_locked(
                self._build_device_connect_frame(
                    self.kbd_desc, port_id=0x01, device_pid=self.kbd_pid
                )
            )
            self._last_kbd_announce = now
            time.sleep(0.05)

    def _maybe_retransmit_descriptors(self, now: float) -> None:
        """Retransmit any 0x81 whose PID isn't yet reflected in the UC's
        keep-alive. Recovers from UC restart or transient UART loss."""
        if self.mouse_desc and self._uc_p1 != self.mouse_pid:
            if now - self._last_mouse_announce >= self._ANNOUNCE_RETRY_INTERVAL:
                self._send_locked(
                    self._build_device_connect_frame(
                        self.mouse_desc, port_id=0x00, device_pid=self.mouse_pid
                    )
                )
                self._last_mouse_announce = now
        if self.kbd_desc and self._uc_p2 != self.kbd_pid:
            if now - self._last_kbd_announce >= self._ANNOUNCE_RETRY_INTERVAL:
                self._send_locked(
                    self._build_device_connect_frame(
                        self.kbd_desc, port_id=0x01, device_pid=self.kbd_pid
                    )
                )
                self._last_kbd_announce = now

    def _run_attach_sequence(self, *, wait_for_uc: bool) -> None:
        """
        Replay the LC->UC attach sequence:
            0x86 -> 0x80 0xFF (x2) -> heartbeat -> 0x89 -> 0x81 xN
        Used at startup (wait_for_uc=True: defer 0x81 until a UC keep-alive
        is observed) and on reconnect (wait_for_uc=False: UC is already
        keep-aliving but its USB-device side dropped and needs 0x86/0x80 to
        re-present to the target).
        """
        self._send_locked(HEADER + bytes([0x86]))
        time.sleep(0.25)
        self._send_locked(HEADER + bytes([0x80, 0xFF]))
        time.sleep(0.23)
        self._send_locked(HEADER + bytes([0x80, 0xFF]))
        self._heartbeat()
        time.sleep(1.0)
        self._send_announce()

        if not (self.mouse_desc or self.kbd_desc):
            return
        if wait_for_uc and not self._uc_seen.is_set():
            logger.info("Waiting for UC keep-alive before announcing devices...")
            while not self._uc_seen.wait(timeout=self._HEARTBEAT_INTERVAL):
                if self._stop.is_set():
                    return
                self._heartbeat()
        self._announce_descriptors()

    # ---------------------------------------------------------- background loops

    def _tx_maint_loop(self) -> None:
        """
        Heartbeat, 0x81 retransmit, and full attach replay on reconnect.
        Decoupled from user sends so a slow caller doesn't starve the UC of
        heartbeats or stall reconnect handling.
        """
        self._run_attach_sequence(wait_for_uc=True)
        while not self._stop.is_set():
            if self._reattach_needed.is_set():
                self._reattach_needed.clear()
                logger.info("Reattach: replaying attach sequence")
                self._run_attach_sequence(wait_for_uc=False)
                continue
            now = time.time()
            if now - self._last_hb >= self._HEARTBEAT_INTERVAL:
                self._heartbeat()
            self._maybe_retransmit_descriptors(now)
            self._stop.wait(timeout=0.2)

    def _rx_loop(self) -> None:
        """Read + decode incoming frames from upper computer."""
        buf = bytearray()
        while not self._stop.is_set():
            try:
                chunk = self.port.read(64)
            except Exception:
                # Serial errors during shutdown are expected; fall through
                # to the stop check on the next iteration.
                break
            if chunk:
                buf.extend(chunk)
                frames, buf = _parse_frames(buf)
                for cmd, payload in frames:
                    if cmd == -1:
                        logger.debug("rx sync skip: %d bytes", len(payload))
                        continue
                    self._handle_frame(cmd, payload)

    def _handle_frame(self, cmd: int, payload: bytes) -> None:
        """
        Receive-side state machine. Pure function modulo ``self``: tests
        can drive it directly with synthetic UC frames.

        Decodes the UC's 0x12 keep-alive (PIDs in P1/P2, LED byte at index 4,
        STATUS at index 5) and dispatches:
          - State 0: sets _uc_seen on first 0x12 (cleared to send 0x81),
            transitions to state 1 once every announced PID is reflected.
          - State 1: reverts to state 0 + sets _reattach_needed when the UC
            drops a previously-acked PID (target-side USB replug).
          - States 2/3/4: echoes the UC's reported LED state back as a
            0x80 0x3N frame so the source keyboard's lock-key LEDs mirror
            the target host. Echoes only on change to avoid flooding.
        """
        logger.debug("rx cmd=%02x payload=%s", cmd, payload.hex(" "))
        if cmd != 0x12 or len(payload) < 4:
            return
        self._uc_p1 = bytes(payload[0:2])
        self._uc_p2 = bytes(payload[2:4])
        if len(payload) >= 6:
            self._uc_status = payload[5]
        if not self._uc_seen.is_set():
            logger.info("UC keep-alive observed -- announce phase cleared")
            self._uc_seen.set()

        # LED echo for the simple modes. The UC's 0x12 byte 4 carries the
        # target host's keyboard LED state (NumLk/CapsLk/ScrLk in the low
        # three bits); we mirror it back to the LC's USB-host side via
        # 0x80 0x3N so the source keyboard's lock LEDs follow the target.
        # 0xFF means "UC has no target enumerated yet"; never echo that.
        if self.state in (self.STATE_2, self.STATE_3, self.STATE_4) and len(payload) >= 5:
            led_byte = payload[4]
            if led_byte != 0xFF and led_byte != self._echoed_led:
                self._send_locked(HEADER + bytes([0x80, 0x30 | (led_byte & 0x07)]))
                self._echoed_led = led_byte
            return

        want_p1 = self.mouse_pid if self.mouse_desc else b"\x00\x00"
        want_p2 = self.kbd_pid if self.kbd_desc else b"\x00\x00"
        any_announced = bool(self.mouse_desc or self.kbd_desc)
        all_acked = self._uc_p1 == want_p1 and self._uc_p2 == want_p2

        if self.state == self.STATE_0 and any_announced and all_acked:
            logger.info("UC acknowledged all PIDs - entering state 1")
            self.state = self.STATE_1
        elif self.state == self.STATE_1 and not all_acked:
            # UC dropped a PID - likely target-side USB replug. Revert to
            # state 0 and trigger the maintenance thread to replay the full
            # attach sequence (0x81 alone won't make the UC re-enumerate).
            logger.info(
                "UC PIDs no longer match (p1=%s p2=%s) - reverting to state 0, triggering reattach",
                self._uc_p1.hex(),
                self._uc_p2.hex(),
            )
            self.state = self.STATE_0
            self._reattach_needed.set()
