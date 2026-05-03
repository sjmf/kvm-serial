# CH9350L UART Protocol Specification

> **Status:** empirically verified by bidirectional bus sniffing (2026-05-03).
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

The dipswitch-selectable `SEL` pin on each module determines its role: `SEL=1` → lower computer, `SEL=0` → upper computer.

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

| CMD | Payload format |
|-----|----------------|
| `0x83`, `0x88` | `[LEN] [SER] [report-bytes...] [CTR] [CTR_SUM]` — length-prefixed |
| `0x81` | `[PORT] [LEN_LO LEN_HI] [DESCRIPTOR] [PID_LO PID_HI] [CHK]` — 16-bit length-prefixed |
| `0x82`, `0x12`, `0x80`, `0x86`, `0x89` | Fixed length |
| `0x01`, `0x02`, `0x04` | State-2 fixed-length frames (alternative mode) |

### Length-prefixed key/mouse frames (CMD `0x83` / `0x88`)

```
57 AB [CMD] [LEN] [SER] [report-bytes...] [CTR] [CTR_SUM]
```

- **LEN** — number of bytes following LEN, i.e. `SER(1) + report-bytes(n) + CTR(1) + CTR_SUM(1)`
- **SER** — labeling byte; encodes device class, protocol, and port number (see §Labeling Byte)
- **CTR** — monotonically increasing session counter, mod 256; separate per SER
- **CTR_SUM** — checksum: `(CTR + sum(report-bytes)) mod 256`
  where `report-bytes` is everything between SER and CTR, exclusive

CMD `0x88` is used in state 0 (unpaired); CMD `0x83` is used in state 1 (paired). The frame payload format is identical between the two CMDs.

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

No payload. In both bidirectional captures (2026-05-03) the LC emitted exactly **3 instances** of `0x89` at ~2 s intervals starting ~1.4 s after the first `0x86`, then stopped — no further `0x89` was observed for the remainder of either ~30 s capture, including across active typing, mouse movement, and disconnect. The function is not fully decoded; the timing suggests it is tied to the attach/announce phase, but two captures is too small a sample to assert this generalises to all sessions. The UC continues normal operation in `0x89`'s absence.

### Device Connection Frame — CMD `0x81`

Sent by the LC at attach time, once per connected USB device. Carries the device's HID Report Descriptor; the UC uses these to construct matching HID descriptors that it will advertise to the target PC over USB. **Without `0x81` frames the UC enumerates a default device whose report-ID layout does not match the LC's `0x83`/`0x88` frames, and all input is dropped on the target.**

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

The descriptor is a standard USB HID Report Descriptor in the format defined by the USB-IF HID specification (Usage Page, Usage, Collection, Report ID, etc.). The captured mouse and keyboard descriptors used by the reference implementation are 74 and 165 bytes long respectively. The mouse descriptor contains a single `Report ID` item (`0x01`); the keyboard descriptor contains three (`0x01` keyboard, `0x02` system control, `0x03` consumer control). Only `Report ID 0x01` was observed as the `RID` byte in `0x83`/`0x88` frames in the captures; behaviour for the other report IDs is not yet exercised.

In both captures the LC retransmitted the keyboard `0x81` frame ~2 s after its first transmission, while the UC's `0x12` keep-alive still showed the keyboard PID slot as `00 00`. Whether the retransmit is purely time-driven or specifically gated on the missing ack cannot be distinguished from the available data — only one retransmit event was observed per capture and in both the ack arrived shortly afterward.

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

Three variants observed, distinguished by LEN and SER.

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

Produced by a real mouse on **port 1** whose descriptor contains a Report ID. Captured 2026-05-03.

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

Emitted by the LC on USB device events. The same opcode is used for both **attach** and **disconnect**; the differentiator is what follows:

- **Attach:** `0x86` is the first frame, followed by `0x80 0xFF` (×2), heartbeats, `0x89`, and one `0x81` Device Connection Frame per attached device.
- **Disconnect:** a *bare* `0x86` with no follow-up frames (no `0x80`, no `0x81`). One `0x86` per device removed; LC continues heartbeating normally afterward.

