#!/usr/bin/env python
"""
Cross-platform video device resolution enumeration.

Uses native platform APIs to discover supported resolutions for a capture device:
  - Linux:   V4L2 ioctl (fcntl stdlib, no extra deps)
  - macOS:   AVFoundation via pyobjc-framework-AVFoundation
  - Windows: DirectShow via comtypes

Falls back to an empty list on failure; callers should present a curated preset
list in that case.
"""

import logging
import sys
from typing import List, NamedTuple, Tuple

logger = logging.getLogger(__name__)

Resolution = Tuple[int, int]

# Ordered preset list used as fallback when enumeration is unavailable or fails.
RESOLUTION_PRESETS: List[Resolution] = [
    (640, 480),
    (800, 600),
    (1024, 768),
    (1280, 720),
    (1280, 1024),
    (1360, 768),
    (1920, 1080),
    (2560, 1440),
    (3840, 2160),
]


class DeviceInfo(NamedTuple):
    """
    Platform-native description of a video capture device.

    Returned by enumerate_devices(); consumed by CaptureDevice.getCameras() to
    build CameraProperties without opening any device.

    Fields:
        index       — OpenCV capture index (same ordering as the native enumerator).
        name        — Human-readable device name from the OS.
        unique_id   — Platform-specific stable identifier: macOS uniqueID,
                      Windows filter name (DevicePath unavailable without IPropertyBag),
                      Linux /dev/videoN path.
        resolutions — All (width, height) pairs supported by the device, sorted.
        default_resolution — Active/preferred resolution at enumeration time.
        fps         — Maximum fps reported by the active format (0 if unknown).
    """

    index: int
    name: str
    unique_id: str
    resolutions: List[Resolution]
    default_resolution: Resolution
    fps: int


def enumerate_devices() -> List[DeviceInfo]:
    """
    Return fully-populated DeviceInfo for all video capture devices without
    opening any device.

    Uses the same native enumerator as OpenCV for each platform so that
    DeviceInfo.index is positionally aligned with cv2.VideoCapture(index).
    Returns an empty list if enumeration is unavailable or fails.
    """
    logger.debug("Enumerating video devices on %s", sys.platform)
    try:
        if sys.platform == "linux":
            return _enumerate_devices_v4l2()
        elif sys.platform == "darwin":
            return _enumerate_devices_avfoundation()
        elif sys.platform == "win32":
            return _enumerate_devices_directshow()
        else:
            logger.debug("Device enumeration not implemented for platform %s", sys.platform)
    except Exception:
        logger.debug("Device enumeration failed", exc_info=True)
    return []


def enumerate_resolutions(device_index: int) -> List[Resolution]:
    """
    Return a list of (width, height) tuples supported by the capture device.

    Returns an empty list if enumeration is not available on this platform or
    if the device cannot be queried.
    """
    logger.debug("Enumerating resolutions for device %d on %s", device_index, sys.platform)
    try:
        if sys.platform == "linux":
            return _enumerate_v4l2(device_index)
        elif sys.platform == "darwin":
            return _enumerate_avfoundation(device_index)
        elif sys.platform == "win32":
            return _enumerate_directshow(device_index)
        else:
            logger.debug("Resolution enumeration not implemented for platform %s", sys.platform)
    except Exception:
        logger.debug("Resolution enumeration failed", exc_info=True)
    return []


# ---------------------------------------------------------------------------
# Linux — V4L2 via ioctl
# ---------------------------------------------------------------------------


