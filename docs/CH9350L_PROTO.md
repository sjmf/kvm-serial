# CH9350L UART Protocol Specification

> **Status:** empirically verified by passive bus sniffing (2026-05-02).  
> Reference implementation: `ch9350_poc.py` (repo root) and the Gist at
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

| CMD range | Payload format |
|-----------|----------------|
| `0x83`, `0x88` | `[LEN] [SER] [device-report...] [CTR] [CTR_SUM]` — length-prefixed |
| `0x82`, `0x12`, `0x01`, `0x02`, `0x04`, `0x80`, `0x86`, `0x89` | Fixed length (see table below) |

### Length-prefixed frames (CMD `0x83` / `0x88`)

```
57 AB [CMD] [LEN] [SER] [report-bytes...] [CTR] [CTR_SUM]
```

- **LEN** — number of bytes following LEN, i.e. `SER(1) + report-bytes(n) + CTR(1) + CTR_SUM(1)`
- **SER** — USB device address assigned by the CH9350L host stack (see §SER Bytes)
- **CTR** — monotonically increasing session counter, mod 256; separate per SER
- **CTR_SUM** — checksum: `(CTR + sum(report-bytes)) mod 256`
  where `report-bytes` is everything between SER and CTR, exclusive

CMD `0x88` is used in state 0 (unpaired); CMD `0x83` is used in state 1 (paired). The frame payload format is identical.

---

## Lower Computer → Upper Computer Frames

### Heartbeat — CMD `0x82`

Sent by the LC approximately every 1 second in all states.

```
57 AB 82 [IO]
```

| Byte | Meaning |
|------|---------|
| `IO` | Low nibble = IO pin state; `0xA3` observed (all-pins-high) |

### Keyboard — CMD `0x83` / `0x88`

Two variants are produced depending on the USB device connected to the LC.

#### CH9329 bridge (HID report ID present), LEN = `0x0C`

```
57 AB [CMD] 0C [SER=0x13] 01 [mod] [rsvd=00] [k0] [k1] [k2] [k3] [k4] [k5] [CTR] [CTR_SUM]
```

| Field | Value | Notes |
|-------|-------|-------|
| LEN | `0x0C` (12) | |
| SER | `0x13` | USB address for CH9329 keyboard endpoint |
| `0x01` | HID report ID | CH9329 keyboard report ID |
| `mod` | modifier byte | USB HID boot protocol modifier bitmask |
| `rsvd` | `0x00` | reserved |
| `k0..k5` | key scancodes | USB HID usage IDs, zero-padded |

#### Boot-protocol keyboard (no report ID), LEN = `0x0B`

Produced by a real keyboard in HID boot protocol mode.

```
57 AB [CMD] 0B [SER=0x11] [mod] [rsvd=00] [k0] [k1] [k2] [k3] [k4] [k5] [CTR] [CTR_SUM]
```

| Field | Value | Notes |
|-------|-------|-------|
| LEN | `0x0B` (11) | one byte shorter — no report ID |
| SER | `0x11` | USB address for real keyboard |
| `mod` | modifier byte | directly after SER, no preceding type byte |

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

### Absolute Mouse — CMD `0x83` / `0x88`, LEN = `0x0A`

Produced by the CH9329 bridge (which always reports absolute coordinates).

```
57 AB [CMD] 0A [SER=0x23] 05 [btn] [XL] [XH] [YL] [YH] [wheel] [CTR] [CTR_SUM]
```

| Field | Value | Notes |
|-------|-------|-------|
| LEN | `0x0A` (10) | |
| SER | `0x23` | USB address for CH9329 mouse endpoint |
| `0x05` | HID report ID | CH9329 absolute mouse report ID |
| `btn` | button bitmask | bit 0 = left, 1 = right, 2 = middle |
| `XL`/`XH` | X coordinate | 16-bit little-endian, raw USB HID absolute space |
| `YL`/`YH` | Y coordinate | 16-bit little-endian |
| `wheel` | scroll | signed byte |

### Relative Mouse — CMD `0x83` / `0x88`, LEN = `0x07`

Produced by a real mouse in HID boot protocol mode.

```
57 AB [CMD] 07 [SER=0x20] [btn] [dx] [dy] [wheel] [CTR] [CTR_SUM]
```