The datasheet (§4.6) names this "Device Disconnect Command" and claims the UC "will reset the chip when it receives the command." On the wire neither claim is fully accurate: (a) the same opcode fires at attach time, and (b) the UC's `0x12` keep-alive continues uninterrupted with its previously-learned PIDs even after both devices have been unplugged — no externally-visible reset occurs.

### Other Startup Opcodes (LC → UC)

| CMD | Payload | Role |
|-----|---------|------|
| `0x80` | 1 byte (`0xFF` observed, twice) | Sent twice ~210–260 ms apart, after the attach `0x86`. Function not fully decoded. State-2/3/4 only per datasheet §4.8, but observed in state 0/1. |
| `0x89` | — | First instance ~1 s after `0x80`; observed firing ~3 times at ~2 s intervals during the descriptor-announce phase, then stopping once forwarding begins. Not in datasheet. |

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
| `VERSION` | 2B | `AC 20` typical (last byte alternates `0B`/`20`) |

`STATUS` byte interpretation (empirical, 2026-05-03):

| Bit | Mask | Meaning |
|-----|------|---------|
| 0 | `0x01` | Port-0 device enumerated on target USB host |
| 1 | `0x02` | Port-1 device enumerated on target USB host |
| 2 | `0x04` | UART link healthy / UC alive |

Common values:
- `0x07` — both devices live on target, HID forwarding works (the only "all green" state)
- `0x04` — UART up but target hasn't enumerated devices yet (e.g. cable in DM/DP-less port, or post-reattach before re-enumeration)
- `0xFF` — transient/error during cable yank
- `0x00` — pre-attach, before UC is fully up

The `P1`/`P2` fields start as `00 00` after power-on and progressively populate as the UC processes each `0x81` frame. The LC uses this to confirm that the UC has accepted its descriptors before transitioning to state 1.

