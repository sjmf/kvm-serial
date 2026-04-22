# Video Device Enumeration

This document describes how kvm-serial discovers video capture devices and their
supported resolutions on each platform. The goal is a single authoritative device
list — populated without opening any device — that both the camera menu and the
resolution menu read from.

## Architecture

Two separate concerns are deliberately separated:

| Concern | Owner |
|---|---|
| Device discovery (name, index, resolutions) | `kvm_serial/utils/resolution_probe.py` |
| Frame capture | OpenCV (`cv2.VideoCapture`) in `kvm_serial/backend/video.py` |

`CaptureDevice.getCameras()` calls `enumerate_devices()`, which returns a list of
`DeviceInfo` named tuples. Each entry contains the device index, human-readable name,
a platform-specific unique ID, a sorted list of supported resolutions, a default
resolution, and the maximum fps reported by the active format. No device is opened
during enumeration.

`CameraProperties.from_device_info()` wraps a `DeviceInfo` for use by the GUI.
The resolution menu reads `CameraProperties.resolutions` from this cached object;
it does not call into the probe module per click.

If native enumeration returns an empty list (missing optional dependency, unsupported
platform, or COM/ioctl failure), `_fallback_enumerate_opencv()` is used instead: the
old `cv2.VideoCapture` probe loop that yields names like `"0"` and `"1"`.

---

## Platform pipelines

### macOS — AVFoundation (`pyobjc-framework-AVFoundation`)

**Entry point:** `_enumerate_devices_avfoundation()` → `_avfoundation_device_list()`.

The device list comes from `AVCaptureDeviceDiscoverySession` with device types
`[BuiltInWideAngleCamera, External]`. This matches the filter OpenCV's
`CAP_AVFOUNDATION` backend uses internally (`cap_avfoundation_mac.mm`), so
`DeviceInfo.index` N is positionally aligned with `cv2.VideoCapture(N)`.

Per-device data is read from `AVCaptureDevice`:

- **Name:** `device.localizedName()`
- **Unique ID:** `device.uniqueID()` (stable across reboots, survives replug for
  built-in devices; may change for some USB cameras)
- **Default resolution / fps:** `device.activeFormat()` →
  `CMVideoFormatDescriptionGetDimensions` + `videoSupportedFrameRateRanges`
- **All resolutions:** `device.formats()` iterated, dimensions deduplicated

#### Index reversal

OpenCV iterates the discovery-session device list in **reverse order** relative to
the API call. `_avfoundation_device_list` applies `[::-1]` to both the discovery
session path and the legacy `devicesWithMediaType_` fallback so indices stay aligned.

