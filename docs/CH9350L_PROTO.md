# CH9350L UART Protocol Specification

> **Status:** empirically verified by bidirectional bus sniffing.
> Frames in this document have been observed on the wire and the
> reference implementation (`ch9350_poc.py`) reproduces them exactly,
> including byte-for-byte matching of the `0x81` Device Connection Frames.
> Coverage now includes power-on, attach, key/mouse forwarding, steady-state
> operation, runtime disconnect, target-side reattach with full sequence replay,
> and all four alternative dipswitch states (2/3/4) including `0x80` LED feedback,
> state-2 relative mouse, and state-3/4 absolute mouse.
>
> **Manufacturer datasheet:** WCH CH9350 V2.3 — [wch-ic.com/downloads/CH9350DS_PDF.html](https://www.wch-ic.com/downloads/CH9350DS_PDF.html). Section references in this document refer to that datasheet. See [§Divergences from the datasheet](#divergences-from-the-datasheet) for the places where on-the-wire behaviour differs from what the datasheet documents.
>
> **Reference implementation:** `ch9350_poc.py` (repo root) and the Gist at
> https://gist.github.com/sjmf/c4329fd27e403a264648bf4e7744655a

---

## Overview

The CH9350L is a USB-to-UART bridge chip designed to operate in pairs:

- **Lower Computer (LC)** — acts as a USB *host*, enumerating attached HID devices (keyboard, mouse).
- **Upper Computer (UC)** — acts as a USB *device*, presenting HID interfaces to the target PC.

The two chips communicate over a full-duplex TTL UART bus. kvm-serial replaces the lower computer in software, speaking this protocol directly toward a physical UC module.

Each module has three relevant dipswitches: `SEL` selects the chip's role (`SEL=1` → lower computer, `SEL=0` → upper computer); `S0` and `S1` together select the **working state** (default 0/1 with handshake; alternatives 2/3/4 with fixed built-in descriptors — see [§States 2/3/4](#states-234-alternative-dipswitch-configurations)); `BAUD0`/`BAUD1` select the UART baud rate (default 115200).

---

## Physical Layer

| Parameter | Value |
|-----------|-------|
| Baud rate | 115200 |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |
| Logic level | 3.3 V TTL |

---

## Frame Structure

All frames share the same two-byte magic header:

```
57 AB [CMD] [payload...]
```

The payload layout depends on `CMD`:

| CMD | Direction | Length | Used in | Payload format |
|-----|-----------|--------|---------|----------------|
| `0x82` | LC → UC | 4B total | 0/1 | Heartbeat: `[IO]` |
| `0x86` | LC → UC | 3B total | 0/1, 2, 3, 4 | Device Notify: no payload |
| `0x80` | LC → UC | 4B total | 0/1, 2, 3, 4 | Startup status (`0xFF`) / LED feedback (`0x3N`) |
| `0x89` | LC → UC | 3B total | 0/1, 2, 3, 4 | Status announce: no payload |
| `0x81` | LC → UC | variable | 0/1 only | `[PORT] [LEN_LO LEN_HI] [DESCRIPTOR] [PID_LO PID_HI] [CHK]` |
| `0x83`, `0x88` | LC → UC | length-prefixed | 0/1 only | `[LEN] [SER] [report-bytes...] [CTR] [CTR_SUM]` |
| `0x01`, `0x02`, `0x04` | LC → UC | fixed (8 / 5 / 8B) | 2 / 2 / 3, 4 | State-2/3/4 keyboard / rel-mouse / abs-mouse |
| `0x10` | LC → UC | 7B total | 2, 3, 4 | VID/PID modify: `[VID_LO VID_HI] [PID_LO PID_HI]` |
| `0x12` | UC → LC | 11B total | 0/1, 2, 3, 4 | Keep-alive: `[P1] [P2] [LED] [STATUS] [VERSION]` |

### Length-prefixed key/mouse frames (CMD `0x83` / `0x88`)

```
57 AB [CMD] [LEN] [SER] [report-bytes...] [CTR] [CTR_SUM]
```

- **LEN** — number of bytes following LEN, i.e. `SER(1) + report-bytes(n) + CTR(1) + CTR_SUM(1)`
- **SER** — labeling byte; encodes device class, protocol, and port number (see §Labeling Byte)
- **CTR** — monotonically increasing session counter, mod 256; separate per SER
- **CTR_SUM** — checksum: `(CTR + sum(report-bytes)) mod 256`
  where `report-bytes` is everything between SER and CTR, exclusive

The CMD byte selects state 0 (`0x88`) vs state 1 (`0x83`); the payload format is identical between the two. See [§State Machine](#state-machine) for the transition rule.

---

## Lower Computer → Upper Computer Frames

### Heartbeat — CMD `0x82`

Sent by the LC at ~1 s cadence when idle. During active key/mouse traffic the cadence becomes denser — heartbeats are interleaved with `0x83`/`0x88` frames, sometimes only ~50 ms apart. The ~1 s figure is the *minimum-frequency* idle baseline, not a strict period.

```
57 AB 82 [IO]
```

| Byte | Meaning |
|------|---------|
| `IO` | High nibble = `0xA` (fixed); low nibble = IO0/IO1/IO3/IO4 pin state. `0xA3` typical (all inputs high) |

### Status Announce — CMD `0x89`

```
57 AB 89
```

No payload. In state 0/1 captures the LC emits 3 instances at ~2 s intervals starting ~1.4 s after the first `0x86`, then stops for the rest of the session. In states 2/3/4 captures only a single `0x89` is observed, at startup. This is consistent with `0x89` being tied to the descriptor-announce phase: states 2/3/4 have no `0x81` descriptor exchange to wait on, so the opcode is sent once and not repeated. The UC continues normal operation in `0x89`'s absence. See [§Divergences](#divergences-from-the-datasheet) for what the datasheet does (and does not) say about this opcode.

### Device Connection Frame — CMD `0x81`

Sent by the LC at attach time, once per connected USB device. Carries the device's HID Report Descriptor; the UC uses these to construct matching HID descriptors that it will advertise to the target PC over USB. **Without `0x81` frames in state 0/1 the LC's subsequent `0x83`/`0x88` input frames produce no effect on the target host** — observed empirically. The likely mechanism is that the UC has no descriptor to advertise so its target-side endpoints either fail to enumerate or enumerate with mismatched report IDs; the LC has no way to detect this from its side.

```
57 AB 81 [PORT] [LEN_LO] [LEN_HI] [DESCRIPTOR...] [PID_LO] [PID_HI] [CHK]
```

| Field | Size | Notes |
|-------|------|-------|
| PORT | 1B | `0x00` = port 1 (DP/DM), `0x01` = port 2 (HP/HM) |
| LEN | 2B LE | length of DESCRIPTOR (74 / 165 bytes observed) |
| DESCRIPTOR | LEN bytes | raw USB HID Report Descriptor (no wrapping) |
| PID | 2B LE | device "PID" identifier — appears verbatim in the UC's `0x12` keep-alive once the descriptor has been processed |
| CHK | 1B | `(sum(DESCRIPTOR) + sum(PID)) mod 256` |

> **Naming note:** the datasheet calls the leading 1-byte field `ID` and the trailing 2-byte field `2-byte ID`. Empirically the leading byte selects the USB port (0/1) and the trailing 2 bytes propagate into the UC keep-alive's PID-port1/PID-port2 fields, so this document refers to them as `PORT` and `PID`.

The descriptor is a standard USB HID Report Descriptor in the format defined by the USB-IF HID specification (Usage Page, Usage, Collection, Report ID, etc.). The captured mouse and keyboard descriptors used by the reference implementation are 74 and 165 bytes long respectively. The mouse descriptor contains a single `Report ID` item (`0x01`); the keyboard descriptor contains three (`0x01` keyboard, `0x02` system control, `0x03` consumer control). In all observed `0x83`/`0x88` traffic the `RID` byte is `0x01`; the keyboard's secondary report IDs (system control, consumer control) were not exercised. In states 3/4, `0x04` absolute-mouse frames likewise carry `id=0x01` as a fixed prefix.

The LC retransmits the keyboard `0x81` frame ~2 s after its first transmission if the UC's `0x12` keep-alive has not yet reflected the keyboard PID. Whether the retransmit is purely time-driven or specifically gated on the missing ack is not pinned down — every observed retransmit was followed shortly by the matching ack, so the two are not separable from the available captures.

### Keyboard — CMD `0x83` / `0x88`

Two variants are produced depending on the USB device connected to the LC.

#### CH9329 / report-ID-prefixed keyboard, LEN = `0x0C`

```
57 AB [CMD] 0C [SER] [RID] [mod] [rsvd=00] [k0] [k1] [k2] [k3] [k4] [k5] [CTR] [CTR_SUM]
```

| Field | Value | Notes |
|-------|-------|-------|
| LEN | `0x0C` (12) | |
| SER | `0x13` | keyboard / HID / port 2 (see §Labeling Byte) |
| RID | report ID byte | `0x01` for the captured keyboard descriptor |
| `mod` | modifier byte | USB HID boot protocol modifier bitmask |
| `rsvd` | `0x00` | reserved per HID boot keyboard |
| `k0..k5` | key scancodes | USB HID usage IDs, zero-padded |

#### Boot-protocol keyboard (no report ID), LEN = `0x0B`

Produced by a real keyboard whose descriptor contains no Report ID item.

```
57 AB [CMD] 0B [SER=0x11] [mod] [rsvd=00] [k0] [k1] [k2] [k3] [k4] [k5] [CTR] [CTR_SUM]
```

| Field | Value | Notes |
|-------|-------|-------|
| LEN | `0x0B` (11) | one byte shorter — no report ID |
| SER | `0x11` | keyboard / Unknown protocol / port 2 |

**Modifier byte bitmask** (same for both variants):

| Bit | Modifier |
|-----|----------|
| 0 | Left Ctrl |
| 1 | Left Shift |
| 2 | Left Alt |
| 3 | Left GUI / Win |
| 4 | Right Ctrl |
| 5 | Right Shift |
| 6 | Right Alt |
| 7 | Right GUI / Win |

### Mouse — CMD `0x83` / `0x88`

Three variants observed, distinguished by LEN and SER. The LEN=`0x08` form is not in the datasheet; see [§Divergences](#divergences-from-the-datasheet).

#### Absolute mouse with report ID — LEN = `0x0A`

Produced by the CH9329 bridge (which reports absolute coordinates).

```
57 AB [CMD] 0A [SER=0x23] [RID=05] [btn] [XL] [XH] [YL] [YH] [wheel] [CTR] [CTR_SUM]
```

| Field | Value | Notes |
|-------|-------|-------|
| SER | `0x23` | mouse / HID / port 2 |
| RID | `0x05` | CH9329 absolute mouse report ID |
| `XL`/`XH` | X coordinate | 16-bit little-endian, raw USB HID absolute space |
| `YL`/`YH` | Y coordinate | 16-bit little-endian |

#### Relative mouse with report ID — LEN = `0x08`

Produced by a real mouse on **port 1** whose descriptor contains a Report ID.

```
57 AB [CMD] 08 [SER=0x22] [RID] [btn] [dx] [dy] [wheel] [CTR] [CTR_SUM]
```

| Field | Value | Notes |
|-------|-------|-------|
| SER | `0x22` | mouse / HID / port 1 |
| RID | report ID | matches Report ID in the mouse's `0x81` descriptor (e.g. `0x01`) |
| `dx`/`dy` | signed bytes | 8-bit relative deltas |

#### Relative mouse, boot protocol (no report ID) — LEN = `0x07`

Produced by a real mouse whose descriptor contains no Report ID.

```
57 AB [CMD] 07 [SER=0x20] [btn] [dx] [dy] [wheel] [CTR] [CTR_SUM]
```

| Field | Value | Notes |
|-------|-------|-------|
| SER | `0x20` | mouse / Unknown protocol / port 1 |

### CTR_SUM Worked Example

Keyboard frame `57 AB 83 0C 13 01 00 00 14 00 00 00 00 00 00 15`:

- LEN=`0C`, SER=`13`, report-bytes = `01 00 00 14 00 00 00 00 00`, CTR=`00`
- `CTR_SUM = (0x00 + (0x01+0x00+0x00+0x14+0x00+0x00+0x00+0x00+0x00)) mod 256 = 0x15` ✓

### Device Notify — CMD `0x86`

```
57 AB 86
```

Emitted by the LC on USB device events. The same opcode is used for both **attach** and **disconnect**; what disambiguates is the follow-up traffic. See [§Attach Sequence Timeline](#attach-sequence-timeline) for the attach case and [§Disconnect Sequence](#disconnect-sequence) for the disconnect case. The datasheet (§4.6) names this "Device Disconnect Command" and is partially incorrect on both opcode reuse and the claimed UC reset; see [§Divergences](#divergences-from-the-datasheet).

### Status / LED — CMD `0x80`

```
57 AB 80 [VAL]
```

Single-byte payload, dual-purpose:

- **Startup (`VAL=0xFF`):** sent twice ~210–260 ms apart immediately after the attach `0x86`. Means "LED state unknown" (pre-enumeration default).
- **State-2/3/4 LED feedback (`VAL=0x3N`):** during operation the LC emits `0x80 (0x30 | LED_BITS)` to mirror the target host's keyboard LED state back to the source keyboard. Low nibble matches the NumLk/CapsLk/ScrLk encoding of `0x12`'s `LED` byte (bit 0/1/2). Not observed in state 0/1 captures.

---

## Upper Computer → Lower Computer Frames

### Keep-alive / LED / PID-ack — CMD `0x12`

Sent by the UC approximately every 1 second.

```
57 AB 12 [P1_LO] [P1_HI] [P2_LO] [P2_HI] [LED] [STATUS] [VERSION_HI] [VERSION_LO]
```

Total frame length: 11 bytes (header 2 + cmd 1 + payload 8).

| Field | Size | Notes |
|-------|------|-------|
| `P1` | 2B LE | PID of port 1 — populated from the `PID` field of the LC's `0x81` frame for port 1, once accepted |
| `P2` | 2B LE | PID of port 2 — populated similarly for port 2 |
| `LED` | 1B | keyboard LED state: bit 0 = Num Lock, bit 1 = Caps Lock, bit 2 = Scroll Lock. `0xFF` observed when target host hasn't reported LED state yet |
| `STATUS` | 1B | bit-encoded UC health/enumeration state — see below |
| `VERSION` | 2B | high byte `0xAC` constant; low byte observed as `0x20` at steady state and `0x0B` during transients (first frame after attach, frame after a `STATUS` change). Purpose not decoded |

`STATUS` byte interpretation (empirical):

| Bit | Mask | Meaning |
|-----|------|---------|
| 0 | `0x01` | Port-0 device enumerated on target USB host |
| 1 | `0x02` | Port-1 device enumerated on target USB host |
| 2 | `0x04` | UART link healthy / UC alive |

Common values:
- `0x07` — both devices live on target, HID forwarding works (the only "all green" state)
- `0x04` — UART up, no target-side enumeration. Reasons include: cable in a DM/DP-less port, target replug pending re-enumeration (see [§Reattach](#re-attach-on-the-ucs-usb-device-side-target-replug)), board-mode dipswitch wrong, or no target host attached
- `0xFF` — UC's "fully unknown" state. Observed at startup (one or two frames before the UC settles into `0x07` or `0x04`), and during target-side cable yank
- `0x00` — pre-attach, before UC is fully up

The `P1`/`P2` fields start at `00 00` after power-on and populate as the UC processes each `0x81` frame. State-1 entry is gated on PID-ack (matching `P1`/`P2`), not on receiving any `0x12`. **`STATUS == 0x07` is the real "is HID actually being forwarded" indicator, not state-1 entry** — a board can complete the UART-side handshake and reach state 1 yet have `STATUS` stuck at `0x04` indefinitely with no input reaching the target. See [§State Machine](#state-machine) for the transition rule and [§Divergences](#divergences-from-the-datasheet) for the comparison with the datasheet.

> **Diagnostic — `STATUS` stuck at `0x04`.** If the LC-side handshake completes (PIDs ack'd, state 1 entered) but `STATUS` persists at `0x04` and `LED` persists at `0xFF`, the protocol negotiation is healthy and the issue is downstream of the UART link. The most common cause is a single-DM/DP-port board where the target cable is plugged into the unwired port — the board used for these captures has two USB-A ports but only one wired DM/DP pair, and only the wired port reaches `STATUS=0x07`. Confirmed by swapping ports: LC frames were byte-identical, but `STATUS` never moved off `0x04` on the wrong port. Identify the correct port empirically: the one where `STATUS` reaches `0x07` and the on-board LEDs mirror host NumLk/CapsLk/ScrLk state.

---

## Attach Sequence Timeline

LC→UC and UC→LC frames from a bidirectional state-0/1 capture ([gist](https://gist.github.com/sjmf/c1412b40e38f44738278c52416d5c0a9)), expressed as deltas from the first `0x86`. Times are observational and will vary between runs.

```
t=0.000   LC → UC   57 AB 86                         attach
t=0.260   LC → UC   57 AB 80 FF                      startup status (1/2)
t=0.470   LC → UC   57 AB 80 FF                      startup status (2/2)
t=0.470   LC → UC   57 AB 82 A3                      heartbeat begins
t=0.500   UC → LC   57 AB 12 00 00 00 00 ...         keep-alive (~30 ms after 2nd 0x80 FF; no PIDs)
t=1.440   LC → UC   57 AB 89                         status announce (1/3)
t=1.490   LC → UC   57 AB 81 00 4A 00 [DESC] [PID]   mouse Device Connection
t=1.550   LC → UC   57 AB 81 01 A5 00 [DESC] [PID]   keyboard Device Connection
t=2.490   UC → LC   57 AB 12 40 00 00 00 ...         keep-alive (mouse PID ack)
t=3.530   LC → UC   57 AB 89                         status announce (2/3)
t=3.580   LC → UC   57 AB 81 01 A5 00 [DESC] [PID]   keyboard Device Connection (retransmit)
t=4.520   UC → LC   57 AB 12 40 00 03 15 ...         keep-alive (both PIDs ack) ← state 1
t=5.570   LC → UC   57 AB 89                         status announce (3/3 — last observed)
t=...     LC → UC   57 AB 83 [LEN] [SER] [...]       key/mouse frames (state 1)
```

After both `P1` and `P2` in the UC's keep-alive match the `PID` values the LC sent in `0x81`, the LC switches CMD from `0x88` (state 0) to `0x83` (state 1). All subsequent key/mouse frames use the paired form.

## Disconnect Sequence

When a USB device is unplugged from the LC mid-session, only a single bare `0x86` is emitted; no other frames accompany it. Heartbeats continue at their normal cadence. From a capture with the mouse unplugged first and the keyboard ~2 s later:

```
... key/mouse frames, then idle ...
LC → UC   57 AB 82 A3        heartbeat (1 s cadence)
LC → UC   57 AB 86            ← mouse unplugged (no follow-up frames)
LC → UC   57 AB 82 A3        heartbeat (cadence unchanged)
LC → UC   57 AB 86            ← keyboard unplugged (no follow-up frames)
LC → UC   57 AB 82 A3        heartbeat (cadence unchanged)
... heartbeats only thereafter ...
```

The interval between the two `0x86` frames in this capture (~2 s) reflects the operator's actions, not any protocol timer. The UC's `0x12` keep-alive does **not** zero its `P1`/`P2` PID slots after disconnect on the LC's USB-host side — it continues to report the last-known PIDs at its normal ~1 s cadence. The LC also remains in state 1 (CMD `0x83`) and does not revert to state 0.

### Re-attach on the UC's USB-device side (target replug)

When the UC's *target-PC* USB cable is unplugged and re-plugged (a different event from an LC-side peripheral disconnect), the UC's `0x12` does react: `P1`/`P2` clear to `00 00` for one or two frames during the transient, `STATUS` flashes `0xFF`, then PIDs settle back to their previous values but `STATUS` remains at `0x04` until the LC drives a re-enumeration.

To get `STATUS` back to `0x07` (i.e. devices re-enumerated on the target host), the LC must replay the **full** attach sequence (`0x86 → 0x80 0xFF ×2 → 0x89 → 0x81 ×N`). Retransmitting `0x81` alone is insufficient — the UC accepts the descriptors and reflects the PIDs in `0x12`, but does not re-present its USB-device side to the target host. Validated by the PoC's `_run_attach_sequence(wait_for_uc=False)` reattach trigger.

---

## State Machine

```
  USB device attached on LC
         │
         ▼
    ┌─────────┐    UC keep-alive shows         ┌─────────┐
    │ State 0 │    P1==mouse_pid AND           │ State 1 │
    │  SOLO   │ ─────────────────────────────▶ │ PAIRED  │
    │         │    P2==kbd_pid                 │         │
    └─────────┘                                └─────────┘
    CMD = 0x88                                 CMD = 0x83
```

State 0 (`0x88`) is the unpaired form; state 1 (`0x83`) is the paired form. The CMD byte switches; the frame payload is identical. Heartbeats run at ~1 s cadence in both states. **Transition trigger:** the UC's `0x12` keep-alive must reflect every PID the LC announced via `0x81` in its `P1`/`P2` fields — receiving any single `0x12` is *not* sufficient. See [§Divergences](#divergences-from-the-datasheet) for how this differs from the datasheet's wording.

---

## Labeling Byte (SER)

`SER` (the byte after `LEN` in `0x83`/`0x88` frames) is a packed bitfield encoding device class, USB protocol mode, and port number. Per CH9350 datasheet §4.3:

| Bit | Meaning |
|-----|---------|
| 7, 6, 3 | Reserved |
| 5, 4 | Device class — `01` = keyboard, `10` = mouse, `11` = multimedia, `00` = other |
| 2, 1 | Protocol — `01` = HID, `10` = BIOS, `00` = Unknown, `11` = reserved |
| 0 | Port — `0` = port 1 (DP/DM), `1` = port 2 (HP/HM) |

Decoded examples of observed values:

| SER | Bits 5,4 | Bits 2,1 | Bit 0 | Decode |
|-----|----------|----------|-------|--------|
| `0x11` | 01 (kbd) | 00 (unknown) | 1 (port 2) | Real boot keyboard, port 2 |
| `0x13` | 01 (kbd) | 01 (HID) | 1 (port 2) | HID keyboard, port 2 |
| `0x20` | 10 (mouse) | 00 (unknown) | 0 (port 1) | Real boot mouse, port 1 |
| `0x22` | 10 (mouse) | 01 (HID) | 0 (port 1) | HID mouse, port 1 |
| `0x23` | 10 (mouse) | 01 (HID) | 1 (port 2) | HID mouse, port 2 |

Empirically the UC accepts `Unknown`-protocol values (bits 2,1 = 00) and forwards them correctly, despite the datasheet implying only HID/BIOS are valid.

> **Interpretation (USB HID).** These bits likely map to USB HID's two `SET_PROTOCOL` modes:
> - `HID` (`01`) → Report Protocol → frame carries an `RID` byte after SER (LEN = `0x0C` keyboard, `0x0A`/`0x08` mouse).
> - `BIOS` (`10`) → Boot Protocol → fixed-layout 8-byte keyboard / 3-byte mouse report, no `RID`.
> - `Unknown` (`00`) → device classified as neither (no Report ID item in its descriptor, no boot interface advertised); the UC handles it as fixed-layout, hence the `RID`-less LEN = `0x0B` / `0x07` variants.
>
> This is consistent with the data but has not been verified against a device that explicitly advertises HID Boot Protocol (`bInterfaceSubClass = 0x01`).

---

## States 2/3/4 (Alternative Dipswitch Configurations)

States 2, 3 and 4 are simpler modes that bypass the descriptor-exchange handshake: the UC presents fixed **built-in** HID descriptors to the target host, and the LC forwards HID reports as fixed-length frames. The three modes differ only in *what built-in descriptor the UC advertises*; the LC-side UART protocol is essentially identical between states 3 and 4. All three are selected via the `S1`/`S0` dipswitches on **both** ends (SEL still selects LC vs UC role); BAUD pins still control baud rate independently:

| S1 | S0 | State | UC built-in HID interfaces (datasheet §3.3–3.5) |
|----|----|-------|-------------------------------------------------|
| HIGH | HIGH | 0/1 (default) | None — descriptor sent over UART via `0x81` |
| HIGH | LOW | 2 | BIOS keyboard + **relative** mouse |
| LOW | HIGH | 3 | BIOS keyboard + **absolute** mouse |
| LOW | LOW | 4 | BIOS keyboard + **HID Digitizers** (replaces abs mouse for multi-monitor) |

The "BIOS keyboard" wording comes straight from the datasheet (§3.3 et seq.) and means a USB HID Boot-protocol keyboard — the kind a PC's BIOS/UEFI accepts before any OS-level HID drivers load. The mouse semantics, however, differ between the three modes, and that determines which mode is appropriate for which environment:

- **State 2 — legacy / pre-boot.** BIOS keyboard + *relative* mouse. This is the right choice for BIOS setup, boot menus, recovery consoles, and UEFI CSM environments, where the boot mouse protocol only understands relative motion. States 3 and 4 will not enumerate in those environments because their absolute-mouse / HID-Digitizers descriptors fall outside the boot protocol.
- **State 3 — modern OS, no handshake, abs mouse.** BIOS keyboard + absolute mouse. Useful when the descriptor-exchange handshake of state 0/1 isn't available (e.g. minimal embedded LC firmware) but absolute-cursor positioning is wanted. Most modern OSes (Linux, macOS, Windows) accept the abs-mouse interface.
- **State 4 — Windows multi-monitor.** **The defining feature of state 4 is that the UC identifies on the target USB bus as a HID Digitizer** (the same device class as a graphics tablet / pen input), not as a regular mouse. That's the entire point of state 4's existence: the chip exposes a different USB device class so the host OS routes pointer reports through its digitizer/pen pipeline rather than its mouse pipeline. The HID Digitizers class itself is widely supported (Linux `hid-multitouch`, macOS, Android, iOS, Windows all parse the descriptors), but **how the OS routes those reports is implementation-dependent.** On Windows 7+, digitizer abs-coords map cleanly to the full virtual desktop spanning multiple monitors — solving the limitation that a plain abs-mouse only addresses the primary monitor. On Linux, macOS, and other targets, a digitizer report may land in a tablet/pen input pipeline rather than driving the system cursor, depending on the desktop environment and its input stack. The datasheet's terse §3.5 caveat — *"some systems do not support HID Digitizers devices"* — is best read as "OS routing of digitizer events to the cursor varies; verify on your target" rather than as a strict OS allowlist. State 3 (UC identifies as a regular HID Mouse with absolute coords) is the safer default for plain cursor-positioning KVM use.

### LC → UC fixed-length frames

| CMD | Frame | Used in | Description |
|-----|-------|---------|-------------|
| `0x01` | `57 AB 01` + 8-byte HID boot keyboard report | 2, 3, 4 | Keyboard |
| `0x02` | `57 AB 02 [btn] [dx] [dy] [wheel]` | 2 only | Relative mouse |
| `0x04` | `57 AB 04 [id] [btn] [XL] [XH] [YL] [YH] [wheel]` | 3, 4 | Absolute mouse — `id`=`0x01`, X/Y as 16-bit LE |
| `0x10` | `57 AB 10 [VID_LO] [VID_HI] [PID_LO] [PID_HI]` | 2, 3, 4 | VID/PID modification (datasheet §3, p.9): override the UC's USB descriptor identity |

Verified empirically across all three modes by bidirectional sniff: [state-2 gist](https://gist.github.com/sjmf/9bf8975412ecbb0985bd4e5c549a915d), [state-3/4 gist](https://gist.github.com/sjmf/5a3fd16fbe81668eddacb0fb4951e09b).

**Common to all three modes (2, 3, 4):**

- **Startup announce.** The LC emits `0x86 → 0x80 0xFF → 0x89 → 0x80 0xFF` at attach, identical to state 0/1 but with **no `0x81` Device Connection frames** — the UC has built-in descriptors and does not need them.
- **UC keep-alive (`0x12`) flows.** Within ~250 ms of the startup announce, the UC begins emitting `0x12` keep-alives at ~1 s cadence and `STATUS` reaches `0x07`. `P1`/`P2` stay at `0000` for the entire session (no descriptor announce, nothing to ack), confirming that `STATUS` bits are gated on USB-side enumeration on the target, **not** on PID-ack.
- **`0x80 0x3N` LED-feedback channel** from LC → UC during operation, mirroring the host's keyboard LED state back to the source keyboard. Example: pressing CapsLk → LC emits `01 00 00 39 ...` → UC responds with `12 ... led=0x02` → LC echoes `80 32`; on release the LC drops back to `80 30`.
- **Per-keystroke retransmit.** Each key event produces 3–4 repeated frames on the wire (no SER, no counter, no checksum, so the LC cannot detect loss — it just retransmits).

**State 2 (relative mouse):**

- **Mouse `0x02` format verified.** `57 AB 02 [btn] [dx] [dy] [wheel]` with signed 8-bit dx/dy (two's complement). The LC emits up to ~7 frames per ~50 ms burst during continuous motion — higher rate than keyboard, with no retransmit padding (a dropped sample is masked by the next).
- **Idle keyboard reports during mouse activity.** With both a keyboard and mouse plugged into the LC, continuous mouse motion produces occasional `57 AB 01 00 00 00 00 00 00 00 00` frames (no key pressed) interleaved with mouse frames. They appear only during active mouse traffic — not during keyboard-only typing or steady-state idle. Most likely the LC's USB host poll cycle reads both endpoints together and emits the keyboard endpoint's "no change" report alongside each batch of mouse reports.
- **State 2 silently drops absolute mouse.** Plugging a CH9329 (abs-mouse + keyboard composite) into the LC in state 2: keyboard reports forwarded via `0x01`, but no `0x04` frames ever appeared on the wire and abs-mouse coordinates were silently dropped. The link was healthy throughout (`STATUS=0x07`); the LC simply has no destination for abs-mouse reports because the UC's state-2 built-in descriptor is relative-only. Switching to state 3 or 4 fixes this.

**States 3 and 4 (absolute mouse):**

- **No `0x02` frames on the wire** — only `0x04`. State-2 relative-mouse and state-3/4 absolute-mouse modes are mutually exclusive.
- **`0x04` format verified.** `57 AB 04 0x01 [btn] [XL XH] [YL YH] [wheel]` — 7-byte payload after the cmd byte; `id=0x01` is a fixed report-ID prefix; X/Y are 16-bit little-endian.
- **The LC integrates relative motion into absolute coordinates** when the source device is a relative-motion mouse. So states 3/4 force absolute-mouse semantics on the target regardless of what the source device reports.
- **States 3 and 4 are indistinguishable at the UART layer** because the choice between them is made on the UC, not the LC. The UC reads its own dipswitch and selects which built-in descriptor to advertise to the target — HID Mouse for state 3, HID Digitizers for state 4 — without any signalling from the LC. The LC just emits `0x04` abs-coordinate frames either way, and the UC routes them to whichever of its built-in descriptors is active. From an implementation perspective, **states 3 and 4 share the same LC code path**; the operator picks between them via dipswitches on the UC based on what the target host supports.
- **Sustained frame stream required for cursor motion.** A real LC emits `0x04` frames at ~50 ms intervals during continuous motion (typically hundreds of frames over a few seconds, with sub-pixel deltas rolled forward into each next frame). An emulator that fires one isolated `0x04` per command does *not* produce visible cursor movement on the target — even though the target's USB host controller still receives the report (the screen un-dims, indicating the OS sees activity). The likely mechanism is that HID Digitizers / abs-mouse drivers require a sustained stream to treat reports as active input rather than as glitches; isolated reports wake the bus but do not update the cursor. The PoC's REPL `m X Y` issues one frame per command and reproduces this "screen wakes, cursor doesn't move" symptom; an LC integration that wants S3/4 cursor motion must emit a continuous burst per move event, mimicking the real LC's poll-driven cadence.

---

## Divergences from the datasheet

The CH9350 V2.3 datasheet is broadly accurate but in several places contradicts what a real CH9350L LC actually emits on the wire. The captures referenced below were all taken against a known-working hardware setup (real LC + USB keyboard + USB mouse, paired with a real UC that successfully forwarded HID input to a target PC).

### `0x86` is fired at both attach and disconnect, and the UC does not reset

- **Datasheet (§4.6 "Device Disconnect Command"):** *"The lower computer will send the command when it detects the device is removed, and the upper computer will reset the chip when it receives the command."*
- **Observed (attach):** `0x86` is the **first** frame the LC emits after a USB device is plugged in, followed by `0x80 0xFF` ×2, heartbeats, `0x89`, and one `0x81` per device.
- **Observed (disconnect):** the LC emits a *bare* `0x86` per device unplugged, with no follow-up frames. The opcode is the same in both contexts; the presence or absence of subsequent `0x80`/`0x89`/`0x81` frames is what disambiguates.
- **No chip reset:** after both devices are disconnected, the UC's `0x12` keep-alive continues at its normal cadence with its previously-learned PIDs in the `P1`/`P2` slots. Whatever "reset" the datasheet refers to is internal to the UC and not visible from the LC side.

### `0x80` is used in every state, not only state 2/3/4

- **Datasheet (§4.8 "Status Change Command"):** *"State 2/3/4 supports this command, which is sent by the lower computer, received by the upper computer and has response."*
- **Observed in state 0/1:** `0x80 0xFF` is sent twice (~210–260 ms apart) at attach time, immediately after `0x86`. The `0xFF` payload means "LED state unknown" (pre-enumeration default).
- **Observed in states 2/3/4:** the same `0x80 0xFF` startup pair, plus a recurring `0x80 0xNN` LED-feedback channel during operation (`NN = 0x30 | LED_BITS`). The datasheet's "Status Change Command" naming is consistent with this LED-feedback role; the datasheet is wrong that the opcode is *exclusive* to states 2/3/4.

### `0x89` is not defined in the datasheet at all

- **Datasheet:** no entry for `0x89`.
- **Observed:** sent 3 times at ~2 s intervals during the descriptor-announce phase in state 0/1, and once at startup in states 2/3/4 (where there is no descriptor announce). Not seen during steady-state operation, typing, mouse movement, or disconnect.

### `0x81` is sent at attach in state 0, not on "device property mismatch" in state 1

- **Datasheet (§4.1 "Device Connection Frame"):** *"State 1 in lower computer mode will send the data frame when a device property mismatch is detected."*
- **Observed:** the LC sends `0x81` at attach time **while still in state 0** (CMD `0x88`). The frame is not a recovery mechanism; it is the primary means by which the LC tells the UC what HID descriptors to advertise to the target PC. State-1 transition happens *after* the UC acknowledges the descriptor (see below).

### `0x81` field naming: leading byte = port, trailing 2 bytes = PID

- **Datasheet (§4.1):** describes the frame as `0x57 0xAB 0x81 [1-byte ID] [2-byte Payload length] [Payload] [2-byte ID] [1-byte parity check]`. The two `ID` fields are not given distinct names.
- **Observed:** the leading 1-byte `ID` selects the USB port (`0x00` = port 1 / DP-DM, `0x01` = port 2 / HP-HM). The trailing 2-byte `ID` is the device PID and is reflected verbatim into the UC's `0x12` keep-alive in the corresponding `PID-port1` / `PID-port2` slot once the descriptor is processed. This document calls them `PORT` and `PID` for clarity.

### State-1 transition is PID-ack, not first `0x12`

- **Datasheet (§3.2):** *"When CH9350L is used in pairs, it switches from state 0 to state 1."* — implies a single-event transition.
- **Common prior assumption** (in earlier versions of this document and in the PoC): receiving any `0x12` from the UC is the trigger.
- **Observed:** the UC sends `0x12` keep-alives starting ~30 ms after the second `0x80 0xFF`, well before any `0x81` has been sent — and continues sending them with `00 00` PIDs until each `0x81` is processed. The LC does not transition to state 1 (CMD `0x83`) until the UC's `0x12` reflects **every** PID the LC has announced via `0x81`. This was proven by bidirectional capture: with two devices announced, the LC stayed in state 0 until both `P1` and `P2` were populated in the UC's keep-alive.
- **Interpretation (USB HID):** this is the natural ordering rule for a composite HID device — INPUT reports for any interface cannot be safely forwarded until *all* configured interfaces have completed enumeration on the target host. The PID-ack gate is the LC's mechanism for waiting on that.

### Labeling byte: "Unknown" protocol bits are valid

- **Datasheet (§4.3):** documents bits 2,1 as `01 = HID, 10 = BIOS, 00 = Unknown, 11 = reserved`, implying only HID/BIOS are usable.
- **Observed:** SER values `0x11` (kbd / Unknown / port 2) and `0x20` (mouse / Unknown / port 1) are routinely sent by a real LC for keyboards and mice whose USB descriptors lack a `Report ID` item, and the UC forwards them correctly. The "Unknown" classification is a normal operating mode, not an error condition.

### Mouse frame variant LEN = `0x08` not documented

- **Datasheet (§4.3):** documents only the LEN=`0x0A` (CH9329 absolute, with report ID) and LEN=`0x07` (boot relative, no report ID) mouse frame formats.
- **Observed:** a third variant exists — LEN=`0x08`, SER=`0x22`, with a `Report ID` byte preceding the 4-byte boot mouse data. This is what the LC emits when the connected USB mouse has a Report Descriptor that includes a `Report ID` item but uses standard relative coordinates.

---

## Reference Implementation

`ch9350_poc.py` ([gist](https://gist.github.com/sjmf/c4329fd27e403a264648bf4e7744655a)) reproduces the attach sequence and emits matching `0x81` frames using HID Report Descriptors captured byte-for-byte from a real CH9350L LC. Frame *content* is byte-identical to what a real LC emits; frame *timing* (heartbeat / `0x89` cadence, inter-frame gaps) is approximate. For the curious, the reverse-engineering process for each stage of the protocol is described in more detail on [issue #13](https://github.com/sjmf/kvm-serial/issues/13).