def _enumerate_v4l2(device_index: int) -> List[Resolution]:
    """
    Enumerate supported resolutions for a V4L2 capture device via ioctl.

    Opens /dev/videoN and issues VIDIOC_ENUM_FMT to iterate over pixel formats,
    then VIDIOC_ENUM_FRAMESIZES to collect discrete (width, height) pairs for each
    format. Stepwise and continuous frame-size types are skipped. Duplicate
    resolutions reported across multiple pixel formats are deduplicated.

    Returns an empty list if the device cannot be opened or no discrete sizes
    are reported.

    References:
        VIDIOC_ENUM_FMT:
            https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/vidioc-enum-fmt.html
        VIDIOC_ENUM_FRAMESIZES / v4l2_frmsizeenum:
            https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/vidioc-enum-framesizes.html
    """
    import fcntl
    import struct

    # V4L2 ioctl numbers and struct formats (from <linux/videodev2.h>)
    VIDIOC_ENUM_FMT = 0xC0405602
    VIDIOC_ENUM_FRAMESIZES = 0xC02C564F

    V4L2_FRMSIZE_TYPE_DISCRETE = 1

    device_path = f"/dev/video{device_index}"
    try:
        fd = open(device_path, "rb")
    except OSError:
        logger.debug("V4L2: cannot open %s", device_path)
        return []

    logger.debug("V4L2: opened %s", device_path)
    resolutions: List[Resolution] = []
    seen: set = set()

    try:
        fmt_index = 0
        while True:
            # Loop termination relies on fcntl.ioctl raising OSError when fmt_index exceeds the
            # device's format count. The V4L2 spec guarantees EINVAL for out-of-range indices, so
            # compliant kernel drivers *should* always break out.

            # struct v4l2_fmtdesc: u32 index, u32 type, u32 flags, u8[32] desc, u32 pixelformat, u32[4] reserved
            fmt_buf = struct.pack("=II32sII4I", fmt_index, 1, b"", 0, 0, 0, 0, 0, 0)
            try:
                result = fcntl.ioctl(fd, VIDIOC_ENUM_FMT, fmt_buf)
            except OSError:
                break

            pixelformat = struct.unpack("=II32sII4I", result)[3]
            logger.debug("V4L2: format index %d, pixelformat 0x%08X", fmt_index, pixelformat)

            size_index = 0
            while True:
                # Loop termination: ioctl raises OSError (EINVAL) when size_index exceeds the
                # discrete frame count, or the else-branch breaks on stepwise/continuous types.

                # struct v4l2_frmsizeenum: u32 index, u32 pixel_format, u32 type,
                # then union (discrete: u32 w, u32 h  OR  stepwise: 6×u32)
                size_buf = struct.pack("=III8I", size_index, pixelformat, 0, 0, 0, 0, 0, 0, 0, 0, 0)
                try:
                    result = fcntl.ioctl(fd, VIDIOC_ENUM_FRAMESIZES, size_buf)
                except OSError:
                    break

                unpacked = struct.unpack("=III8I", result)
                frmsize_type = unpacked[2]
                if frmsize_type == V4L2_FRMSIZE_TYPE_DISCRETE:
                    width, height = unpacked[3], unpacked[4]
                    if (width, height) not in seen:
                        seen.add((width, height))
                        resolutions.append((width, height))
                        logger.debug("V4L2: found %dx%d", width, height)
                else:
                    logger.debug(
                        "V4L2: pixelformat 0x%08X is stepwise/continuous, skipping", pixelformat
                    )
                    break

                size_index += 1

            fmt_index += 1
    finally:
        fd.close()

    resolutions.sort()
    logger.info("V4L2: enumerated %d resolution(s) from %s", len(resolutions), device_path)
    return resolutions


# ---------------------------------------------------------------------------
# Full-device enumeration — returns DeviceInfo without opening any device
# ---------------------------------------------------------------------------


def _enumerate_devices_v4l2() -> List[DeviceInfo]:
    """
    Enumerate V4L2 capture devices by scanning /dev/video0..15.

    Probes each path with VIDIOC_QUERYCAP; skips entries that are not video
    capture devices. The DeviceInfo.index matches the N in /dev/videoN, which
    is the same index cv2.VideoCapture(N, CAP_V4L2) opens.

    Returns an empty list if no devices are found or fcntl is unavailable.
    """
    import fcntl
    import struct

    VIDIOC_QUERYCAP = 0x80685600
    V4L2_CAP_VIDEO_CAPTURE = 0x00000001
    # struct v4l2_capability: u8[16] driver, u8[32] card, u8[32] bus_info,
    # u32 version, u32 capabilities, u32 device_caps, u32[3] reserved = 104 bytes
    CAP_BUF_SIZE = 104

    result: List[DeviceInfo] = []
    for n in range(16):
        device_path = f"/dev/video{n}"
        try:
            fd = open(device_path, "rb")
        except OSError:
            continue
        try:
            cap_buf = b"\x00" * CAP_BUF_SIZE
            cap_buf = fcntl.ioctl(fd, VIDIOC_QUERYCAP, cap_buf)
            caps = struct.unpack_from("=I", cap_buf, 80)[0]
            if not (caps & V4L2_CAP_VIDEO_CAPTURE):
                continue
            name = cap_buf[16:48].rstrip(b"\x00").decode("utf-8", errors="replace") or device_path
        except Exception:
            name = device_path
        finally:
            fd.close()

        resolutions = _enumerate_v4l2(n)
        default_res = resolutions[-1] if resolutions else (1920, 1080)
        logger.info("V4L2: device %d '%s': %d resolution(s)", n, name, len(resolutions))
        result.append(
            DeviceInfo(
                index=n,
                name=name,
                unique_id=device_path,
                resolutions=resolutions,
                default_resolution=default_res,
                fps=0,
            )
        )

    return result


