# Serial KVM Controller (CH9329)

[![PyPI](https://img.shields.io/pypi/v/kvm-serial)](https://pypi.org/project/kvm-serial/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE.md)
[![Black](https://img.shields.io/badge/code%20style-black-black)](https://github.com/sjmf/kvm-serial/actions/workflows/lint.yml)
[![Run Tests](https://img.shields.io/github/actions/workflow/status/sjmf/kvm-serial/test.yml?label=Unit%20Tests)](https://github.com/sjmf/kvm-serial/actions/workflows/test.yml)
[![codecov](https://img.shields.io/codecov/c/gh/sjmf/kvm-serial)](https://codecov.io/gh/sjmf/kvm-serial)

A Software KVM, using the CH9329 UART Serial to USB HID controller.

Control your computers using an emulated keyboard and mouse!

This python module allows you to control to a second device using a CH9329 module (or cable) and 
a video capture device. You can find these from vendors on eBay and AliExpress for a low price.
However, there is very little software support available for these modules, and CH9329
protocol documentation is sparse.

Running this package will capture keyboard and mouse inputs from the local computer 
where the script is running, and send these over a serial UART connection to the CH9329 USB HID 
module, which will send USB HID mouse and keyboard movements and scan codes to the remote.

The `kvm_serial` package provides options for running the GUI, or as a script providing flexible options.

## GUI Usage

Run the GUI using `python -m kvm_serial`:

![KVM Window](https://wp.finnigan.dev/wp-content/uploads/2025/09/output-4.gif)
*The Serial KVM window running on OSX, controlling a Windows remote machine*

The module can be [installed from PyPI](https://pypi.org/project/kvm-serial/) (`pip install kvm-serial`),
or locally from a cloned git repo (`pip install -e .`).

The GUI app will do a lot of the work for you: it will enumerate video devices and serial ports, 
and give you a window to interact with the guest in. Application settings can be changed from the 
menus (File, Options, View), for example if the app doesn't select the correct devices by default.

## Kit List

This module requires a little bit of hardware to get going. You will need:

* CH9329 module or cable
* Video capture card (e.g. HDMI)

You can likely get everything you need for under £30, which is incredible when compared to the 
price of a KVM crash cart adapter.

### CH9329 module/cable assembled as cables.

_PLEASE NOTE: I am a hobbyist. I have no affiliation with any manufacturer developing or selling CH9329 hardware._  

[![Home-made serial KVM module](https://wp.finnigan.dev/wp-content/uploads/2023/11/mini-uart.jpg)](https://wp.finnigan.dev/?p=682)
*A home-made serial KVM module: CH9329 module soldered to SILabs CP2102. CH340 works, too.*

So, I don't have a specific vendor to recommend, but if you put "*CH9329 cable usb*" into a search 
engine, you will find the right thing. Just make sure what you buy has "CH9329" in the name: a USB-A 
to USB-A cable won't do, and can damage your machine.

The modules have a USB-A male connector on one end, and serial connector on the other. The cables 
have USB-A both ends, as they are already put together and should pretty much be plug-and-play: just 
make sure it's the right way around. I just soldered a CH9329 module to a UART transceiver chip 
myself, as above.

### Video capture card

You also need a capture card that takes the display output from your remote machine, and presents it 
as a USB device to your local system. I found the "*UGREEN Video Capture Card HDMI to USB C Capture 
Device*" was a good balance of price versus value. The more you spend on a capture device, the more
responsive your video feed will likely be (to a point). HDMI and VGA hardware is available.

## Script Usage

A script called `control.py` is also provided for use directly from the terminal, so you can also control remotes from a headless environment! (e.g. Pi to Pi!)

Packages from `requirements.txt` must be installed first. Use your preferred python package manager. E.g.:

```bash
# Create Virtual env
python -m venv ./.venv
./.venv/scripts/activate
# Then, use pip to install dependencies
pip install -r requirements.txt
# Or install as a module
pip install kvm_serial
```

Usage examples for the `control.py` script:

```bash
# Run with mouse and video support; use a Mac OSX serial port:
python control.py -ex /dev/cu.usbserial-A6023LNH

# Run the script using keyboard 'tty' mode (no mouse, no video)
python control.py --mode tty /dev/tty.usbserial0

# Run using `pyusb` keyboard mode (which requires root):
sudo python control.py --mode usb /dev/tty.usbserial0

# Increase logging using --verbose (or -v), and use COM1 serial port (Windows)
python control.py --verbose COM1
```

Use `python control.py --help` to view all available options. Keyboard capture and transmission is the default functionality of control.py: a couple of extra parameters are used to enable mouse and video. For most purposes, the default capture mode will suffice.

Mouse capture is provided using the parameter `--mouse` (`-e`). It uses pynput for capturing mouse input and transmits this over the serial link simultaneously to keyboard input. Appropriate system permissions (Privacy and Security) may be required to use mouse capture.

Video capture is provided using the parameter `--video` (`-x`). It uses OpenCV for capturing frames from the camera device. Again, system permissions for webcam access may need to be granted.

See [MODES.md](./docs/MODES.MD) for more information on the various other options to the script.
Implementations are provided for all the main python input capture methods.

## Troubleshooting

**Permissions errors on Linux**: 
if your system user does not have serial write permissions (resulting in a permission error), you can add your user to the `dialout` group: e.g. `sudo usermod -a -G dialout $USER`. You must fully log out of the system to apply the change.

**Difficulty installing requirements**: If you get `command not found: pip` or similar when installing requirements, try: `python -m pip [...]` to run pip instead.

## Acknowledgements
With thanks to [@beijixiaohu](https://github.com/beijixiaohu), the author of the [ch9329Comm PyPi package](https://pypi.org/project/ch9329Comm/) and [GitHub repo](https://github.com/beijixiaohu/CH9329_COMM/) (in Chinese), some code of which is re-used under the MIT License.

## License
(c) 2023-25 Samantha Finnigan (except where acknowledged) and released under [MIT License](LICENSE.md).