This is an empirically verified implementation detail of the OpenCV
`CAP_AVFOUNDATION` backend, not a documented contract. Re-run the alignment verification script after any OpenCV upgrade:
[gist.github.com/sjmf/d1d06ba7bdbf331b5ef4b0667272c37f](https://gist.github.com/sjmf/d1d06ba7bdbf331b5ef4b0667272c37f)

Expected output (two cameras, indices aligned):

```
IDENTITY: OpenCV and our order agree by dims. (Reversal not needed.)
```

If it prints `REVERSED` or `MISMATCH`, investigate before shipping.

#### Fallback

If the discovery session API is unavailable (pre-macOS 10.15), `_avfoundation_device_list`
falls back to the deprecated `AVCaptureDevice.devicesWithMediaType_`. The same
`[::-1]` reversal is applied.

If `pyobjc-framework-AVFoundation` is not installed, `_enumerate_devices_avfoundation`
returns `[]` and the OpenCV fallback probe runs.

---

### Windows — DirectShow (`comtypes`)

**Entry point:** `_enumerate_devices_directshow()` → `_directshow_devices()`.

Device discovery uses the standard DirectShow enumeration pattern:
`ICreateDevEnum::CreateClassEnumerator(CLSID_VideoInputDeviceCategory)` →
`IEnumMoniker::Next` → per-moniker `IMoniker::BindToStorage(IPropertyBag)`.

OpenCV's `CAP_DSHOW` backend uses the same `ICreateDevEnum` /
`CLSID_VideoInputDeviceCategory` path, so moniker order is positionally aligned with
`cv2.VideoCapture(N, CAP_DSHOW)`.

Per-device data:

- **Name:** `IPropertyBag::Read("FriendlyName")` — the OS-supplied display name
  (e.g. `"Microsoft® LifeCam Studio(TM)"`)
- **Unique ID:** `IPropertyBag::Read("DevicePath")` when present; falls back to
  `FriendlyName` (virtual drivers may omit `DevicePath`)
- **Resolutions:** `IMoniker::BindToObject(IBaseFilter)` → `IBaseFilter::EnumPins`
  → output pins → `IPin::EnumMediaTypes` → `AM_MEDIA_TYPE` structures with
  `formattype == FORMAT_VideoInfo` are cast to `VIDEOINFOHEADER`; `biWidth` /
  `abs(biHeight)` are collected and deduplicated

#### COM interface definitions

`quartz.dll`'s typelib (`QuartzTypeLib`) exposes filter-graph rendering interfaces
only. `CLSID_SystemDeviceEnum`, `ICreateDevEnum`, and `CLSID_VideoInputDeviceCategory`
live in `devenum.dll`, which has no typelib. The previous
`comtypes.client.GetModule("quartz.dll")` / `from comtypes.gen import DirectShowLib`
pattern therefore silently returned an empty device list on every Windows system.

The current implementation defines all required interfaces directly as
`comtypes.IUnknown` subclasses inside `_define_directshow_interfaces()`, called
once on first use (lazy sentinel `_DS_INTERFACES_DEFINED`). The defined interfaces
and GUIDs are stored as module-level `_DS_*` globals. `IPropertyBag` is imported
from `comtypes.persist`, which already defines it correctly.

`IPin._methods_` includes vtable-slot placeholders for `Connect`,
`ReceiveConnection`, and `ConnectedTo` (parameters typed as `c_void_p` to avoid the
self-reference problem at class-body evaluation time). Only `QueryDirection` (slot 7)
and `EnumMediaTypes` (slot 10) are actually called; the placeholders keep the vtable
offsets correct.

#### Fallback

If `comtypes` is not installed, a `WARNING`-level log message is emitted and `[]` is
returned. `comtypes` is listed in `requirements.txt` with a `sys_platform == "win32"`
marker; run `pip install comtypes` if it is missing.

---

### Linux — V4L2 (stdlib only)

**Entry point:** `_enumerate_devices_v4l2()`.

Scans `/dev/video0` through `/dev/video15`. Each path is probed with
`VIDIOC_QUERYCAP` (ioctl `0x80685600`) to confirm it is a video capture device
and to read the card name from bytes 16–48 of `v4l2_capability`. Non-capture
nodes (e.g. metadata, M2M) are skipped.

Per-device resolution list is built by `_enumerate_v4l2(N)`:

1. `VIDIOC_ENUM_FMT` iterates pixel formats until `EINVAL`.
2. For each format, `VIDIOC_ENUM_FRAMESIZES` iterates discrete frame sizes.
   Stepwise and continuous types are skipped (only discrete sizes are reported).
3. Duplicates across formats are deduplicated.

`DeviceInfo.index` equals N from `/dev/videoN`, matching what
`cv2.VideoCapture(N, CAP_V4L2)` opens. On systems with non-contiguous video nodes
(e.g. `/dev/video0`, `/dev/video2`), `index` will reflect the actual node number,
not the menu position. `kvm.py` uses `_camera_index()` to translate menu position
to the correct `DeviceInfo.index` before calling `cv2.VideoCapture`.

No extra dependencies required — `fcntl` and `struct` are stdlib.

---

## Data flow summary

```
enumerate_devices()                   # resolution_probe.py
  └─ _enumerate_devices_{platform}()
       ├─ [macOS]   AVCaptureDeviceDiscoverySession  → DeviceInfo list
       ├─ [Windows] ICreateDevEnum / IPropertyBag    → DeviceInfo list
       └─ [Linux]   VIDIOC_QUERYCAP / VIDIOC_ENUM_*  → DeviceInfo list

CaptureDevice.getCameras()            # video.py
  └─ calls enumerate_devices()
  └─ wraps each DeviceInfo in CameraProperties.from_device_info()
  └─ [fallback] _fallback_enumerate_opencv() if list is empty

KVMQtGui._populate_resolution_menu() # kvm.py
  └─ reads CameraProperties.resolutions (already cached, no re-enumeration)

CaptureDevice.setCamera()            # video.py
  └─ cv2.VideoCapture(CameraProperties.index, CAMERA_BACKEND)
  └─ first and only device open per session
```

## Known limitations

- **Identical duplicate devices** (two identical HDMI capture cards) cannot be
  reliably disambiguated. Their resolutions are behaviourally equivalent for KVM
  use, so swapping them is harmless.
- **fps on Windows** is always reported as `0` — `AM_MEDIA_TYPE` carries
  `AvgTimePerFrame` (100ns units) but the current parser does not convert it.
- **Linux stepwise/continuous frame sizes** are skipped; devices that do not report
  discrete sizes will show an empty resolution list and fall back to
  `RESOLUTION_PRESETS`.
- **AVFoundation index reversal** is an OpenCV implementation detail, not a
  documented API contract. The alignment script must be re-run after OpenCV upgrades to check the upstream implementation remains the same.