def _enumerate_devices_avfoundation() -> List[DeviceInfo]:
    """
    Return DeviceInfo for all macOS capture devices using AVFoundation.

    Requires pyobjc-framework-AVFoundation. Uses the same discovery session as
    OpenCV (via _avfoundation_device_list) so indices are positionally aligned.
    Default resolution comes from the device's activeFormat; fps is the maximum
    from activeFormat.videoSupportedFrameRateRanges.
    """
    try:
        import AVFoundation
        import CoreMedia
    except ImportError:
        logger.debug("pyobjc-framework-AVFoundation not available")
        return []

    devices = _avfoundation_device_list(AVFoundation)
    result: List[DeviceInfo] = []

    for index, device in enumerate(devices):
        name = f"Camera {index}"
        unique_id = str(index)
        resolutions: List[Resolution] = []
        default_res: Resolution = (1920, 1080)
        fps = 0

        try:
            name = str(device.localizedName())
        except Exception:
            pass
        try:
            unique_id = str(device.uniqueID())
        except Exception:
            pass

        try:
            active_fmt = device.activeFormat()
            if active_fmt:
                desc = active_fmt.formatDescription()
                dims = CoreMedia.CMVideoFormatDescriptionGetDimensions(desc)
                default_res = (int(dims.width), int(dims.height))
                for rate_range in active_fmt.videoSupportedFrameRateRanges():
                    try:
                        f = int(rate_range.maxFrameRate())
                        if f > fps:
                            fps = f
                    except Exception:
                        pass
        except Exception:
            logger.debug("AVFoundation: failed to read active format for '%s'", name, exc_info=True)

        seen: set = set()
        try:
            for fmt in device.formats():
                try:
                    desc = fmt.formatDescription()
                    dims = CoreMedia.CMVideoFormatDescriptionGetDimensions(desc)
                    w, h = int(dims.width), int(dims.height)
                    if (w, h) not in seen:
                        seen.add((w, h))
                        resolutions.append((w, h))
                except Exception:
                    pass
        except Exception:
            logger.debug("AVFoundation: failed to enumerate formats for '%s'", name, exc_info=True)

        resolutions.sort()
        if not resolutions and default_res != (0, 0):
            resolutions = [default_res]

        logger.info(
            "AVFoundation: device %d '%s': %d resolution(s), default %dx%d @ %dfps",
            index,
            name,
            len(resolutions),
            default_res[0],
            default_res[1],
            fps,
        )
        result.append(
            DeviceInfo(
                index=index,
                name=name,
                unique_id=unique_id,
                resolutions=resolutions,
                default_resolution=default_res,
                fps=fps,
            )
        )

    return result


def _enumerate_devices_directshow() -> List[DeviceInfo]:
    """
    Return DeviceInfo for all Windows DirectShow video capture devices.

    Requires comtypes. Uses the same ICreateDevEnum path as _directshow_resolutions
    so indices are positionally aligned with OpenCV's CAP_DSHOW backend. Device
    name comes from IPropertyBag.Read("FriendlyName") on each moniker's storage,
    the canonical DirectShow pattern. Returns an empty list if comtypes is
    unavailable or enumeration fails.
    """
    logger.info("DirectShow: starting device enumeration")
    try:
        import comtypes  # noqa: F401
        import comtypes.client  # noqa: F401
    except ImportError:
        logger.warning(
            "DirectShow: comtypes not installed — device enumeration unavailable. "
            "Run: pip install comtypes"
        )
        return []

    try:
        devices = _directshow_devices()
        logger.info("DirectShow: enumeration complete — %d device(s)", len(devices))
        return devices
    except Exception:
        logger.warning("DirectShow: device enumeration failed", exc_info=True)
        return []


def _directshow_devices() -> List[DeviceInfo]:
    """
    Walk DirectShow monikers and build DeviceInfo for each capture device.

    For each moniker we call IMoniker::BindToStorage to obtain an IPropertyBag,
    then Read("FriendlyName") — the documented way to retrieve a capture
    device's display name without instantiating its filter. DevicePath is read
    when available to form a stable unique_id.

    References:
        Enumerating Devices and Filters:
            https://learn.microsoft.com/en-us/windows/win32/directshow/enumerating-devices-and-filters
    """
    from comtypes.automation import VARIANT
    from comtypes.persist import IPropertyBag

    monikers = _ds_enum_monikers()
    logger.info("DirectShow: %d moniker(s) to inspect", len(monikers))
    result: List[DeviceInfo] = []
    for index, moniker in enumerate(monikers):
        logger.debug("DirectShow: reading property bag for moniker %d", index)
        name = f"Camera {index}"
        unique_id = f"dshow:{index}"

        try:
            prop_bag = moniker.BindToStorage(None, None, IPropertyBag._iid_)
            var = VARIANT()
            prop_bag.Read("FriendlyName", var, None)
            if var.value:
                name = str(var.value)
                unique_id = name
                logger.debug("DirectShow: moniker %d FriendlyName='%s'", index, name)
            else:
                logger.debug("DirectShow: moniker %d has empty FriendlyName", index)
            try:
                dev_path = VARIANT()
                prop_bag.Read("DevicePath", dev_path, None)
                if dev_path.value:
                    unique_id = str(dev_path.value)
                    logger.debug("DirectShow: moniker %d DevicePath='%s'", index, unique_id)
            except Exception:
                # DevicePath is absent for some virtual drivers — not fatal.
                logger.debug("DirectShow: moniker %d has no DevicePath", index)
        except Exception:
            logger.warning(
                "DirectShow: failed to read property bag for device %d", index, exc_info=True
            )

        logger.debug("DirectShow: walking media types for device %d ('%s')", index, name)
        resolutions = _directshow_resolutions(index)
        default_res = resolutions[-1] if resolutions else (1920, 1080)
        logger.info(
            "DirectShow: device %d '%s': %d resolution(s), default %dx%d",
            index,
            name,
            len(resolutions),
            default_res[0],
            default_res[1],
        )
        result.append(
            DeviceInfo(
                index=index,
                name=name,
                unique_id=unique_id,
                resolutions=resolutions,
                default_resolution=default_res,
                fps=0,
            )
        )

    return result


