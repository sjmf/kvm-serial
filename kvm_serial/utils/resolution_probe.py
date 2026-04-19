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
    try:
        if sys.platform == "linux":
            return _enumerate_v4l2(device_index)
        elif sys.platform == "darwin":
            return _enumerate_avfoundation(device_index)
        elif sys.platform == "win32":
            return _enumerate_directshow(device_index)
    except Exception:
        logger.debug("Resolution enumeration failed", exc_info=True)
    return []


# ---------------------------------------------------------------------------
# Linux — V4L2 via ioctl
# ---------------------------------------------------------------------------


def _enumerate_v4l2(device_index: int) -> List[Resolution]:
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
        logger.debug(f"Cannot open {device_path}")
        return []

    resolutions: List[Resolution] = []
    seen: set = set()

    try:
        fmt_index = 0
        while True:
            # struct v4l2_fmtdesc: u32 index, u32 type, u32 flags, u8[32] desc, u32 pixelformat, u32[4] reserved
            fmt_buf = struct.pack("=II32sII4I", fmt_index, 1, b"", 0, 0, 0, 0, 0, 0)
            try:
                result = fcntl.ioctl(fd, VIDIOC_ENUM_FMT, fmt_buf)
            except OSError:
                break

            pixelformat = struct.unpack("=II32sII4I", result)[3]

            size_index = 0
            while True:
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
                else:
                    # Stepwise or continuous — skip, not worth iterating
                    break

                size_index += 1

            fmt_index += 1
    finally:
        fd.close()

    resolutions.sort()
    return resolutions


# ---------------------------------------------------------------------------
# macOS — AVFoundation via pyobjc
# ---------------------------------------------------------------------------


def _enumerate_avfoundation(device_index: int) -> List[Resolution]:
    try:
        import AVFoundation
        import CoreMedia
    except ImportError:
        logger.debug("pyobjc-framework-AVFoundation not available")
        return []

    devices = AVFoundation.AVCaptureDevice.devicesWithMediaType_(AVFoundation.AVMediaTypeVideo)
    if device_index >= len(devices):
        logger.debug(f"AVFoundation: no device at index {device_index}")
        return []

    device = devices[device_index]
    resolutions: List[Resolution] = []
    seen: set = set()

    for fmt in device.formats():
        desc = fmt.formatDescription()
        dims = CoreMedia.CMVideoFormatDescriptionGetDimensions(desc)
        w, h = int(dims.width), int(dims.height)
        if (w, h) not in seen:
            seen.add((w, h))
            resolutions.append((w, h))

    resolutions.sort()
    return resolutions


# ---------------------------------------------------------------------------
# Windows — DirectShow via comtypes
# ---------------------------------------------------------------------------


def _enumerate_directshow(device_index: int) -> List[Resolution]:
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
    """Enumerate media types from a DirectShow video capture filter."""
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
        try:
            moniker, fetched = enum_moniker.Next(1)
            if fetched == 0:
                break
            monikers.append(moniker)
        except comtypes.COMError:
            break

    if device_index >= len(monikers):
        return []

    filter_ = monikers[device_index].BindToObject(None, None, ds.IID_IBaseFilter)
    enum_pins = filter_.EnumPins()

    resolutions: List[Resolution] = []
    seen: set = set()

    while True:
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
            except Exception:
                pass

    resolutions.sort()
    return resolutions
