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
from typing import List, Tuple

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
# macOS — AVFoundation via pyobjc
# ---------------------------------------------------------------------------


def _enumerate_avfoundation(device_index: int) -> List[Resolution]:
    """
    Enumerate supported resolutions for a macOS capture device via AVFoundation.

    Requires `pyobjc-framework-AVFoundation` (optional dependency); returns an
    empty list if the import fails. Uses AVCaptureDevice.devicesWithMediaType_
    to list video devices, then iterates the device's format list and extracts
    CMVideoDimensions via CoreMedia.CMVideoFormatDescriptionGetDimensions.
    Duplicate resolutions across formats are deduplicated.

    References:
        AVCaptureDevice.devicesWithMediaType_:
            https://developer.apple.com/documentation/avfoundation/avcapturedevice/1390520-deviceswithmediatype
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

    devices = AVFoundation.AVCaptureDevice.devicesWithMediaType_(AVFoundation.AVMediaTypeVideo)
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