# ---------------------------------------------------------------------------
# macOS — AVFoundation via pyobjc
# ---------------------------------------------------------------------------


def _avfoundation_device_list(AVFoundation) -> list:
    """
    Return the ordered list of AVCaptureDevice objects using the same discovery
    session as OpenCV's CAP_AVFOUNDATION backend.

    OpenCV uses AVCaptureDeviceDiscoverySession with BuiltInWideAngleCamera +
    External device types (see cap_avfoundation_mac.mm). Using the deprecated
    devicesWithMediaType_ instead applies a different filter and produces a
    different device ordering when multiple cameras are present, breaking the
    positional mapping between our resolution enumeration and OpenCV indices.

    Falls back to devicesWithMediaType_ if the discovery session API is
    unavailable (pre-10.15 systems or unexpected AVFoundation layout).

    References:
        AVCaptureDeviceDiscoverySession:
            https://developer.apple.com/documentation/avfoundation/avcapturedevicediscoverysession
        OpenCV cap_avfoundation_mac.mm:
            https://github.com/opencv/opencv/blob/4.x/modules/videoio/src/cap_avfoundation_mac.mm
    """
    try:
        # AVCaptureDeviceTypeExternal was added in macOS 14; fall back to the
        # deprecated ExternalUnknown on older systems (available since macOS 10.15).
        try:
            external_type = AVFoundation.AVCaptureDeviceTypeExternal
        except AttributeError:
            external_type = AVFoundation.AVCaptureDeviceTypeExternalUnknown

        device_types = [
            AVFoundation.AVCaptureDeviceTypeBuiltInWideAngleCamera,
            external_type,
        ]
        session = AVFoundation.AVCaptureDeviceDiscoverySession.discoverySessionWithDeviceTypes_mediaType_position_(
            device_types,
            AVFoundation.AVMediaTypeVideo,
            AVFoundation.AVCaptureDevicePositionUnspecified,
        )
        # OpenCV's CAP_AVFOUNDATION backend iterates DiscoverySession devices in
        # reverse order (verified empirically via scripts/verify_avfoundation_alignment.py
        # with N cameras attached — OpenCV idx N maps to session idx (count-1-N)).
        # Reverse here so our indices line up with cv2.VideoCapture(idx).
        devices = list(session.devices())[::-1]
        logger.debug(
            "AVFoundation: discovery session returned %d device(s) (reversed for OpenCV alignment)",
            len(devices),
        )
        return devices
    except Exception:
        logger.debug(
            "AVFoundation: discovery session unavailable, falling back to devicesWithMediaType_",
            exc_info=True,
        )
        # Same reversal applies to the legacy API path; see comment above.
        return list(
            AVFoundation.AVCaptureDevice.devicesWithMediaType_(AVFoundation.AVMediaTypeVideo)
        )[::-1]


def _enumerate_avfoundation(device_index: int) -> List[Resolution]:
    """
    Enumerate supported resolutions for a macOS capture device via AVFoundation.

    Requires `pyobjc-framework-AVFoundation` (optional dependency); returns an
    empty list if the import fails. Uses AVCaptureDeviceDiscoverySession with
    the same device types as OpenCV's CAP_AVFOUNDATION backend so that device
    indices are aligned between resolution enumeration and frame capture.
    Iterates the device's format list and extracts CMVideoDimensions via
    CoreMedia.CMVideoFormatDescriptionGetDimensions. Duplicate resolutions
    across formats are deduplicated.

    References:
        AVCaptureDeviceDiscoverySession:
            https://developer.apple.com/documentation/avfoundation/avcapturedevicediscoverysession
        AVCaptureDevice.formats:
            https://developer.apple.com/documentation/avfoundation/avcapturedevice/formats
        CMVideoFormatDescriptionGetDimensions:
            https://developer.apple.com/documentation/coremedia/cmvideoformatdescriptiongetdimensions(_:)
    """
    try:
        import AVFoundation
        import CoreMedia
    except ImportError:
        logger.debug("pyobjc-framework-AVFoundation not available")
        return []

    devices = _avfoundation_device_list(AVFoundation)
    logger.debug("AVFoundation: %d capture device(s) found", len(devices))
    if device_index >= len(devices):
        logger.debug("AVFoundation: no device at index %d", device_index)
        return []

    device = devices[device_index]
    try:
        device_name = device.localizedName()
    except Exception:
        device_name = f"device[{device_index}]"
    logger.debug("AVFoundation: querying '%s'", device_name)

    resolutions: List[Resolution] = []
    seen: set = set()

    for fmt in device.formats():
        desc = fmt.formatDescription()
        dims = CoreMedia.CMVideoFormatDescriptionGetDimensions(desc)
        w, h = int(dims.width), int(dims.height)
        if (w, h) not in seen:
            seen.add((w, h))
            resolutions.append((w, h))
            logger.debug("AVFoundation: found %dx%d", w, h)

    resolutions.sort()
    logger.info("AVFoundation: enumerated %d resolution(s) for '%s'", len(resolutions), device_name)
    return resolutions


