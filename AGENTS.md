# AGENTS.md

This file provides guidance for coding agents and contributors working in this repository.

## What this project is

A software KVM (Keyboard, Video, Mouse) controller for UART-to-USB-HID bridge chips. It captures local keyboard and mouse input and transmits it over serial to either a CH9329 or CH9350L chip, which emulates USB HID devices on the remote machine. A video capture card provides the screen feed back to the host.

The package has two entry points:
- **GUI** (`kvm_serial/kvm.py`): PyQt5 app with live video, menus, settings persistence
- **Headless CLI** (`kvm_serial/control.py`): Terminal-based, for Pi-to-Pi or server use

## Setup

```bash
pip install -e ".[dev]"    # dev includes pytest, black, pyinstaller, pre-commit
# or
uv run kvm-gui             # run GUI directly without install
```

## Commands

```bash
# Run GUI
python -m kvm_serial

# Run headless control script
python -m kvm_serial.control /dev/cu.usbserial-XXXX
python -m kvm_serial.control --help   # all options

# Lint (Black, line-length 100)
uv run --extra dev black --check kvm_serial tests

# Format Python source and tests
uv run --extra dev black kvm_serial tests

# Tests
pytest tests/

# Single test
pytest tests/kvm/test_kvm_init.py::TestKVMInitialization::test_window_initialization

# Build executables
pyinstaller kvm-gui.spec
# macOS: also sign after build:
codesign --force --deep --sign - --entitlements assets/entitlements.plist "dist/KVM Serial.app"
```

## Architecture

### Serial protocol (`kvm_serial/utils/communication.py`)

`DataComm` is an abstract base class with a high-level API (`send_scancode()`, `send_mouse_absolute()`, `send_mouse_relative()`, `release()`). Concrete subclasses implement chip-specific framing:

- **`CH9329Comm`** (`kvm_serial/utils/ch9329.py`) — command-style protocol with framed packets:

  ```text
  header(2B: 0x57 0xAB) + addr(1B) + cmd(1B) + len(1B) + data + checksum(1B)
  ```

  Command bytes: `0x02` = keyboard, `0x04` = absolute mouse, `0x05` = relative mouse.

- **`CH9350Comm`** (`kvm_serial/utils/ch9350.py`) — paired-chip protocol with descriptor handshake (state 0/1) or fixed-format frames (states 2/3/4). Full specification in `docs/CH9350L_PROTO.md`.

`DataCommManager` (`kvm_serial/backend/manager.py`) is a singleton that owns the protocol instance and input listeners, ensuring a single serial port drives at most one `DataComm` and manages its lifecycle.

### Keyboard capture backends (`kvm_serial/backend/implementations/`)

All backends extend `BaseOp` (abstract) and implement `run()`. `KeyboardListener` in `backend/keyboard.py` selects the implementation via a `Mode` enum:

| Mode | Class | Notes |
|------|-------|-------|
| `curses` | `CursesOp` | Default for headless; partial modifier support |
| `pynput` | `PynputOp` | Default when mouse/video enabled; needs Input Monitoring on macOS |
| `tty` | `TtyOp` | No modifiers, supports paste |
| `usb` | `PyUSBOp` | Full modifier capture, requires root |
| Qt | `QtOp` | Used by the GUI only |

### GUI application (`kvm_serial/kvm.py`)

`KVMQtGui(QMainWindow)` orchestrates everything:
- `VideoCaptureWorker(QThread)` — on-demand frame capture, communicates via Qt signals
- `CameraEnumerationThread(QThread)` — async camera discovery (avoids macOS permission hang)
- `VideoGraphicsView(QGraphicsView)` — subclassed to handle focus, keyboard, and mouse events
- Settings persisted to `.kvm_settings.ini` via `kvm_serial/utils/settings.py`
- `__init_devices()` is deferred via `QTimer.singleShot(0, ...)` to not block the event loop

