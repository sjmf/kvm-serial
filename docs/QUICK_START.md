# Quick Start Guide

Use this guide to get running with `kvm-serial` in ~10 minutes (excluding shipping).

---

## Shopping List
You will need some hardware to get going with `kvm-serial`:

| Item | Notes |
|------|-------|
| **Bridge chip module** | *CH9329* cable/module, or... <br/> *CH9350L* UC breakout board (if you need to use in BIOS on older machines) |
| **USB-to-UART adapter** | CP2102, CH340, FTDI, etc. — pick up if your bridge module doesn't include one |
| **Video capture card** | Required for live video feed from the remote machine (HDMI or VGA). |

Pre-assembled CH9329 cables (search "CH9329 cable usb" on eBay/AliExpress) include the UART adapter and are the easiest starting point.

CH9350L modules require a separate USB-to-UART adapter: picking up some Dupont jumper wires will be useful to connect these together. You can usually get everything needed for under £30 ($40USD).

Alternately, combined HDMI+USB-serial hardware such as the [NanoKVM-USB](https://wiki.sipeed.com/nanokvmusb) are now coming onto the market: these offer everything you need in a nice package (for slightly more expense). These are a really good option for users who just want convenience, and are supported by `kvm-serial`.

> It's worth noting that the cheapest HDMI to USB capture cards can have significant lag between the input signal and what arrives on your screen. Before spending £5 on an adapter, consider if you would prefer higher performance from an adapter at around a £30-60 price-point.

---

## Step 1 — Install the software

**Option A: Download a pre-built executable** (no Python required)

Download the latest release for your platform from the [releases page](https://github.com/sjmf/kvm-serial/releases/latest/).

- **macOS:** Right-click → Open on first launch (or run `xattr -dr com.apple.quarantine ./KVM\ Serial.app` on macOS Tahoe and later).
- **Windows:** Click "More info" → "Run anyway" on the SmartScreen prompt.

**Option B: Install from PyPI**

```bash
pip install kvm-serial
python -m kvm_serial        # launch the GUI
```

**Option C: Run directly with `uv`** (no install step)

```bash
uv run kvm-gui
```

**Option D: Install from source** (for bleeding-edge code or development)

```bash
git clone https://github.com/sjmf/kvm-serial.git
cd kvm-serial
pip install -e ".[dev]"
python -m kvm_serial
```

---

## Step 2 — Install serial drivers (if needed)

Executables bundle all Python dependencies, but your OS may still need a USB-to-UART driver.

| Platform | Action |
|----------|--------|
| **Windows** | Install the driver for your adapter chip (CP210x, CH340, FTDI, PL2303). Check Device Manager → Ports for the COM port after connecting. |
| **macOS** | Most adapters work without drivers. Verify with `ls /dev/cu.*` after connecting. |
| **Linux** | Kernel modules are usually included. Just add your user to the `dialout` group: `sudo usermod -a -G dialout $USER` then log out and back in. |

See [INSTALLATION.md](INSTALLATION.md) for detailed driver download links and instructions.

---

## Step 3 — Connect the hardware

### CH9329 (simpler — recommended for new users)

1. Plug the **USB-A (HID) end** of the CH9329 cable into the **target machine**.
2. Plug the **serial end** (or USB-to-UART adapter) into your **host machine**.
3. Verify a serial port appears on the host:
   - macOS/Linux: `/dev/cu.usbserial-XXXX` or `/dev/ttyUSB0`
   - Windows: `COM3`, `COM4`, etc.

> **Wiring note (DIY modules only):** Connect only TX, RX, and GND between the UART adapter and the CH9329. Do not connect 5 V / VCC — the chip is powered by the target's USB port.

### CH9350L (more capable, needs dipswitch setup)

1. Set the dipswitches on the CH9350L board before connecting:
   - **SEL = 0** (OFF) — configures the module as Upper Computer (UC); kvm-serial emulates the Lower Computer (LC) module.
   - **S0/S1** — select the working state. State 3 is recommended (see table below).
   - **BA0/BA1 = 0/0** — baud rate 115200 (default out of the box).

   | S0 | S1 | State | Use case |
   |----|----|-------|----------|
   | HIGH | HIGH | 0/1 | Full descriptor handshake |
   | LOW | HIGH | 2 | Legacy BIOS/UEFI CSM (relative mouse) |
   | **HIGH** | **LOW** | **3** | **Desktop OS (absolute mouse) — recommended** |
   | LOW | LOW | 4 | Multi-monitor (HID Digitizers) |

2. Connect the UC's **USB-A connector** to the **target machine**.
3. Wire the UC's serial header to your host via a 3.3 V USB-to-UART adapter (TX→RX, RX→TX, GND→GND).
4. Verify the serial port appears on the host (same as above).

> If the target machine does not enumerate ("see") a USB HID device, try the other USB-A port on the UC board.

See [CH9329_GUIDE.md](CH9329_GUIDE.md) and [CH9350L_GUIDE.md](CH9350L_GUIDE.md) for full hardware details.

---

## Step 4 — Run the GUI

```bash
python -m kvm_serial
```

1. The app auto-enumerates serial ports and video devices.
2. Open **File → Connect** and select your serial port, then click **Connect**.
3. (Optional) Select the video capture card under **Options → Camera**.
4. For CH9350L: open **Options → Protocol** and select the matching CH9350L state, then **Options → Baud → 115200**.
5. Click in the video window — your keyboard and mouse are now forwarded to the remote machine.
6. Use **File → Save Configuration** to persist your settings.

---

## Step 4 (alternative) — Headless / CLI

Use `control.py` when running without a display (e.g. Raspberry Pi, server).

```bash
# CH9329 — basic keyboard forwarding
python -m kvm_serial.control /dev/cu.usbserial-XXXX

# CH9329 — with mouse capture
python -m kvm_serial.control --mouse /dev/cu.usbserial-XXXX

# CH9350L — absolute mouse, state 3 (recommended for desktop)
python -m kvm_serial.control --ch9350 --ch9350-state 3 /dev/cu.usbserial-XXXX

# CH9350L — relative mouse, state 2 (for BIOS/UEFI)
python -m kvm_serial.control --ch9350 --ch9350-state 2 /dev/cu.usbserial-XXXX

# Windows COM port
python -m kvm_serial.control COM3

# All options
python -m kvm_serial.control --help
```

The default keyboard capture mode is `curses` (keyboard-only) or `pynput` (when mouse is enabled). See [MODES.md](MODES.md) for a full comparison if you need to change this.

---

## Troubleshooting

**No serial ports listed**
- Check the driver is installed (see Step 2).
- Linux: ensure you are in the `dialout` group and have logged out and back in.
- Confirm the USB-A HID end is in the **target** machine, not the host. The host needs to talk to the **serial** end of the cable.
- Try unplugging and reconnecting the device!

**No keyboard/mouse response on the target**
- CH9350L: verify SEL = 0 and S0/S1 match your selected state. Power-cycle the board after changing dipswitches.
- CH9350L: confirm baud rate matches the BA0/BA1 dipswitch setting (default 115200).
- Try a different USB port on the target.

**Input not captured on the host (macOS)**
- `pynput` mode requires **Input Monitoring** permission: System Settings > Privacy & Security > Input Monitoring.
- Alternatively, use `--mode curses` or `--mode tty`.

**Linux: permission denied on serial port**

```bash
sudo usermod -a -G dialout $USER
# then log out and back in
```

---

## Further reading

| Document | Contents |
|----------|----------|
| [INSTALLATION.md](INSTALLATION.md) | Platform-specific driver setup |
| [CH9329_GUIDE.md](CH9329_GUIDE.md) | CH9329 hardware wiring, GUI and CLI usage, troubleshooting |
| [CH9350L_GUIDE.md](CH9350L_GUIDE.md) | CH9350L dipswitch config, working states, RS-485, troubleshooting |
| [MODES.md](MODES.md) | Keyboard capture mode comparison (curses, pynput, tty, usb) |
| [SUPPORTED_DEVICES.md](SUPPORTED_DEVICES.md) | Feature comparison between CH9329 and CH9350L |
| [BUILD.md](BUILD.md) | Building executables from source |