# ---------------------------------------------------------------------------
# Windows — DirectShow via comtypes (interface definitions, no typelib needed)
# ---------------------------------------------------------------------------

# These are module-level so they're defined once and reused across calls.
# Defined inside a function-like block guarded by TYPE_CHECKING would hide
# them from the interpreter; we use a lazy sentinel instead.
_DS_INTERFACES_DEFINED = False


def _define_directshow_interfaces():
    """
    Define the minimal set of DirectShow COM interfaces needed for device
    enumeration and resolution discovery, using comtypes without any typelib.

    quartz.dll's typelib (QuartzTypeLib) exposes rendering interfaces only —
    ICreateDevEnum, IEnumMoniker, IBaseFilter, etc. are not in it. Defining
    them directly here avoids the GetModule("quartz.dll") / DirectShowLib
    import pattern that silently fails on systems where the generated module
    name doesn't match.

    References:
        ICreateDevEnum / IEnumMoniker / IMoniker:
            https://learn.microsoft.com/en-us/windows/win32/api/strmif/nn-strmif-icreatedevenum
        IBaseFilter / IEnumPins / IPin / IEnumMediaTypes:
            https://learn.microsoft.com/en-us/windows/win32/api/strmif/
        AM_MEDIA_TYPE / VIDEOINFOHEADER:
            https://learn.microsoft.com/en-us/previous-versions/windows/desktop/api/amvideo/ns-amvideo-videoinfoheader
        IPropertyBag (in comtypes.persist):
            https://learn.microsoft.com/en-us/windows/win32/api/oaidl/nn-oaidl-ipropertybag
    """
    global _DS_INTERFACES_DEFINED
    if _DS_INTERFACES_DEFINED:
        return
    _DS_INTERFACES_DEFINED = True
    logger.debug("DirectShow: defining COM interfaces (first call)")

    import ctypes
    import comtypes

    # -- Structures ----------------------------------------------------------

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.c_ulong),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", ctypes.c_ushort),
            ("biBitCount", ctypes.c_ushort),
            ("biCompression", ctypes.c_ulong),
            ("biSizeImage", ctypes.c_ulong),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", ctypes.c_ulong),
            ("biClrImportant", ctypes.c_ulong),
        ]

    class VIDEOINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("rcSource", RECT),
            ("rcTarget", RECT),
            ("dwBitRate", ctypes.c_ulong),
            ("dwBitErrorRate", ctypes.c_ulong),
            ("AvgTimePerFrame", ctypes.c_longlong),
            ("bmiHeader", BITMAPINFOHEADER),
        ]

    class AM_MEDIA_TYPE(ctypes.Structure):
        _fields_ = [
            ("majortype", comtypes.GUID),
            ("subtype", comtypes.GUID),
            ("bFixedSizeSamples", ctypes.c_int),
            ("bTemporalCompression", ctypes.c_int),
            ("lSampleSize", ctypes.c_ulong),
            ("formattype", comtypes.GUID),
            ("pUnk", ctypes.c_void_p),
            ("cbFormat", ctypes.c_ulong),
            ("pbFormat", ctypes.c_void_p),
        ]

    # -- Interface definitions -----------------------------------------------

    # IPropertyBag lives in comtypes.persist; we need it inline so BindToStorage's
    # out-pointer can be typed correctly (saves a ctypes.cast on every call).
    from comtypes.persist import IPropertyBag

    class IEnumMoniker(comtypes.IUnknown):
        _iid_ = comtypes.GUID("{00000102-0000-0000-C000-000000000046}")
        _methods_ = [
            # Next's rgelt is typed as POINTER(POINTER(IUnknown)) rather than a raw
            # void_p so comtypes wraps the returned pointer into an IUnknown proxy
            # — callers then QueryInterface(IMoniker) to access IMoniker methods.
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "Next",
                (["in"], ctypes.c_ulong, "celt"),
                (["out"], ctypes.POINTER(ctypes.POINTER(comtypes.IUnknown)), "rgelt"),
                (["out"], ctypes.POINTER(ctypes.c_ulong), "pceltFetched"),
            ),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "Skip",
                (["in"], ctypes.c_ulong, "celt"),
            ),
            comtypes.COMMETHOD([], comtypes.HRESULT, "Reset"),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "Clone",
                (["out"], ctypes.POINTER(ctypes.c_void_p), "ppenum"),
            ),
        ]

    class ICreateDevEnum(comtypes.IUnknown):
        _iid_ = comtypes.GUID("{29840822-5B84-11D0-BD3B-00A0C911CE86}")
        _methods_ = [
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "CreateClassEnumerator",
                (["in"], ctypes.POINTER(comtypes.GUID), "clsidDeviceClass"),
                (["out"], ctypes.POINTER(ctypes.POINTER(IEnumMoniker)), "ppEnumMoniker"),
                (["in"], ctypes.c_ulong, "dwFlags"),
            ),
        ]

    class IEnumMediaTypes(comtypes.IUnknown):
        _iid_ = comtypes.GUID("{89C31040-846B-11CE-97D3-00AA0055595A}")
        _methods_ = [
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "Next",
                (["in"], ctypes.c_ulong, "celt"),
                (["out"], ctypes.POINTER(ctypes.POINTER(AM_MEDIA_TYPE)), "rgelt"),
                (["out"], ctypes.POINTER(ctypes.c_ulong), "pceltFetched"),
            ),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "Skip",
                (["in"], ctypes.c_ulong, "celt"),
            ),
            comtypes.COMMETHOD([], comtypes.HRESULT, "Reset"),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "Clone",
                (["out"], ctypes.POINTER(ctypes.c_void_p), "ppenum"),
            ),
        ]

    class IPin(comtypes.IUnknown):
        _iid_ = comtypes.GUID("{56A86891-0AD4-11CE-B03A-0020AF0BA770}")
        # Vtable order is load-bearing: only QueryDirection (slot 7) and
        # EnumMediaTypes (slot 10) are called, but the earlier slots must be
        # present so those offsets are correct. IPin self-references in
        # Connect / ReceiveConnection / ConnectedTo are replaced with c_void_p
        # because IPin isn't yet defined at class-body evaluation time.
        _methods_ = [
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "Connect",
                (["in"], ctypes.c_void_p, "pReceivePin"),
                (["in"], ctypes.POINTER(AM_MEDIA_TYPE), "pmt"),
            ),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "ReceiveConnection",
                (["in"], ctypes.c_void_p, "pConnector"),
                (["in"], ctypes.POINTER(AM_MEDIA_TYPE), "pmt"),
            ),
            comtypes.COMMETHOD([], comtypes.HRESULT, "Disconnect"),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "ConnectedTo",
                (["out"], ctypes.POINTER(ctypes.c_void_p), "pPin"),
            ),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "ConnectionMediaType",
                (["out"], ctypes.POINTER(AM_MEDIA_TYPE), "pmt"),
            ),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "QueryPinInfo",
                (["out"], ctypes.c_void_p, "pInfo"),
            ),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "QueryDirection",
                (["out"], ctypes.POINTER(ctypes.c_int), "pPinDir"),
            ),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "QueryId",
                (["out"], ctypes.POINTER(ctypes.c_wchar_p), "Id"),
            ),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "QueryAccept",
                (["in"], ctypes.POINTER(AM_MEDIA_TYPE), "pmt"),
            ),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "EnumMediaTypes",
                (["out"], ctypes.POINTER(ctypes.POINTER(IEnumMediaTypes)), "ppEnum"),
            ),
        ]

    class IEnumPins(comtypes.IUnknown):
        _iid_ = comtypes.GUID("{56A86892-0AD4-11CE-B03A-0020AF0BA770}")
        _methods_ = [
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "Next",
                (["in"], ctypes.c_ulong, "celt"),
                (["out"], ctypes.POINTER(ctypes.POINTER(IPin)), "rgelt"),
                (["out"], ctypes.POINTER(ctypes.c_ulong), "pceltFetched"),
            ),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "Skip",
                (["in"], ctypes.c_ulong, "celt"),
            ),
            comtypes.COMMETHOD([], comtypes.HRESULT, "Reset"),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "Clone",
                (["out"], ctypes.POINTER(ctypes.c_void_p), "ppenum"),
            ),
        ]

    class IBaseFilter(comtypes.IUnknown):
        _iid_ = comtypes.GUID("{56A86895-0AD4-11CE-B03A-0020AF0BA770}")
        _methods_ = [
            # IMediaFilter methods (inherited, must appear in vtable order)
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "GetClassID",
                (["out"], ctypes.POINTER(comtypes.GUID), "pClassID"),
            ),
            comtypes.COMMETHOD([], comtypes.HRESULT, "Stop"),
            comtypes.COMMETHOD([], comtypes.HRESULT, "Pause"),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "Run",
                (["in"], ctypes.c_longlong, "tStart"),
            ),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "GetState",
                (["in"], ctypes.c_ulong, "dwMilliSecsTimeout"),
                (["out"], ctypes.POINTER(ctypes.c_int), "State"),
            ),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "SetSyncSource",
                (["in"], ctypes.c_void_p, "pClock"),
            ),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "GetSyncSource",
                (["out"], ctypes.POINTER(ctypes.c_void_p), "pClock"),
            ),
            # IBaseFilter methods
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "EnumPins",
                (["out"], ctypes.POINTER(ctypes.POINTER(IEnumPins)), "ppEnum"),
            ),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "FindPin",
                (["in"], ctypes.c_wchar_p, "Id"),
                (["out"], ctypes.POINTER(ctypes.POINTER(IPin)), "ppPin"),
            ),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "QueryFilterInfo",
                (["out"], ctypes.c_void_p, "pInfo"),
            ),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "JoinFilterGraph",
                (["in"], ctypes.c_void_p, "pGraph"),
                (["in"], ctypes.c_wchar_p, "pName"),
            ),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "QueryVendorInfo",
                (["out"], ctypes.POINTER(ctypes.c_wchar_p), "pVendorInfo"),
            ),
        ]

    class IMoniker(comtypes.IUnknown):
        _iid_ = comtypes.GUID("{0000000F-0000-0000-C000-000000000046}")
        _methods_ = [
            # IPersist
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "GetClassID",
                (["out"], ctypes.POINTER(comtypes.GUID), "pClassID"),
            ),
            # IPersistStream
            comtypes.COMMETHOD([], comtypes.HRESULT, "IsDirty"),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "Load",
                (["in"], ctypes.c_void_p, "pStm"),
            ),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "Save",
                (["in"], ctypes.c_void_p, "pStm"),
                (["in"], ctypes.c_int, "fClearDirty"),
            ),
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "GetSizeMax",
                (["out"], ctypes.POINTER(ctypes.c_ulonglong), "pcbSize"),
            ),
            # IMoniker
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "BindToObject",
                (["in"], ctypes.c_void_p, "pbc"),
                (["in"], ctypes.c_void_p, "pmkToLeft"),
                (["in"], ctypes.POINTER(comtypes.GUID), "riidResult"),
                (["out"], ctypes.POINTER(ctypes.POINTER(IBaseFilter)), "ppvResult"),
            ),
            # Typed to return POINTER(IPropertyBag) so callers get a usable
            # property-bag proxy directly — used for reading FriendlyName /
            # DevicePath off a device moniker.
            comtypes.COMMETHOD(
                [],
                comtypes.HRESULT,
                "BindToStorage",
                (["in"], ctypes.c_void_p, "pbc"),
                (["in"], ctypes.c_void_p, "pmkToLeft"),
                (["in"], ctypes.POINTER(comtypes.GUID), "riid"),
                (["out"], ctypes.POINTER(ctypes.POINTER(IPropertyBag)), "ppvObj"),
            ),
        ]

    # Store on module globals so callers can access them
    global _DS_ICreateDevEnum, _DS_IMoniker, _DS_IBaseFilter
    global _DS_IEnumPins, _DS_IPin, _DS_IEnumMediaTypes
    global _DS_AM_MEDIA_TYPE, _DS_VIDEOINFOHEADER
    global _DS_CLSID_SystemDeviceEnum, _DS_CLSID_VideoInputDeviceCategory
    global _DS_FORMAT_VideoInfo, _DS_IID_IBaseFilter, _DS_IID_IPropertyBag

    _DS_ICreateDevEnum = ICreateDevEnum
    _DS_IMoniker = IMoniker
    _DS_IBaseFilter = IBaseFilter
    _DS_IEnumPins = IEnumPins
    _DS_IPin = IPin
    _DS_IEnumMediaTypes = IEnumMediaTypes
    _DS_AM_MEDIA_TYPE = AM_MEDIA_TYPE
    _DS_VIDEOINFOHEADER = VIDEOINFOHEADER

    _DS_CLSID_SystemDeviceEnum = comtypes.GUID("{62BE5D10-60EB-11D0-BD3B-00A0C911CE86}")
    _DS_CLSID_VideoInputDeviceCategory = comtypes.GUID("{860BB310-5D01-11D0-BD3B-00A0C911CE86}")
    _DS_FORMAT_VideoInfo = comtypes.GUID("{05589F80-C356-11CE-BF01-00AA0055595A}")
    _DS_IID_IBaseFilter = comtypes.GUID("{56A86895-0AD4-11CE-B03A-0020AF0BA770}")
    _DS_IID_IPropertyBag = comtypes.GUID("{55272A00-42CB-11CE-8135-00AA004BB851}")


