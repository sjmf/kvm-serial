# Serial KVM Controller (CH9329)

[![PyPI](https://img.shields.io/pypi/v/kvm-serial)](https://pypi.org/project/kvm-serial/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE.md)
[![Black](https://img.shields.io/badge/code%20style-black-black)](https://github.com/sjmf/kvm-serial/actions/workflows/lint.yml)
[![Run Tests](https://img.shields.io/github/actions/workflow/status/sjmf/kvm-serial/test.yml?label=Unit%20Tests)](https://github.com/sjmf/kvm-serial/actions/workflows/test.yml)
[![codecov](https://img.shields.io/codecov/c/gh/sjmf/kvm-serial)](https://codecov.io/gh/sjmf/kvm-serial)

__PLEASE NOTE: I am a hobbyist. I have no affiliation with any manufacturer developing or selling CH9329 hardware.__

A Software KVM, using the CH9329 UART Serial to USB HID controller.

[![Home-made serial KVM module](https://wp.finnigan.dev/wp-content/uploads/2023/11/mini-uart.jpg)](https://wp.finnigan.dev/?p=682)

This python module can transmit keyboard and mouse input over a UART serial connection to a second 
device, using a CH9329 module or cable. You can find these from vendors on eBay and AliExpress for 
next to nothing. However, there is very little software support available for these modules, and 
protocol documentation is sparse.

This Python module can capture keyboard scan codes from a keyboard attached to the local computer 
where the script is running, and send them via Serial UART to the device which the CH9329 USB HID 
keyboard is listening on. For most purposes, the default mode will suffice.

The `kvm_serial` package provides options for running the GUI, or as a script providing flexible options.

## GUI Usage

Run the GUI using `python -m kvm_serial`:

![KVM Window](https://wp.finnigan.dev/wp-content/uploads/2025/06/Screenshot-2025-06-12-at-23.56.28-2.png)

The module can be [installed from PyPI](https://pypi.org/project/kvm-serial/) (`pip install kvm-serial`),
or locally from a cloned git repo (`pip install -e .`).

The video window is provided using OpenCV, and can be quit using `Ctrl+ESC`.

## Script Usage

A script called `control.py` is also provided for use directly from the terminal. 
(Actually, this is all the `kvm.py` GUI does: set up the parameters for the script and run it!)

Packages from `requirements.txt` must be installed first. Use your preferred python package manager. E.g.:

```bash
# Conda
conda create -n kvm
conda activate kvm
# OR Venv (don't use both!)
python -m venv ./.venv
./.venv/scripts/activate
# Then, use pip to install dependencies
pip install -r requirements.txt
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

Use `python control.py --help` to view all available options. Keyboard capture and transmission is the default functionality of control.py: a couple of extra parameters are used to enable mouse and video.

Mouse capture is provided using the parameter `--mouse` (`-e`). It uses pynput for capturing mouse input and transmits this over the serial link simultaneously to keyboard input. Appropriate system permissions (Privacy and Security) may be required to use mouse capture.

Video capture is provided using the parameter `--video` (`-x`). It uses OpenCV for capturing frames from the camera device. Again, system permissions for webcam access may need to be granted.

## Keyboard capture mode comparison

Some capture methods require superuser privileges (`sudo`), for example `pyusb` provides the most accurate keyboard scancode capture, but needs to de-register the device driver for the input method in order to control it directly.

For example usage, please see the accompanying blogpost: https://wp.finnigan.dev/?p=682

| Mode     | Modifiers  | Paste  | Blocking   | Focus  | Exit     | Permissions            |
|----------|------------|--------|------------|--------|----------|------------------------|
| `usb`    | ✅ Yes     | ❌ No  | ✅ Yes      | ❌ No  | Ctrl+ESC | `sudo` / root          |
| `tty`    | ❌ No      | ✅ Yes | ❌ No       | ✅ Yes | Ctrl+C   | Standard user          |
| `pynput` | ✅ Yes     | ❌ No  | ❌ No       | ❌ No  | Ctrl+ESC | Input monitoring (OSX) |
| `curses` | ⚠️ Some    | ✅ Yes | ❌ No       | ✅ Yes | ESC      | Standard user          |

For `curses`, modifier support is incomplete but should be good enough to enable working in a terminal. Curses provides a good mix of functionality versus permissions and is therefore the default mode in keyboard-only mode. When running with mouse and video, `pynput` is selected automatically.

A 'yes' in the remaining columns means:

 * **Modifiers**:
Keys like `Ctrl`, `Shift`, `Alt` and `Cmd`/`Win` will be captured. Combinations like Ctrl+C will be passed through.
 * **Paste**: 
Content can be pasted from host to guest. Paste text into the console and it will be transmitted char-wise to the HID device
 * **Blocking**:
Keyboard input will not function in other applications while the script is running
 * **Focus**:
The console must remain in focus for input to be recorded (and transmitted over the UART)
 * **Implication**:
You will need to select the best input method for your use case! 

## Troubleshooting

**Permissions errors on Linux**: 
if your system user does not have serial write permissions (resulting in a permission error), you can add your user to the `dialout` group: e.g. `sudo usermod -a -G dialout $USER`. You must fully log out of the system to apply the change.

**Difficulty installing requirements**: If you get `command not found: pip` or similar when installing requirements, try: `python -m pip [...]` to run pip instead.

## Acknowledgements
With thanks to [@beijixiaohu](https://github.com/beijixiaohu), the author of the [ch9329Comm PyPi package](https://pypi.org/project/ch9329Comm/) and [GitHub repo](https://github.com/beijixiaohu/CH9329_COMM/) (in Chinese), some code of which is re-used under the MIT License.

## License
(c) 2023-25 Samantha Finnigan (except where acknowledged) and released under [MIT License](LICENSE.md).

