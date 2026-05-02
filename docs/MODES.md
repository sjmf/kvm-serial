# Keyboard capture mode comparison

Some capture methods require superuser privileges (`sudo`), for example `pyusb` provides the most accurate keyboard scancode capture, but needs to de-register the device driver for the input method in order to control it directly.

For example usage, please see the accompanying blogpost: https://wp.finnigan.dev/?p=682

| Mode     | Platform           | Modifiers  | Paste  | Blocking   | Focus  | Exit     | Permissions            |
|----------|-------------------|------------|--------|------------|--------|----------|------------------------|
| `usb`    | All               | ✅ Yes     | ❌ No  | ✅ Yes      | ❌ No  | Ctrl+ESC | `sudo` / root          |
| `tty`    | Unix/Linux/macOS  | ❌ No      | ✅ Yes | ❌ No       | ✅ Yes | Ctrl+C   | Standard user          |
| `pynput` | All               | ✅ Yes     | ❌ No  | ❌ No       | ❌ No  | Ctrl+ESC | Input monitoring (OSX) |
| `curses` | Unix/Linux/macOS  | ⚠️ Some    | ✅ Yes | ❌ No       | ✅ Yes | ESC      | Standard user          |

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

**Platform compatibility:**

* **Windows**: `curses` and `tty` modes are not available (they require Unix-specific modules). On Windows, `pynput` is the default for headless mode, but it does not capture keystrokes in the background — focus must remain on the console window for input to be recorded. For reliable headless keyboard capture on Windows, use `usb` mode (requires admin privilege).
* **macOS**: `pynput` requires Input Monitoring permission. `curses` and `tty` work as standard user.
* **Linux**: All modes available; `curses` is the default for keyboard-only mode.