def _ds_enum_monikers():
    """Return list of IMoniker for all DirectShow video capture devices.

    IEnumMoniker::Next hands back IUnknown-typed pointers (see IEnumMoniker
    definition above for the rationale); we QueryInterface each one to IMoniker
    so that BindToObject / BindToStorage are callable on the returned proxies.
    CreateClassEnumerator returns None when the category is empty (S_FALSE).
    """
    import comtypes
    import comtypes.client

    _define_directshow_interfaces()

    logger.debug("DirectShow: creating SystemDeviceEnum")
    dev_enum = comtypes.client.CreateObject(
        _DS_CLSID_SystemDeviceEnum,
        interface=_DS_ICreateDevEnum,
    )
    logger.debug("DirectShow: creating class enumerator for VideoInputDeviceCategory")
    enum_moniker = dev_enum.CreateClassEnumerator(_DS_CLSID_VideoInputDeviceCategory, 0)
    if enum_moniker is None:
        logger.info("DirectShow: VideoInputDeviceCategory is empty (no capture devices)")
        return []

    monikers = []
    while True:
        try:
            punk, fetched = enum_moniker.Next(1)
            if fetched == 0:
                break
            moniker = punk.QueryInterface(_DS_IMoniker)
            logger.debug("DirectShow: moniker %d: QI to IMoniker ok", len(monikers))
            monikers.append(moniker)
        except comtypes.COMError:
            logger.debug("DirectShow: IEnumMoniker::Next raised COMError, stopping", exc_info=True)
            break
    logger.info("DirectShow: IEnumMoniker walk yielded %d moniker(s)", len(monikers))
    return monikers


