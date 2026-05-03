# CH9350L UART Protocol Specification

> **Status:** empirically verified by bidirectional bus sniffing (2026-05-03).
> Frames in this document have been observed on the wire and the
> reference implementation (`ch9350_poc.py`) reproduces them exactly,
> including byte-for-byte matching of the `0x81` Device Connection Frames.
> Coverage now includes power-on, attach, key/mouse forwarding, steady-state
> operation, and runtime disconnect.
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
57 AB 12 [P1_LO] [P1_HI] [P2_LO] [P2_HI] [LED] [STATUS] [VERSION_LO] [VERSION_MID] [VERSION_HI]
```

Total frame length: 11 bytes.

| Field | Size | Notes |
|-------|------|-------|
| `P1` | 2B LE | PID of port 1 — populated from the `PID` field of the LC's `0x81` frame for port 1, once accepted |
| `P2` | 2B LE | PID of port 2 — populated similarly for port 2 |
| `LED` | 1B | keyboard LED state: bit 0 = Num Lock, bit 1 = Caps Lock, bit 2 = Scroll Lock |
| `STATUS` | 1B | `0x07` typical |
| `VERSION` | 3B | `AC 20` typical (last byte varies) |

The `P1`/`P2` fields start as `00 00` after power-on and progressively populate as the UC processes each `0x81` frame. The LC uses this to confirm that the UC has accepted its descriptors before transitioning to state 1.

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

The interval between the two `0x86` frames in this capture (~2 s) was set by user action, not by the protocol. The UC's `0x12` keep-alive does **not** zero its `P1`/`P2` PID slots after disconnect — it continues to report the last-known PIDs at its normal ~1 s cadence. The LC also remains in state 1 (CMD `0x83`) and does not revert to state 0. Re-attach behaviour after disconnecting both devices was not captured and is not yet documented.

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

---

## State 2 Mode (Alternative Dipswitch Configuration)

When the UC dipswitch is set to `S0=LOW, S1=HIGH`, the UC enters a simpler mode that accepts unframed fixed-length reports with no pairing or counter. This mode requires no handshake.

| CMD | Frame | Description |
|-----|-------|-------------|
| `0x01` | `57 AB 01` + 8-byte HID boot keyboard report | Keyboard |
| `0x02` | `57 AB 02 [btn] [dx] [dy] [wheel]` | Relative mouse |
| `0x04` | `57 AB 04 [id] [btn] [XL] [XH] [YL] [YH] [wheel]` | Absolute mouse |

> **Note:** State 2 frames have not been verified empirically; they are documented from the CH9350L datasheet and the PoC implementation only. This is future work.

---

## Divergences from the datasheet

The CH9350 V2.3 datasheet is broadly accurate but in several places contradicts what a real CH9350L LC actually emits on the wire. All bidirectional captures referenced below were taken on 2026-05-03 against a known-working hardware setup (real LC + USB keyboard + USB mouse, paired with a real UC that successfully forwarded HID input to a target PC).

### `0x86` is fired at both attach and disconnect, and the UC does not reset

- **Datasheet (§4.6 "Device Disconnect Command"):** *"The lower computer will send the command when it detects the device is removed, and the upper computer will reset the chip when it receives the command."*
- **Observed (attach):** `0x86` is the **first** frame the LC emits after a USB device is plugged in, followed by `0x80 0xFF` ×2, heartbeats, `0x89`, and one `0x81` per device.
- **Observed (disconnect):** the LC emits a *bare* `0x86` per device unplugged, with no follow-up frames. The opcode is the same in both contexts; the presence or absence of subsequent `0x80`/`0x89`/`0x81` frames is what disambiguates.
- **No chip reset:** after both devices are disconnected, the UC's `0x12` keep-alive continues at its normal cadence with its previously-learned PIDs in the `P1`/`P2` slots. Whatever "reset" the datasheet refers to is internal to the UC and not visible from the LC side.

### `0x80` is used in state 0/1, not just 2/3/4

- **Datasheet (§4.8 "Status Change Command"):** *"State 2/3/4 supports this command, which is sent by the lower computer, received by the upper computer and has response."*
- **Observed:** `0x80 0xFF` is sent twice (~210–260 ms apart) at attach time in state 0/1, immediately after `0x86`. The `0xFF` payload's exact semantics are not yet decoded.

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