> **State-1 entry is necessary but not sufficient for forwarding to work.** State-1 is gated on PID-ack (a UART-internal handshake — UC reflects PIDs once it has stored each `0x81`'s descriptor). It does **not** require any USB-device-side enumeration on the target. The proper "is HID actually being forwarded" indicator is `STATUS == 0x07`, not state-1 entry. A board with no DM/DP wiring, or a UC port that doesn't reach a target host, will still complete the UART-side handshake and reach state 1 — but `STATUS` will stay at `0x04` indefinitely and no input will land on a target.

> **Diagnostic.** If the LC-side handshake completes (PIDs ack'd, state 1 entered) but `STATUS` persists at `0x04` and `LED` persists at `0xFF`, the protocol negotiation is healthy and the issue is downstream of the UART link — typically wiring (cable plugged into a port without a DM/DP path), a board-mode dipswitch in the wrong position, or no target host actually attached on DM/DP. Verified 2026-05-03 by plugging the target USB cable into a board's HM/HP-only port: LC frames byte-identical to the working case, but `STATUS` never moves off `0x04`.

> **Single-DM/DP boards.** Many CH9350L breakout boards expose two USB-A ports but only wire DM/DP through to one of them. On such boards, the UC's USB-device cable to the target PC **must** be plugged into the port with the wired DM/DP pair — the other port will complete the UART handshake (state 1, PIDs ack'd) but `STATUS` will stay at `0x04` and no HID input will reach the target. Identify the correct port empirically: the one where `STATUS` reaches `0x07` and the on-board LEDs mirror host NumLk/CapsLk/ScrLk state.

> **Interpretation (USB HID).** The `LED` byte is the channel through which a USB HID OUTPUT report (host → keyboard, NumLk/CapsLk/ScrLk) reaches the LC so the physical keyboard's LEDs can be driven. This explains the cadence behaviour: when idle the UC has nothing new to forward and emits `0x12` at a steady ~1 s heartbeat; during typing the UC services more USB transactions on its target side and emits `0x12` more frequently. Each `0x83`/`0x88` keystroke from the LC also corresponds to an INPUT report consumed by the host on the UC side, which may produce `SET_REPORT` traffic the UC needs to forward.

---

## Attach Sequence Timeline

LC→UC and UC→LC frames from the bidirectional capture taken 2026-05-03 (sniff_lc.txt + sniff_uc.txt), expressed as deltas from the first `0x86`. Times are observational and will vary between runs.

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

When a USB device is unplugged from the LC mid-session, only a single bare `0x86` is emitted; no other frames accompany it. Heartbeats continue at their normal cadence. From sniff_lc2.txt (2026-05-03), with the user unplugging the mouse first and the keyboard ~2 s later:

```
... key/mouse frames, then idle ...
LC → UC   57 AB 82 A3        heartbeat (1 s cadence)
LC → UC   57 AB 86            ← mouse unplugged (no follow-up frames)
LC → UC   57 AB 82 A3        heartbeat (cadence unchanged)
LC → UC   57 AB 86            ← keyboard unplugged (no follow-up frames)
LC → UC   57 AB 82 A3        heartbeat (cadence unchanged)
... heartbeats only thereafter ...
```

The interval between the two `0x86` frames in this capture (~2 s) was set by user action, not by the protocol. The UC's `0x12` keep-alive does **not** zero its `P1`/`P2` PID slots after disconnect on the LC's USB-host side — it continues to report the last-known PIDs at its normal ~1 s cadence. The LC also remains in state 1 (CMD `0x83`) and does not revert to state 0.

### Re-attach on the UC's USB-device side (target replug)

When the UC's *target-PC* USB cable is unplugged and re-plugged (a different event from an LC-side peripheral disconnect), the UC's `0x12` does react: `P1`/`P2` clear to `00 00` for one or two frames during the transient, `STATUS` flashes `0xFF`, then PIDs settle back to their previous values but `STATUS` remains at `0x04` until the LC drives a re-enumeration.

To get `STATUS` back to `0x07` (i.e. devices re-enumerated on the target host), the LC must replay the **full** attach sequence (`0x86 → 0x80 0xFF ×2 → 0x89 → 0x81 ×N`). Retransmitting `0x81` alone is insufficient — the UC accepts the descriptors and reflects the PIDs in `0x12`, but does not re-present its USB-device side to the target host. Validated 2026-05-03 with the PoC's `_run_attach_sequence(wait_for_uc=False)` reattach trigger.

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

- In **state 0**, the LC sends heartbeats and key/mouse frames with CMD `0x88`.
- In **state 1**, CMD switches to `0x83`. Frame payload format is identical.
- The LC emits a heartbeat at ~1 s cadence in both states. `0x89` status announces appeared only during the attach phase in available captures (see [§Status Announce](#status-announce--cmd-0x89)).
- Receiving any `0x12` from the UC is **not sufficient** for state-1 transition — the UC must have acknowledged every `0x81` the LC sent (matching PIDs in P1/P2). This was previously believed to be a single-frame transition; bidirectional capture proved otherwise.

---

## Labeling Byte (SER)

`SER` (the byte after `LEN` in `0x83`/`0x88` frames) is a bitfield, not a free-form USB address. Per CH9350 datasheet §4.3:

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
| LOW | LOW | 4 | BIOS keyboard + abs mouse + **HID Digitizers** (multi-monitor) |

The "BIOS keyboard" wording comes straight from the datasheet (§3.3 et seq.) and means a USB HID Boot-protocol keyboard — the kind a PC's BIOS/UEFI accepts before any OS-level HID drivers load. The mouse semantics, however, differ between the three modes, and that determines which mode is appropriate for which environment:

- **State 2 — legacy / pre-boot.** BIOS keyboard + *relative* mouse. This is the right choice for BIOS setup, boot menus, recovery consoles, and UEFI CSM environments, where the boot mouse protocol only understands relative motion. States 3 and 4 will not enumerate in those environments because their absolute-mouse / HID-Digitizers descriptors fall outside the boot protocol.
- **State 3 — modern OS, no handshake, abs mouse.** BIOS keyboard + absolute mouse. Useful when the descriptor-exchange handshake of state 0/1 isn't available (e.g. minimal embedded LC firmware) but absolute-cursor positioning is wanted. Most modern OSes (Linux, macOS, Windows) accept the abs-mouse interface.
- **State 4 — Windows multi-monitor.** BIOS keyboard + abs mouse + HID Digitizers. Solves the Windows 7+ extended-screen problem where plain abs-mouse only addresses the primary monitor; HID Digitizers can address the full virtual desktop. Note from §3.5: *"some systems do not support HID Digitizers devices"* — non-Windows targets should usually pick state 3 instead.

### LC → UC fixed-length frames

| CMD | Frame | Used in | Description |
|-----|-------|---------|-------------|
| `0x01` | `57 AB 01` + 8-byte HID boot keyboard report | 2, 3, 4 | Keyboard |
| `0x02` | `57 AB 02 [btn] [dx] [dy] [wheel]` | 2 only | Relative mouse |
| `0x04` | `57 AB 04 [id] [btn] [XL] [XH] [YL] [YH] [wheel]` | 3, 4 | Absolute mouse — `id`=`0x01`, X/Y as 16-bit LE |
| `0x10` | `57 AB 10 [VID_LO] [VID_HI] [PID_LO] [PID_HI]` | 2, 3, 4 | VID/PID modification (datasheet §3, p.9): override the UC's USB descriptor identity |

Empirical capture (2026-05-03, bidirectional sniff with `S1=HIGH, S0=LOW` on both boards):

- **Startup announce still happens.** The LC emits `0x86 → 0x80 0xFF → 0x89 → 0x80 0xFF` at attach, identical to state 0/1 but with **no `0x81` Device Connection frames**. The UC has built-in descriptors and does not need them.
- **UC keep-alive (`0x12`) still flows.** Within ~250 ms of the LC's startup announce, the UC begins emitting `0x12` keep-alives at ~1 s cadence and `STATUS` reaches `0x07` (both ports enumerated on target). PIDs in `P1`/`P2` stay at `0000` for the entire session (no descriptor announce, nothing to ack), confirming `STATUS` bits are gated on USB-side enumeration on the target, **not** on PID-ack.
- **`0x80` is reused as a LED-feedback channel from LC → UC.** During operation the LC emits `0x80 0xNN` frames where `NN` is `0x30 | LED_BITS` — high nibble `3` is a fixed type marker, low nibble carries the same NumLk/CapsLk/ScrLk encoding as `0x12`'s LED byte. Example: pressing CapsLk causes the LC to emit `01 00 00 39 ...` (CAPS down) → UC responds with `12 ... led=0x02` → LC echoes `80 32`; on release the LC drops back to `80 30`. The "Status Change Command" name from datasheet §4.8 is a reasonable fit, and this is the mode in which it actually appears.
- **Per-keystroke retransmit.** Each key event produces 3–4 repeated frames on the wire (no SER, no counter, no checksum, so the LC cannot detect loss — it just retransmits).
- **Mouse `0x02` verified empirically (2026-05-03, mouse_lc.txt).** Format on the wire is exactly `57 AB 02 [btn] [dx] [dy] [wheel]` with signed 8-bit dx/dy (two's complement) and no counter/checksum. The LC emits up to ~7 frames per ~50 ms burst during continuous motion — much higher rate than keyboard, with no retransmit padding (a dropped sample is masked by the next one). Button and wheel bytes were 0 throughout the captured run; only dx/dy varied.
- **Idle keyboard reports interleaved with mouse activity.** With both a keyboard and mouse plugged into the LC, continuous mouse motion produces occasional `57 AB 01 00 00 00 00 00 00 00 00` frames (no key pressed) interleaved with mouse frames. They appear only during active mouse traffic and stop when the mouse stops — not seen during keyboard-only typing or steady-state idle. Most likely the LC's underlying USB host poll cycle reads both endpoints together and emits the keyboard endpoint's "no change" report alongside each batch of mouse reports.

**State 2 verified to drop absolute mouse.** 2026-05-03 (absmouse_lc.txt) plugged a CH9329 enumerated as a USB absolute-mouse + keyboard composite into the LC in state 2: keyboard reports forwarded via `0x01`, but no `0x04` frames ever appeared on the wire and abs-mouse coordinates were silently dropped. The link was healthy throughout (`STATUS=0x07`) — the LC simply has no destination for abs-mouse reports because the UC's state-2 built-in descriptor is relative-only. Switching the dipswitches to state 3 or 4 fixes this.

### State 3/4 verified empirically (2026-05-03, s3_lc.txt / s4_lc.txt)

States 3 and 4 are **on-the-wire identical to state 2 except they emit `0x04` absolute-mouse frames instead of (or alongside) `0x02` relative ones**:

- Same startup announce: `0x86 → 0x80 0xFF → 0x89 → 0x80 0xFF`. No `0x81`.
- Same UC `0x12` keep-alive cadence and `STATUS=0x07` semantics. PIDs stay `0000`.
- Same `0x80 0x3N` LED-feedback channel from LC → UC.
- Same per-keystroke retransmit pattern.
- **`0x04` frames empirically verified.** Format on the wire: `57 AB 04 0x01 [btn] [XL XH] [YL YH] [wheel]` — 7-byte payload after the cmd byte; `id=0x01` is a fixed report-ID prefix; X/Y are 16-bit little-endian.
- **Even with a relative-only physical mouse plugged into the LC**, the LC integrates the dx/dy deltas internally and emits absolute coordinates over the wire. So states 3/4 force absolute-mouse semantics on the target regardless of what the source device reports.

State 3 and state 4 captures look identical at the UART layer — confirming the datasheet: the difference is only in the UC's USB-side built-in descriptor (HID Mouse vs HID Digitizers), not in any LC→UC framing. From the kvm-serial implementation perspective, **states 3 and 4 share the same code path**; the user picks between them by physically setting the dipswitches based on what their target host supports.

---

## Divergences from the datasheet

The CH9350 V2.3 datasheet is broadly accurate but in several places contradicts what a real CH9350L LC actually emits on the wire. All bidirectional captures referenced below were taken on 2026-05-03 against a known-working hardware setup (real LC + USB keyboard + USB mouse, paired with a real UC that successfully forwarded HID input to a target PC).

### `0x86` is fired at both attach and disconnect, and the UC does not reset

- **Datasheet (§4.6 "Device Disconnect Command"):** *"The lower computer will send the command when it detects the device is removed, and the upper computer will reset the chip when it receives the command."*
- **Observed (attach):** `0x86` is the **first** frame the LC emits after a USB device is plugged in, followed by `0x80 0xFF` ×2, heartbeats, `0x89`, and one `0x81` per device.
- **Observed (disconnect):** the LC emits a *bare* `0x86` per device unplugged, with no follow-up frames. The opcode is the same in both contexts; the presence or absence of subsequent `0x80`/`0x89`/`0x81` frames is what disambiguates.
- **No chip reset:** after both devices are disconnected, the UC's `0x12` keep-alive continues at its normal cadence with its previously-learned PIDs in the `P1`/`P2` slots. Whatever "reset" the datasheet refers to is internal to the UC and not visible from the LC side.

### `0x80` is used in state 0/1 and state 2

- **Datasheet (§4.8 "Status Change Command"):** *"State 2/3/4 supports this command, which is sent by the lower computer, received by the upper computer and has response."*
- **Observed in state 0/1:** `0x80 0xFF` is sent twice (~210–260 ms apart) at attach time, immediately after `0x86`. The `0xFF` payload appears to mean "LED state unknown" (pre-enumeration default).
- **Observed in state 2:** in addition to the same `0x80 0xFF` startup pair, `0x80 0xNN` recurs during operation as a LED-feedback channel from LC → UC. The payload encodes `0x30 | LED_BITS` where the low nibble matches the NumLk/CapsLk/ScrLk encoding of `0x12`'s LED byte. This matches the datasheet's "Status Change Command" name and direction; the datasheet is correct that it operates in state 2, but wrong that it is *exclusive* to state 2/3/4.

### `0x89` is not defined in the datasheet at all

- **Datasheet:** no entry for `0x89`.
- **Observed:** in two attach captures, sent 3 times at ~2 s intervals starting ~1.4 s after the first `0x86`, then not seen again for the rest of either ~30 s capture (across typing, mouse movement, and disconnect). Whether `0x89` reappears in longer-running sessions has not been verified.

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

## Implementation in kvm-serial

The reference implementation in `ch9350_poc.py` reproduces the attach
sequence and emits matching `0x81` frames using captured HID Report
Descriptors. The mouse and keyboard descriptors built into the script
match the bytes captured from a real CH9350L LC at attach time, including
the trailing PID and checksum. The frame *content* is byte-identical to
what a real LC emits; frame *timing* (heartbeat / `0x89` cadence,
inter-frame gaps) is approximate and does not aim to match the real LC.
The UC accepts the resulting frames and forwards keys to the target PC
end-to-end, verified manually on 2026-05-03.