def _enumerate_directshow(device_index: int) -> List[Resolution]:
    """
    Enumerate supported resolutions for a Windows capture device via DirectShow.

    Requires `comtypes` (optional dependency); returns an empty list if the import
    fails. Delegates to _directshow_resolutions for the actual COM enumeration,
    catching any exception it raises so that a partial or broken DirectShow
    environment degrades gracefully.
    """
    try:
        import comtypes  # noqa: F401
    except ImportError:
        logger.warning(
            "comtypes not installed — DirectShow resolution enumeration unavailable. "
            "Run: pip install comtypes"
        )
        return []

    try:
        return _directshow_resolutions(device_index)
    except Exception:
        logger.debug("DirectShow enumeration failed", exc_info=True)
        return []


def _directshow_resolutions(device_index: int) -> List[Resolution]:
    """
    Walk a DirectShow video capture filter's media types and collect resolutions.

    Uses ICreateDevEnum/IEnumMoniker to locate the video capture device at
    device_index, then IEnumPins to find its output pins (PINDIR_OUTPUT = 0).
    For each output pin, IEnumMediaTypes yields AM_MEDIA_TYPE structures; those
    with formattype FORMAT_VideoInfo are cast to VIDEOINFOHEADER to read
    biWidth/biHeight. Negative heights (top-down DIBs) are normalised with abs().

    Raises any COM or ctypes exception to the caller (_enumerate_directshow),
    which handles them as a graceful fallback.

    References:
        ICreateDevEnum:
            https://learn.microsoft.com/en-us/windows/win32/api/strmif/nn-strmif-icreatedevenum
        IEnumMoniker:
            https://learn.microsoft.com/en-us/windows/win32/api/objidl/nn-objidl-ienummoniker
        IEnumPins:
            https://learn.microsoft.com/en-us/windows/win32/api/strmif/nn-strmif-ienumpins
        IEnumMediaTypes:
            https://learn.microsoft.com/en-us/windows/win32/api/strmif/nn-strmif-ienummediatypes
        VIDEOINFOHEADER:
            https://learn.microsoft.com/en-us/previous-versions/windows/desktop/api/amvideo/ns-amvideo-videoinfoheader
    """
    import ctypes
    import comtypes

    monikers = _ds_enum_monikers()
    logger.debug("DirectShow: %d video capture device(s) found", len(monikers))
    if device_index >= len(monikers):
        logger.debug("DirectShow: no device at index %d", device_index)
        return []

    logger.debug("DirectShow: binding filter for device %d", device_index)
    filter_ = monikers[device_index].BindToObject(None, None, _DS_IID_IBaseFilter)
    logger.debug("DirectShow: enumerating pins for device %d", device_index)
    enum_pins = filter_.EnumPins()

    resolutions: List[Resolution] = []
    seen: set = set()
    pin_idx = 0

    while True:
        # Loop termination: IEnumPins::Next returns fetched == 0 when all pins have been visited.
        try:
            pin, fetched = enum_pins.Next(1)
            if fetched == 0:
                break
        except comtypes.COMError:
            logger.debug("DirectShow: IEnumPins::Next raised COMError", exc_info=True)
            break

        dir_val = ctypes.c_int(0)
        try:
            pin.QueryDirection(ctypes.byref(dir_val))
        except comtypes.COMError:
            logger.debug("DirectShow: pin %d QueryDirection failed", pin_idx, exc_info=True)
            pin_idx += 1
            continue
        if dir_val.value != 0:  # PINDIR_OUTPUT = 0
            logger.debug("DirectShow: pin %d is input (dir=%d), skipping", pin_idx, dir_val.value)
            pin_idx += 1
            continue

        logger.debug("DirectShow: pin %d is output, walking media types", pin_idx)
        try:
            enum_mt = pin.EnumMediaTypes()
        except comtypes.COMError:
            logger.debug("DirectShow: pin %d EnumMediaTypes failed", pin_idx, exc_info=True)
            pin_idx += 1
            continue

        while True:
            # Loop termination: IEnumMediaTypes::Next returns fetched == 0 when exhausted.
            try:
                mt_ptr, fetched = enum_mt.Next(1)
                if fetched == 0:
                    break
            except comtypes.COMError:
                break

            try:
                mt = mt_ptr.contents
                if mt.formattype == _DS_FORMAT_VideoInfo and mt.pbFormat:
                    vi = ctypes.cast(mt.pbFormat, ctypes.POINTER(_DS_VIDEOINFOHEADER)).contents
                    w, h = vi.bmiHeader.biWidth, abs(vi.bmiHeader.biHeight)
                    if w > 0 and h > 0 and (w, h) not in seen:
                        seen.add((w, h))
                        resolutions.append((w, h))
                        logger.debug("DirectShow: pin %d found %dx%d", pin_idx, w, h)
            except Exception:
                logger.debug("DirectShow: media-type parse failed", exc_info=True)

        pin_idx += 1

    resolutions.sort()
    logger.info(
        "DirectShow: enumerated %d resolution(s) for device %d", len(resolutions), device_index
    )
    return resolutions
