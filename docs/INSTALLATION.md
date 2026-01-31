# Installation Guide

This guide covers installing KVM Serial and its dependencies on Windows, macOS, and Linux.

NOTE: If using the executable binaries, you **do not** need to also create the python environment,
as this will be bundled in the application. However, steps regarding serial drivers still apply!

## Requirements

- Python 3.10 or higher for running from source
- USB to UART bridge connecting to the CH9329 serial device
- USB video capture device (for video functionality)

# Platform Specific Dependencies

__Note:__ On modern Windows and Mac, this application is signed without a paid developer certificate (between $99 and $300). You will therefore see the following prompts:

![Mac OSX Security Prompt](img/osx-sec-prompt.png)
![Windows Security Prompt](img/win-sec-prompt.png)

In order to run the binary app on Mac OSX, you will need to *right click -> Open* it. Otherwise, the above prompt will not show the "Open" option.

On Windows, you will need to click "More info" on the SmartScreen dialog to "Run anyway".

As always, do not run apps on your machine which you do not trust. The entire build chain and source code for this application is available in the GitHub repository for you to verify if desired.

## Windows

**Note**: If you see "No serial ports found" and you've connected a USB serial device, ensure the drivers are properly installed (see below):

### USB to UART Bridge Drivers

Most CH9329 devices use a USB to UART bridge chip to communicate with your computer. You'll need to install the appropriate drivers based on which chip your device uses.

**Common USB to UART Bridge Chips**:

1. **Silicon Labs CP210x** (CP2102, CP2104, CP2105, etc.)
   - **Download**: [CP210x USB to UART Bridge VCP Drivers](https://www.silabs.com/software-and-tools/usb-to-uart-bridge-vcp-drivers)
   - **Recommended Version**: CP210x Windows Drivers v6.7.6 (Released 9/3/2020) or later

2. **FTDI** (FT232, FT234X, FT4232H, etc.)
   - **Download**: [FTDI VCP Drivers](https://ftdichip.com/drivers/vcp-drivers/)

3. **Prolific PL2303**
   - The Prolific product page for the PL2303 has gone. An alternative is available at: [Plugable USB Serial Adapter Drivers](https://plugable.com/pages/prolific-drivers)
   - Alternately, a GitHub repo with Windows 11-compatible PL2303 drivers is available at [theAmberLion/Prolific](https://github.com/theAmberLion/Prolific).

4. **WCH CH340/CH341**
   - **Download**: [WCH CH340 Drivers](http://www.wch-ic.com/downloads/CH341SER_ZIP.html)
   - **Note**: Windows 10/11 often include these drivers automatically

**Installation Steps**:

1. Download the appropriate driver for your device's chip
2. Extract and run the installer
3. Connect your CH9329 device via USB
4. Verify installation:
   - Open Device Manager (Win + X → Device Manager)
   - Look under "Ports (COM & LPT)" for your device
   - Note the COM port number (e.g., COM3, COM4)

### Windows Permissions

**Windows 10/11 Camera Access**:

On first launch, Windows may prompt for camera access permission. The application will:

1. Display a Windows permission dialog asking for camera access
2. Wait for your response (Allow/Deny)
3. Continue normally after you respond

If you need to change camera permissions later: Settings → Privacy & security → Camera → Allow desktop apps to access your camera

## macOS

Most USB-to-serial devices work out of the box on modern macOS systems without additional drivers.

**Verifying the device**:

Connect your device and verify it appears in `/dev/`:

```bash
ls /dev/cu.*
```

You should see a device like `/dev/cu.usbserial-xxxxx` or `/dev/cu.SLAB_USBtoUART`

If unavailable, you can list USB devices connected to the system using:

```bash
system_profiler SPUSBDataType
```

### macOS Permissions

macOS requires specific permissions for camera and input monitoring:

1. **Camera Access**: The app will request camera permission on first launch
2. **Input Monitoring**: System Preferences → Security & Privacy → Privacy → Input Monitoring

## Linux

### USB to UART Kernel Modules

Most Linux distributions include kernel modules for common USB to UART bridge chips by default:

- **CP210x**: `cp210x`
- **FTDI**: `ftdi_sio`
- **PL2303**: `pl2303`
- **CH340/CH341**: `ch341`

**Verifying driver support**:

```bash
# Check if the driver is loaded (replace cp210x with your chip's module)
lsmod | grep cp210x

# Connect your device and check dmesg for detection
dmesg | tail -20

# List serial devices
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
```

If the driver isn't loaded, it should automatically load when you connect the device. The device will typically appear as:

- `/dev/ttyUSB0` (or ttyUSB1, ttyUSB2, etc.) for most USB-to-serial adapters
- `/dev/ttyACM0` for some USB devices using the CDC ACM protocol

**Troubleshooting**: If the device doesn't appear:

1. Check kernel messages: `dmesg | grep -i usb`
2. Verify the USB connection: `lsusb` (look for your device)
3. Ensure the kernel module is available: `modinfo cp210x` (or relevant module)

### System Dependencies

Install required system libraries for PyQt5 and OpenCV:

**Ubuntu/Debian**:

```bash
sudo apt-get update
sudo apt-get install -y \
    libxcb-xinerama0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-xfixes0 \
    libxkbcommon-x11-0 \
    libgl1 \
    libegl1 \
    libxcb-cursor0
```

**Fedora/RHEL**:

```bash
sudo dnf install -y \
    libxcb \
    xcb-util-wm \
    xcb-util-image \
    xcb-util-keysyms \
    xcb-util-renderutil \
    libxkbcommon-x11 \
    mesa-libGL \
    mesa-libEGL
```

### User Permissions

**Serial Port Access**:

Linux requires users to be in the `dialout` group to access serial ports without root privileges.
If you get permission denied errors when accessing serial ports, add the user to the group:

```bash
# Add your user to the dialout group
sudo usermod -a -G dialout $USER

# Verify group membership
groups $USER

# Log out and log back in for changes to take effect
# OR reload groups in current session (may not work in all cases):
newgrp dialout
```

**Important**: You must log out and log back in (or restart) for the group changes to take effect system-wide. After logging back in, verify with:

```bash
groups  # Should show 'dialout' in the list
```

If you see "Permission denied" errors when trying to access `/dev/ttyUSB*` or `/dev/ttyACM*`, this is the most common cause.

## Common Issues

### "No serial ports found"

- Windows: Install serial drivers (see above). Check Device Manager for the device.
- macOS: Check `/dev/cu.*` for the device
- Linux: Check `/dev/ttyUSB*` or `/dev/ttyACM*`
- Linux: Verify you're in the `dialout` group
- Try unplugging and reconnecting the device
