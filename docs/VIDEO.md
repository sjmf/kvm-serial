# Video Subsystem

This document describes the video implementation used by the GUI. kvm-serial captures video through Qt's `QtMultimedia` module. Qt wraps the
three native camera stacks (AVFoundation on macOS, DirectShow on Windows, V4L2
on Linux) behind a single API and delivers frames directly into a
`QGraphicsVideoItem` that lives in the GUI's scene.

## Overview

Video capture is implemented with QtMultimedia end-to-end:

- device enumeration: `QCameraInfo.availableCameras()`
- capability probing: `QCamera(...).supportedViewfinderSettings()`
- active capture: `QCamera(...).setViewfinder(QGraphicsVideoItem)` + `start()`

Relevant code:

- backend enumeration and capability model:
  [kvm_serial/backend/video.py](../kvm_serial/backend/video.py)
- GUI camera lifecycle and rendering:
  [kvm_serial/kvm.py](../kvm_serial/kvm.py)

## Architecture

```
QCameraInfo.availableCameras()  ─┐
    (device list)                │
                                 ├─►  kvm_serial/backend/video.py
QCamera(info).supportedViewfinder│    enumerate_cameras() → List[CameraProperties]
Settings() (resolutions/fps)    ─┘

kvm_serial/kvm.py
  KVMQtGui._set_camera(camera, width, height):
    QCamera(camera.info)
      .setViewfinder(self.video_item)   # QGraphicsVideoItem in video_scene
      .setViewfinderSettings(...)       # resolution
      .start()                          # Qt streams frames into video_item
```

## Data Model

`CameraProperties` in [kvm_serial/backend/video.py](../kvm_serial/backend/video.py)
stores what the GUI needs to drive menus and opening:

| Field | Type | Source / Meaning |
|---|---|---|
| `index` | `int` | Position in Qt's enumerated list (GUI list index, not OS device index) |
| `name` | `str` | `QCameraInfo.description()` fallback chain |
| `unique_id` | `str` | `QCameraInfo.deviceName()` (or index fallback) |
| `width`, `height` | `int` | Default resolution dimensions used by GUI status/mapping fallbacks |
| `fps` | `int` | Max `maximumFrameRate()` observed across supported viewfinder settings |
| `resolutions` | `List[Tuple[int, int]]` | Unique supported resolutions from `supportedViewfinderSettings()` |
| `default_resolution` | `Tuple[int, int]` | Active/default resolution chosen during probe |
| `info` | `Optional[QCameraInfo]` | Live Qt camera descriptor passed to `QCamera(...)` when opening |

## Enumeration Flow

`enumerate_cameras()` probes each `QCameraInfo` by:

1. creating `QCamera(info)`
2. calling `load()`
3. waiting for loaded state via `_wait_for_loaded()`
4. reading `supportedViewfinderSettings()`
5. calling `unload()`

`_wait_for_loaded()` spins a local `QEventLoop` with a timeout
(`PROBE_TIMEOUT_MS`, currently 2000 ms). This keeps probing robust when a
backend is slower to report loaded status.

## GUI Lifecycle

In [kvm_serial/kvm.py](../kvm_serial/kvm.py):

- `__init_video()` creates:
  - `QGraphicsScene`
  - `VideoGraphicsView` (custom subclass)
  - `QGraphicsVideoItem` (`self.video_item`)
- `video_item.nativeSizeChanged` is connected to
  `_on_video_native_size_changed()`

In `__init_timers()`, device initialization is deferred with `QTimer.singleShot`
so menu/device setup runs after the event loop starts.

`_populate_video_devices()` calls `enumerate_cameras()`, then:

1. fills the video menu
2. selects the first camera by default (sets `video_var = 0`) without opening the device
3. populates the resolution menu from cached capabilities for device 0

Actual camera opening is deferred to `_load_settings()`, which is the single
source of truth for applying the saved camera choice and saved resolution via
`_set_camera(...)`. `_load_settings()` sets `video_var` to the saved index,
loads `resolution_var` from settings, then calls `_populate_resolution_menu()`
for the active device — which rebuilds the resolution menu and opens the camera
at the correct resolution in a single `_set_camera(...)` call.

## Opening and Switching Cameras

`_set_camera(camera, width=None, height=None)` in
[kvm_serial/kvm.py](../kvm_serial/kvm.py):

1. stops/unloads any previously active `self.qcamera`
2. creates a new `QCamera(camera.info)`
3. attaches sink: `setViewfinder(self.video_item)`
4. optionally applies resolution via `QCameraViewfinderSettings`
5. starts capture with `start()`

Errors from Qt camera initialization are routed to
`_on_camera_initialization_error()` via `self.qcamera.error.connect(...)`.

## Resolution Behavior

- The resolution menu is built from `CameraProperties.resolutions`
  (`_populate_resolution_menu`).
- `resolution_var` stores the selected override as `WIDTHxHEIGHT`.
- If saved/selected resolution is unsupported for a newly selected camera,
  code falls back to that camera's default resolution and resets menu state.

## Native Size and Coordinate Mapping

`_on_video_native_size_changed()` updates `video_item` size and scene rect when
the first decoded frame reports its real dimensions.

Mouse coordinate mapping and status reporting rely on `_camera_resolution()`,
which prefers `video_item.nativeSize()` and falls back to camera/default values.

## Screenshot Path

`_grab_video_frame()` captures the current video by rendering the scene into a
`QPixmap` at native video size when available.

If native size is not available yet (for example, very early startup), it
falls back to `video_view.grab()`.

## Linux Runtime Dependencies

QtMultimedia requires system runtime libraries/plugins on Linux.
If they are missing, importing `PyQt5.QtMultimedia` will fail in
[kvm_serial/backend/video.py](../kvm_serial/backend/video.py).

Install guidance is maintained in
[docs/INSTALLATION.md](./INSTALLATION.md).
