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
    name comes from IBaseFilter.QueryFilterInfo().achName (the filter's friendly
    name).  Returns an empty list if comtypes is unavailable or enumeration fails.
    """
    try:
        import comtypes
        import comtypes.client
    except ImportError:
        logger.debug("comtypes not available")
        return []

    try:
        return _directshow_devices()
    except Exception:
        logger.debug("DirectShow device enumeration failed", exc_info=True)
        return []


def _directshow_devices() -> List[DeviceInfo]:
    """Walk DirectShow monikers and build DeviceInfo for each capture device."""
    import comtypes
    import comtypes.client

    comtypes.client.GetModule("quartz.dll")
    from comtypes.gen import DirectShowLib as ds  # type: ignore

    dev_enum = comtypes.client.CreateObject(ds.CLSID_SystemDeviceEnum, interface=ds.ICreateDevEnum)
    enum_moniker = dev_enum.CreateClassEnumerator(ds.CLSID_VideoInputDeviceCategory, 0)
    if enum_moniker is None:
        return []

    monikers = []
    while True:
        try:
            moniker, fetched = enum_moniker.Next(1)
            if fetched == 0:
                break
            monikers.append(moniker)
        except comtypes.COMError:
            break

    result: List[DeviceInfo] = []
    for index, moniker in enumerate(monikers):
        name = f"Camera {index}"
        unique_id = f"dshow:{index}"

        try:
            filter_ = moniker.BindToObject(None, None, ds.IID_IBaseFilter)
            filter_info = filter_.QueryFilterInfo()
            if filter_info.achName:
                name = str(filter_info.achName)
                unique_id = name
        except Exception:
            logger.debug("DirectShow: failed to get filter name for device %d", index)

        resolutions = _directshow_resolutions(index)
        default_res = resolutions[-1] if resolutions else (1920, 1080)
        logger.info("DirectShow: device %d '%s': %d resolution(s)", index, name, len(resolutions))
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
# Windows — DirectShow via comtypes
# ---------------------------------------------------------------------------


def _enumerate_directshow(device_index: int) -> List[Resolution]:
    """
    Enumerate supported resolutions for a Windows capture device via DirectShow.

    Requires `comtypes` (optional dependency); returns an empty list if the import
    fails. Delegates to _directshow_resolutions for the actual COM enumeration,
    catching any exception it raises so that a partial or broken DirectShow
    environment degrades gracefully.
    """
    try:
        import comtypes
        import comtypes.client
    except ImportError:
        logger.debug("comtypes not available")
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
    import comtypes.client

    # Load DirectShow / quartz
    comtypes.client.GetModule("quartz.dll")
    from comtypes.gen import DirectShowLib as ds  # type: ignore

    # Create the system device enumerator
    dev_enum = comtypes.client.CreateObject(
        ds.CLSID_SystemDeviceEnum,
        interface=ds.ICreateDevEnum,
    )

    video_cap_guid = ds.CLSID_VideoInputDeviceCategory
    enum_moniker = dev_enum.CreateClassEnumerator(video_cap_guid, 0)
    if enum_moniker is None:
        return []

    monikers = []
    while True:
        # Loop termination: IEnumMoniker::Next returns fetched == 0 (COM S_FALSE) when the
        # device list is exhausted. COMError provides a secondary exit for broken enumerators.
        try:
            moniker, fetched = enum_moniker.Next(1)
            if fetched == 0:
                break
            monikers.append(moniker)
        except comtypes.COMError:
            break

    logger.debug("DirectShow: %d video capture device(s) found", len(monikers))
    if device_index >= len(monikers):
        logger.debug("DirectShow: no device at index %d", device_index)
        return []

    logger.debug("DirectShow: enumerating device at index %d", device_index)
    filter_ = monikers[device_index].BindToObject(None, None, ds.IID_IBaseFilter)
    enum_pins = filter_.EnumPins()

    resolutions: List[Resolution] = []
    seen: set = set()

    while True:
        # Loop termination: IEnumPins::Next returns fetched == 0 when all pins have been
        # visited. The two continue paths both return to the top of this loop, so Next is
        # always called to advance the enumerator before any per-pin processing is skipped.
        try:
            pin, fetched = enum_pins.Next(1)
            if fetched == 0:
                break
        except comtypes.COMError:
            break

        pin_info = pin.QueryPinInfo()
        if pin_info.dir != 0:  # PINDIR_OUTPUT = 0
            continue

        try:
            enum_mt = pin.EnumMediaTypes()
        except comtypes.COMError:
            continue

        while True:
            # Loop termination: IEnumMediaTypes::Next returns fetched == 0 when all
            # media types for this pin have been examined.
            try:
                mt, fetched = enum_mt.Next(1)
                if fetched == 0:
                    break
            except comtypes.COMError:
                break

            try:
                if mt.formattype == ds.FORMAT_VideoInfo:
                    vi = ctypes.cast(mt.pbFormat, ctypes.POINTER(ds.VIDEOINFOHEADER)).contents
                    w, h = vi.bmiHeader.biWidth, abs(vi.bmiHeader.biHeight)
                    if w > 0 and h > 0 and (w, h) not in seen:
                        seen.add((w, h))
                        resolutions.append((w, h))
                        logger.debug("DirectShow: found %dx%d", w, h)
            except Exception:
                pass

    resolutions.sort()
    logger.info(
        "DirectShow: enumerated %d resolution(s) for device %d", len(resolutions), device_index
    )
    return resolutions
