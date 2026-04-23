# Video Capture

kvm-serial captures video through Qt's `QtMultimedia` module. Qt wraps the
three native camera stacks (AVFoundation on macOS, DirectShow on Windows, V4L2
on Linux) behind a single API and delivers frames directly into a
`QGraphicsVideoItem` that lives in the GUI's scene.

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

There is **one enumerator and one opener** — both are Qt. The `QCameraInfo`
returned by enumeration is handed straight to `QCamera()`, so there is no
separate index to keep aligned with a native API.

### `CameraProperties` ([kvm_serial/backend/video.py](../kvm_serial/backend/video.py))

A dataclass holding the metadata the GUI needs:

| Field | Source |
|---|---|
| `name`, `unique_id` | `QCameraInfo.description()` / `.deviceName()` |
| `resolutions`, `default_resolution` | `QCamera.supportedViewfinderSettings()` |
| `fps` | max of `supportedViewfinderSettings.maximumFrameRate()` |
| `info` | the live `QCameraInfo` (passed back to `QCamera()` when opening) |

Enumeration calls `QCamera.load()` on each device to populate
`supportedViewfinderSettings()` without starting capture, then `unload()`s it.
`load()` is asynchronous; `_wait_for_loaded()` spins a local `QEventLoop` with
a 2s timeout to give the backend time to populate capabilities. In practice
AVFoundation/DirectShow return synchronously; V4L2 is fast enough that the
wait is usually a no-op.

### Frame pipeline

The old implementation had a `VideoCaptureWorker` `QThread` that called
`cv2.VideoCapture.read()`, emitted numpy frames back to the GUI, where they
were colour-converted to RGB and pushed into a `QGraphicsPixmapItem`. That
whole pipeline is gone. `QGraphicsVideoItem` is a native QtMultimedia video
sink: the camera streams into it with backend-appropriate hardware
acceleration and zero Python per-frame work.

`KVMQtGui.video_item.nativeSizeChanged` fires once the first frame is decoded.
That's the authoritative resolution (the viewfinder request isn't always
honoured exactly) and is used to set the scene rect and drive the
mouse-coordinate mapping.

## Screenshots

`_grab_video_frame()` renders the video item to a `QPixmap` via
`QGraphicsScene.render(...)` at the video's native resolution when available.
If the camera hasn't produced a first frame yet, it falls back to
`video_view.grab()`.

## Platform notes

Qt's DSHOW wrapper (Windows) and V4L2 wrapper (Linux) share all the nuances
the OpenCV backends had access to, and the Python layer no longer touches
either directly. No workarounds live in this tree anymore for:

- DirectShow property-order quirks (Qt sets viewfinder settings atomically)
- AVFoundation index reversal (there is no index to reverse — `QCameraInfo`
  objects are passed by reference to `QCamera`)
- V4L2 non-contiguous `/dev/videoN` gaps (Qt iterates via udev/sysfs)
- MediaFoundation init delays on Windows (Qt uses DSHOW)

## Linux install note

Qt's multimedia plugins are in separate Debian/Ubuntu packages:

```bash
sudo apt install python3-pyqt5.qtmultimedia libqt5multimedia5-plugins
```

Without these, `from PyQt5.QtMultimedia import QCamera` will raise
`ImportError`, which is surfaced to the user at module load time by a
guarded import in [kvm_serial/backend/video.py](../kvm_serial/backend/video.py).

## History

Earlier versions of this document described a platform-specific enumeration
layer in `kvm_serial/utils/resolution_probe.py` (removed) and an AVFoundation
index-reversal hack (no longer applicable). See issue #24 and the Qt-migration
commit for the rationale.