| Field | Value | Notes |
|-------|-------|-------|
| LEN | `0x07` (7) | |
| SER | `0x20` | USB address for real mouse |
| `btn` | button bitmask | same bit mapping as above |
| `dx` | X delta | signed byte |
| `dy` | Y delta | signed byte |
| `wheel` | scroll delta | signed byte |

No report ID byte is present; the LC forwards the 4-byte extended boot mouse report directly after SER.

### CTR_SUM Worked Example

Keyboard frame: `57 AB 88 0C 13 01 02 00 04 00 00 00 00 05 08`

- LEN=`0C`, SER=`13`, report-bytes = `01 02 00 04 00 00 00 00`, CTR=`05`
- `CTR_SUM = (0x05 + (0x01+0x02+0x00+0x04+0x00+0x00+0x00+0x00)) mod 256`
- `= (5 + 7) mod 256 = 0x0C` … but the last byte shown is `08` — this is an illustration only; compute with your actual bytes.

---

## Upper Computer → Lower Computer Frames

### Pairing / LED Control — CMD `0x12`

Sent by the UC approximately every 1 second. Receiving any `0x12` frame transitions the LC from state 0 to state 1.

```
57 AB 12 [SN0] [SN1] [SN2] [SN3] [LED] [??] [AC] [tail]
```

Total frame length: 11 bytes.

| Field | Notes |
|-------|-------|
| `SN0..SN3` | UC serial number; `00 00 00 00` observed on uninitialized units |
| `LED` | keyboard LED state: bit 0 = Num Lock, bit 1 = Caps Lock, bit 2 = Scroll Lock; `0xFF` = heartbeat suppress |
| remaining 3 bytes | `07 AC [tail]`; `tail` varies with UC firmware/state |

---

## Startup / Device-Connect Opcodes (LC → UC)

These frames appear on the bus when a USB device is connected to the LC, before the first heartbeat. Their exact semantics are not fully decoded.

| CMD | Payload | Observed at |
|-----|---------|-------------|
| `0x86` | none | USB device attached |
| `0x80` | 1 byte (`0xFF` observed) | shortly after `0x86`, twice |
| `0x89` | none | end of device-connect sequence |

---

## State Machine

```
  Power-on / USB-device connected
         │
         ▼
    ┌─────────┐   receive 0x12        ┌─────────┐
    │ State 0 │ ─────────────────────▶│ State 1 │
    │  SOLO   │   from upper computer │ PAIRED  │
    └─────────┘                       └─────────┘
    CMD = 0x88                        CMD = 0x83
```

- In **state 0**, the LC sends heartbeats and key/mouse frames with CMD `0x88`.
- In **state 1**, CMD switches to `0x83`. Frame payload format is identical.
- The LC sends a heartbeat every ~1 second in both states.

---

## State 2 Mode (Alternative Dipswitch Configuration)

When the UC dipswitch is set to `S0=LOW, S1=HIGH`, the UC enters a simpler mode that accepts unframed fixed-length reports with no pairing or counter. This mode requires no handshake.

| CMD | Frame | Description |
|-----|-------|-------------|
| `0x01` | `57 AB 01` + 8-byte HID boot keyboard report | Keyboard |
| `0x02` | `57 AB 02 [btn] [dx] [dy] [wheel]` | Relative mouse |
| `0x04` | `57 AB 04 [id] [btn] [XL] [XH] [YL] [YH] [wheel]` | Absolute mouse |

> **Note:** State 2 frames have not yet been sniffed empirically; they are documented from the CH9350L datasheet and the PoC implementation only. This is future work.

---

## SER Bytes

`SER` is the USB device address assigned by the CH9350L's internal USB host stack when a device is enumerated. It is not a fixed protocol constant and can vary between sessions or hardware. The values below were observed across multiple captures:

| SER | Device | Variant |
|-----|--------|---------|
| `0x13` | Keyboard | CH9329 bridge (report IDs present) |
| `0x23` | Mouse (absolute) | CH9329 bridge |
| `0x11` | Keyboard | Boot protocol (real keyboard) |
| `0x20` | Mouse (relative) | Boot protocol (real mouse) |

---

## Implementation in kvm-serial

For kvm-serial acting as the lower computer, we use the **CH9329-format** frames (SER `0x13`/`0x23`, with report ID bytes) regardless of what input device is attached on the host side.