Video path: QTimer fires → `_request_video_frame()` → worker emits `frame_ready` → `_on_frame_ready()` converts BGR→RGB and renders to `QGraphicsScene`.

Mouse coordinates are in scene space (native camera resolution), not window pixels. `_on_mouse_move()` guards against out-of-bounds before calling `MouseOp.on_move()`.

### Video capture (`kvm_serial/backend/video.py`)

`CaptureDevice` uses Qt5 (QtMultimedia) for both enumeration and frame capture. On macOS and Windows, Qt drives the native camera stacks directly (AVFoundation, DirectShow). On Linux, capture is layered over GStreamer:

```text
QCamera -> Qt's GStreamer media plugin
        -> GStreamer camerabin          (gstreamer1.0-plugins-bad; -extra on Ubuntu 26.04)
        -> wrappercamerabinsrc -> v4l2src  (gstreamer1.0-plugins-good)
        -> V4L2 kernel API (/dev/videoN)
```

- Enumeration: `QCameraInfo.availableCameras()`. On Linux this lists V4L2 device nodes without needing `camerabin`, so a camera can appear in the menu yet fail to open when `camerabin` is missing (Qt logs "the 'camerabin' plugin is missing").
- Capture: `QCamera`, through the platform backend above.
- Settings probing: `QCamera.supportedViewfinderSettings()`, with no separate native introspection layer. On the GStreamer backend `load()` is asynchronous and this list stays empty until `LoadedStatus`, so call `wait_for_loaded()` after `load()` before reading it (#47).

`CameraProperties` holds device metadata (`index, name, unique_id, width, height, fps, resolutions, default_resolution`) with the live `QCameraInfo` object for passing to `QCamera()` when opening. The GUI menu position (`self.video_var`) maps directly to the enumerated device list; no platform-specific index translation is needed.

### Keyboard layouts (`kvm_serial/utils/keyboard_layouts.py`)

Layout files map ASCII characters to USB HID scancodes. `en_GB`, `en_US`, and `pl_PL` are supported. The GUI auto-detects from `QLocale` on first run.

## Testing

Read [docs/TESTING.md](docs/TESTING.md) before adding or changing tests. It documents the mocking patterns the suite depends on (patch timing, import-point patching, module cleanup) and the failure modes they prevent.

Run the full suite with `pytest tests/`. CI runs it in a single invocation on Python 3.10. `unittest.mock.patch` resolves dotted targets differently before Python 3.12, so when changing test infrastructure (`KVMTestBase`, patch targets, module cleanup), also run the suite on 3.10.

The root `tests/conftest.py` injects `serial`/`serial.tools`/`serial.tools.list_ports` mocks into `sys.modules` via `pytest_configure` before any collection, so the whole suite can run in one invocation.

All GUI tests inherit from `KVMTestBase` (defined in `tests/kvm/test_kvm_base.py`), which:
1. Mocks all PyQt5 widgets and `QApplication` before any import
2. Imports `kvm_serial.kvm` inside `setUp()` *after* patches are started
3. Removes tested modules from `sys.modules` in `tearDown()`

Test mixins (`KVMTestMixins`) provide domain helpers: `SerialTestMixin.create_mock_serial_ports()`, `VideoTestMixin.create_mock_cameras()`, etc.

## CH9350L protocol support

The CH9350L operates in pairs: **lower computer** (USB host) and **upper computer** (USB device, presents HID to the target PC). kvm-serial replaces the lower computer in software. The protocol supports four working states (selected via UC dipswitches S0/S1):

- **State 0/1:** Descriptor handshake + PID-ack gate; full HID Report Descriptor passthrough
- **State 2:** BIOS keyboard + relative mouse (legacy BIOS / UEFI CSM compatible)
- **State 3:** BIOS keyboard + absolute mouse
- **State 4:** BIOS keyboard + absolute mouse + HID Digitizers

For full protocol detail, see `docs/CH9350L_PROTO.md`.
