# CH9329 UART Protocol Specification

> **Manufacturer datasheet:** WCH CH9329 V1.1 — [wch.cn](http://wch.cn). Pin and electrical
> parameter references in this document refer to that datasheet.
>
> **Reference implementation:** `kvm_serial/utils/ch9329.py` — originally derived from
> [beijixiaohu/CH9329_COMM](https://github.com/beijixiaohu/CH9329_COMM/).

---

## Overview

The CH9329 is a UART-to-USB-HID bridge chip. It presents itself on the target PC as a composite
USB device (keyboard + mouse + optional custom HID) and receives framed commands over a TTL
UART from the host controller — kvm-serial in this case. The protocol is entirely
**host-driven**: the host sends command frames and the chip executes them. There is no
handshake, no descriptor exchange, and no state machine to track.

kvm-serial uses Serial Communication **Mode 0** (Protocol Transmission mode, the default), which
requires all data to be sent as framed packets per the format below.

---

## Physical Layer

| Parameter | Value |
|-----------|-------|
| Baud rate | 9600 bps (default; configurable) |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |
| Logic level | 3.3 V or 5 V TTL |

Supported baud rates: 1200, 2400, 4800, 9600, 14400, 19200, 38400, 57600, 115200.
Note: 115200 bps is not supported when the chip operates at 3.3 V.

---

## Frame Structure

Every command is a single self-contained packet with the following layout:

```text
[HEAD_HI] [HEAD_LO] [ADDR] [CMD] [LEN] [DATA...] [SUM]
  0x57      0xAB     1B     1B    1B    LEN bytes   1B
```

| Field | Size | Description |
|-------|------|-------------|
| `HEAD` | 2B | Fixed magic header `0x57 0xAB` |
| `ADDR` | 1B | Device address — `0x00` by default; non-zero when multiple CH9329 chips share one UART bus |
| `CMD` | 1B | Command type — selects keyboard, absolute mouse, or relative mouse |
| `LEN` | 1B | Number of data bytes that follow (0–255) |
| `DATA` | LEN bytes | Payload — format is CMD-specific, described below |
| `SUM` | 1B | Checksum: `(sum(HEAD) + ADDR + CMD + LEN + sum(DATA)) mod 256` |

Maximum `LEN` is 255; a payload of 256 or more bytes causes an `OverflowError` in the
`len.to_bytes(1)` call before the packet is even sent.

### Checksum Worked Example

Keyboard frame for 'a' (`scancode = 0x04`):

```text
57 AB 00 02 08 00 00 04 00 00 00 00 00 10
```

- Header sum: `0x57 + 0xAB = 0x102`; modular carry is included in the final mod-256 step.
- `SUM = (0x57 + 0xAB + 0x00 + 0x02 + 0x08 + 0x00 + 0x00 + 0x04 + 0x00×5) mod 256`
- `= (0x102 + 0x0A + 0x04) mod 256 = 0x110 mod 256 = 0x10` ✓

---

## Commands

### Keyboard — CMD `0x02`

Sends an 8-byte USB HID boot-protocol keyboard report directly to the chip.

```text
57 AB [ADDR] 02 08 [mod] [rsvd] [k0] [k1] [k2] [k3] [k4] [k5] [SUM]
```

| Field | Size | Description |
|-------|------|-------------|
| `LEN` | `0x08` | Fixed — boot keyboard report is always 8 bytes |
| `mod` | 1B | Modifier bitmask (see below) |
| `rsvd` | 1B | Reserved — always `0x00` |
| `k0..k5` | 6B | USB HID usage IDs of currently held keys; zero-padded |

**Modifier byte bitmask:**

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

Sending `00 00 00 00 00 00 00 00` releases all keys (the `release()` call).

### Absolute Mouse — CMD `0x04`

```text
57 AB [ADDR] 04 07 02 [btn] [XL] [XH] [YL] [YH] [wheel] [SUM]
```

| Field | Value | Description |
|-------|-------|-------------|
| `LEN` | `0x07` | Fixed payload length |
| marker | `0x02` | Absolute-coordinate mode indicator |
| `btn` | 1B | Button bitmask — bit 0 = left, bit 1 = right, bit 2 = middle |
| `XL`/`XH` | 2B LE | X coordinate in the chip's 12-bit absolute space (0–4095) |
| `YL`/`YH` | 2B LE | Y coordinate in the chip's 12-bit absolute space (0–4095) |
| `wheel` | 1B signed | Scroll wheel delta, encoded as a signed byte (see §Signed Byte Encoding) |

**Coordinate scaling.** Source pixel coordinates are scaled into the chip's 12-bit space:

$$dx = \left\lfloor \frac{4096 \times x}{\max(1,\, width)} \right\rfloor$$

Negative coordinates (e.g. from multi-monitor setups where a pointer can be off-screen left/above
the primary display) wrap via `abs(4096 + dx)` rather than clamping, so motion remains continuous
across monitor boundaries.

### Relative Mouse — CMD `0x05`

```text
57 AB [ADDR] 05 05 01 [btn] [dx] [dy] [wheel] [SUM]
```

| Field | Value | Description |
|-------|-------|-------------|
| `LEN` | `0x05` | Fixed payload length |
| marker | `0x01` | Relative-coordinate mode indicator |
| `btn` | 1B | Button bitmask — same encoding as absolute mouse |
| `dx` | 1B signed | Horizontal delta (−127..+127) |
| `dy` | 1B signed | Vertical delta (−127..+127) |
| `wheel` | 1B signed | Scroll wheel delta (−127..+127) |

Out-of-range deltas are **clamped** (not wrapped) to the signed-byte limits.

---

## Signed Byte Encoding

All signed single-byte fields (`dx`, `dy`, `wheel`) use standard two's-complement encoding,
clamped to −127..+127 (not the full −128..+127 — the implementation deliberately excludes −128
to keep encoding unambiguous). Python's `int.to_bytes(1, signed=True)` encodes this directly.

| Decimal | Hex |
|---------|-----|
| +127 | `0x7F` |
| +1 | `0x01` |
| 0 | `0x00` |
| −1 | `0xFF` |
| −127 | `0x81` |

---

## Multi-Chip Addressing

The `ADDR` byte allows multiple CH9329 chips to share a single UART bus. Each chip can be
configured with a non-zero address; a frame is only acted on by the chip whose address matches.
`0x00` is the factory default and the value used by kvm-serial in all frames.

> **Note:** Multi-chip addressing on the same serial bus is not available in kvm-serial. Users
> requiring multiple device control can use multiple serial devices to interface to multiple chips.

---

## Operating Mode and Communication Mode

The chip's mode is set at hardware level via the `MODE0`/`MODE1` and `CFG0`/`CFG1` input pins
(pulled high by default → Mode 0 / Communication Mode 0).

| MODE1 | MODE0 | Operating Mode | USB Device Identity |
|-------|-------|---------------|---------------------|
| 1 | 1 | **0 (default)** | Composite: keyboard + mouse + custom HID |
| 1 | 0 | 1 | Keyboard only (no multimedia keys) |
| 0 | 1 | 2 | Keyboard + mouse (no custom HID) — recommended for Linux/macOS |
| 0 | 0 | 3 | Custom HID only (raw data passthrough) |

kvm-serial uses **Mode 0** (both pins high / floating). All three HID functions — keyboard,
absolute mouse, and relative mouse — are available simultaneously in this mode.

| CFG1 | CFG0 | Serial Communication Mode |
|------|------|--------------------------|
| 1 | 1 | **0 (default)** — Protocol Transmission (framed packets) |
| 1 | 0 | 1 — ASCII mode (printable characters only) |
| 0 | 1 | 2 — Transparent mode (raw 8-byte keyboard data) |

kvm-serial requires **Communication Mode 0**. ASCII and transparent modes are outside the scope
of this document.

---

## No Handshake Required

Unlike the CH9350L (which needs a descriptor handshake before forwarding input), the CH9329
acts on command frames immediately after USB enumeration completes. There are no startup frames
the host must send, no keep-alive to maintain, and no state machine to track. The chip's
`ACT#` output pin goes low once USB enumeration has succeeded, but kvm-serial does not monitor
this pin — it simply begins sending frames when the serial port is opened.

---

## Summary of Command Bytes

| CMD | Description | `LEN` | Payload |
|-----|-------------|-------|---------|
| `0x02` | Keyboard | `0x08` | `mod rsvd k0 k1 k2 k3 k4 k5` |
| `0x04` | Absolute mouse | `0x07` | `0x02 btn XL XH YL YH wheel` |
| `0x05` | Relative mouse | `0x05` | `0x01 btn dx dy wheel` |
