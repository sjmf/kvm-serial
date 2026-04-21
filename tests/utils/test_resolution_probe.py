"""Tests for kvm_serial.utils.resolution_probe"""

import sys
import struct
import pytest
from unittest.mock import MagicMock, patch, mock_open

from kvm_serial.utils.resolution_probe import (
    enumerate_resolutions,
    RESOLUTION_PRESETS,
    _enumerate_v4l2,
    _enumerate_avfoundation,
    _avfoundation_device_list,
    _enumerate_directshow,
    _directshow_resolutions,
)


class TestResolutionPresets:
    def test_presets_non_empty(self):
        assert len(RESOLUTION_PRESETS) > 0

    def test_presets_are_tuples(self):
        for r in RESOLUTION_PRESETS:
            assert isinstance(r, tuple) and len(r) == 2

    def test_presets_sorted_lexicographically(self):
        assert list(RESOLUTION_PRESETS) == sorted(RESOLUTION_PRESETS)

    def test_presets_contain_common_resolutions(self):
        assert (1920, 1080) in RESOLUTION_PRESETS
        assert (1280, 720) in RESOLUTION_PRESETS
        assert (640, 480) in RESOLUTION_PRESETS


class TestEnumerateResolutionsDispatch:
    def test_returns_list(self):
        with patch("kvm_serial.utils.resolution_probe.sys") as mock_sys:
            mock_sys.platform = "unsupported_platform"
            result = enumerate_resolutions(0)
        assert isinstance(result, list)

    def test_dispatches_to_v4l2_on_linux(self):
        with (
            patch("kvm_serial.utils.resolution_probe.sys") as mock_sys,
            patch(
                "kvm_serial.utils.resolution_probe._enumerate_v4l2", return_value=[(1920, 1080)]
            ) as mock_fn,
        ):
            mock_sys.platform = "linux"
            result = enumerate_resolutions(0)
        mock_fn.assert_called_once_with(0)
        assert result == [(1920, 1080)]

    def test_dispatches_to_avfoundation_on_darwin(self):
        with (
            patch("kvm_serial.utils.resolution_probe.sys") as mock_sys,
            patch(
                "kvm_serial.utils.resolution_probe._enumerate_avfoundation",
                return_value=[(1280, 720)],
            ) as mock_fn,
        ):
            mock_sys.platform = "darwin"
            result = enumerate_resolutions(0)
        mock_fn.assert_called_once_with(0)
        assert result == [(1280, 720)]

    def test_dispatches_to_directshow_on_win32(self):
        with (
            patch("kvm_serial.utils.resolution_probe.sys") as mock_sys,
            patch(
                "kvm_serial.utils.resolution_probe._enumerate_directshow", return_value=[(640, 480)]
            ) as mock_fn,
        ):
            mock_sys.platform = "win32"
            result = enumerate_resolutions(0)
        mock_fn.assert_called_once_with(0)
        assert result == [(640, 480)]

    def test_exception_returns_empty(self):
        with patch("kvm_serial.utils.resolution_probe.sys") as mock_sys:
            mock_sys.platform = "linux"
            with patch(
                "kvm_serial.utils.resolution_probe._enumerate_v4l2",
                side_effect=RuntimeError("boom"),
            ):
                result = enumerate_resolutions(0)
        assert result == []


class TestEnumerateV4L2:
    def _make_fmtdesc(self, index, pixelformat):
        return struct.pack("=II32sII4I", index, 1, b"", pixelformat, 0, 0, 0, 0, 0)

    def _make_frmsizeenum_discrete(self, index, pixelformat, width, height):
        V4L2_FRMSIZE_TYPE_DISCRETE = 1
        return struct.pack(
            "=III8I",
            index,
            pixelformat,
            V4L2_FRMSIZE_TYPE_DISCRETE,
            width,
            height,
            0,
            0,
            0,
            0,
            0,
            0,
        )

    def _make_frmsizeenum_stepwise(self, index, pixelformat):
        V4L2_FRMSIZE_TYPE_STEPWISE = 2
        return struct.pack(
            "=III8I",
            index,
            pixelformat,
            V4L2_FRMSIZE_TYPE_STEPWISE,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )

    @pytest.mark.skipif(sys.platform != "linux", reason="V4L2 only available on Linux")
    def test_returns_empty_when_device_not_found(self):
        with patch("builtins.open", side_effect=OSError("no device")):
            result = _enumerate_v4l2(99)
        assert result == []

    @pytest.mark.skipif(sys.platform != "linux", reason="V4L2 only available on Linux")
    def test_discrete_resolutions_returned(self):
        MJPG = 0x47504A4D
        fmt0 = self._make_fmtdesc(0, MJPG)
        size0 = self._make_frmsizeenum_discrete(0, MJPG, 1920, 1080)
        size1 = self._make_frmsizeenum_discrete(1, MJPG, 1280, 720)
        call_counts = {"fmt": 0, "size": 0}

        def fake_ioctl(fd, request, buf):
            VIDIOC_ENUM_FMT = 0xC0405602
            VIDIOC_ENUM_FRAMESIZES = 0xC02C564F
            if request == VIDIOC_ENUM_FMT:
                if call_counts["fmt"] == 0:
                    call_counts["fmt"] += 1
                    return fmt0
                raise OSError("no more formats")
            if request == VIDIOC_ENUM_FRAMESIZES:
                idx = call_counts["size"]
                call_counts["size"] += 1
                if idx == 0:
                    return size0
                if idx == 1:
                    return size1
                raise OSError("no more sizes")
            raise OSError("unexpected ioctl")

        with patch("builtins.open", mock_open()), patch("fcntl.ioctl", side_effect=fake_ioctl):
            result = _enumerate_v4l2(0)

        assert (1280, 720) in result
        assert (1920, 1080) in result

    @pytest.mark.skipif(sys.platform != "linux", reason="V4L2 only available on Linux")
    def test_stepwise_formats_skipped(self):
        MJPG = 0x47504A4D
        fmt0 = self._make_fmtdesc(0, MJPG)
        size_stepwise = self._make_frmsizeenum_stepwise(0, MJPG)
        call_counts = {"fmt": 0}

        def fake_ioctl(fd, request, buf):
            VIDIOC_ENUM_FMT = 0xC0405602
            VIDIOC_ENUM_FRAMESIZES = 0xC02C564F
            if request == VIDIOC_ENUM_FMT:
                if call_counts["fmt"] == 0:
                    call_counts["fmt"] += 1
                    return fmt0
                raise OSError("done")
            if request == VIDIOC_ENUM_FRAMESIZES:
                return size_stepwise
            raise OSError("unexpected")

        with patch("builtins.open", mock_open()), patch("fcntl.ioctl", side_effect=fake_ioctl):
            result = _enumerate_v4l2(0)

        assert result == []

    @pytest.mark.skipif(sys.platform != "linux", reason="V4L2 only available on Linux")
    def test_duplicates_deduplicated(self):
        MJPG = 0x47504A4D
        YUYV = 0x56595559
        fmt0 = self._make_fmtdesc(0, MJPG)
        fmt1 = self._make_fmtdesc(1, YUYV)
        size_mjpg = self._make_frmsizeenum_discrete(0, MJPG, 1920, 1080)
        size_yuyv = self._make_frmsizeenum_discrete(0, YUYV, 1920, 1080)
        fmt_call = [0]
        size_call = {"MJPG": 0, "YUYV": 0}

        def fake_ioctl(fd, request, buf):
            VIDIOC_ENUM_FMT = 0xC0405602
            VIDIOC_ENUM_FRAMESIZES = 0xC02C564F
            if request == VIDIOC_ENUM_FMT:
                n = fmt_call[0]
                fmt_call[0] += 1
                if n == 0:
                    return fmt0
                if n == 1:
                    return fmt1
                raise OSError("done")
            if request == VIDIOC_ENUM_FRAMESIZES:
                pf = struct.unpack("=III8I", buf)[1]
                if pf == MJPG:
                    n = size_call["MJPG"]
                    size_call["MJPG"] += 1
                    if n == 0:
                        return size_mjpg
                    raise OSError("done")
                if pf == YUYV:
                    n = size_call["YUYV"]
                    size_call["YUYV"] += 1
                    if n == 0:
                        return size_yuyv
                    raise OSError("done")
                raise OSError("unexpected pf")
            raise OSError("unexpected")

        with patch("builtins.open", mock_open()), patch("fcntl.ioctl", side_effect=fake_ioctl):
            result = _enumerate_v4l2(0)

        assert result.count((1920, 1080)) == 1


def _make_av_mock(devices):
    """Return (mock_av, mock_cm) with the discovery session wired to return `devices`."""
    mock_av = MagicMock()
    mock_cm = MagicMock()
    # Wire discovery session so list(session.devices()) == devices
    mock_av.AVCaptureDeviceDiscoverySession.discoverySessionWithDeviceTypes_mediaType_position_.return_value.devices.return_value = (
        devices
    )
    return mock_av, mock_cm


class TestAVFoundationDeviceList:
    """Tests for the _avfoundation_device_list helper."""

    def test_uses_discovery_session(self):
        mock_av = MagicMock()
        device = MagicMock()
        mock_av.AVCaptureDeviceDiscoverySession.discoverySessionWithDeviceTypes_mediaType_position_.return_value.devices.return_value = [
            device
        ]
        result = _avfoundation_device_list(mock_av)
        assert result == [device]
        mock_av.AVCaptureDeviceDiscoverySession.discoverySessionWithDeviceTypes_mediaType_position_.assert_called_once()

    def test_falls_back_to_devicesWithMediaType_on_session_failure(self):
        mock_av = MagicMock()
        device = MagicMock()
        mock_av.AVCaptureDeviceDiscoverySession.discoverySessionWithDeviceTypes_mediaType_position_.side_effect = RuntimeError(
            "session unavailable"
        )
        mock_av.AVCaptureDevice.devicesWithMediaType_.return_value = [device]
        result = _avfoundation_device_list(mock_av)
        assert result == [device]

    def test_uses_external_type_on_macos14(self):
        """On macOS 14+ AVCaptureDeviceTypeExternal should be used."""
        mock_av = MagicMock()
        mock_av.AVCaptureDeviceDiscoverySession.discoverySessionWithDeviceTypes_mediaType_position_.return_value.devices.return_value = (
            []
        )
        _avfoundation_device_list(mock_av)
        call_args = (
            mock_av.AVCaptureDeviceDiscoverySession.discoverySessionWithDeviceTypes_mediaType_position_.call_args
        )
        device_types = call_args[0][0]
        assert mock_av.AVCaptureDeviceTypeExternal in device_types

    def test_falls_back_to_external_unknown_when_external_missing(self):
        """On older macOS, AVCaptureDeviceTypeExternal is absent; use ExternalUnknown."""
        mock_av = MagicMock(spec=[])  # spec=[] → no attributes by default
        # Only define what we need
        mock_av.AVCaptureDeviceTypeBuiltInWideAngleCamera = "builtin"
        mock_av.AVCaptureDeviceTypeExternalUnknown = "external_unknown"
        mock_av.AVMediaTypeVideo = "video"
        mock_av.AVCaptureDevicePositionUnspecified = 0
        session = MagicMock()
        session.devices.return_value = []
        mock_av.AVCaptureDeviceDiscoverySession = MagicMock()
        mock_av.AVCaptureDeviceDiscoverySession.discoverySessionWithDeviceTypes_mediaType_position_.return_value = (
            session
        )
        result = _avfoundation_device_list(mock_av)
        assert result == []
        call_args = (
            mock_av.AVCaptureDeviceDiscoverySession.discoverySessionWithDeviceTypes_mediaType_position_.call_args
        )
        device_types = call_args[0][0]
        assert "external_unknown" in device_types


class TestEnumerateAVFoundation:
    def test_import_error_returns_empty(self):
        with patch.dict("sys.modules", {"AVFoundation": None, "CoreMedia": None}):
            result = _enumerate_avfoundation(0)
        assert result == []

    def test_out_of_range_index_returns_empty(self):
        mock_av, mock_cm = _make_av_mock([])
        with patch.dict("sys.modules", {"AVFoundation": mock_av, "CoreMedia": mock_cm}):
            result = _enumerate_avfoundation(0)
        assert result == []

    def test_returns_deduplicated_sorted_resolutions(self):
        mock_av = MagicMock()
        mock_cm = MagicMock()

        fmt1, fmt2, fmt3 = MagicMock(), MagicMock(), MagicMock()

        def dims_for(desc):
            d = MagicMock()
            mapping = {
                fmt1.formatDescription(): (1920, 1080),
                fmt2.formatDescription(): (1280, 720),
                fmt3.formatDescription(): (1920, 1080),
            }
            w, h = mapping.get(desc, (640, 480))
            d.width, d.height = w, h
            return d

        mock_cm.CMVideoFormatDescriptionGetDimensions.side_effect = dims_for

        device = MagicMock()
        device.formats.return_value = [fmt1, fmt2, fmt3]
        mock_av.AVCaptureDeviceDiscoverySession.discoverySessionWithDeviceTypes_mediaType_position_.return_value.devices.return_value = [
            device
        ]

        with patch.dict("sys.modules", {"AVFoundation": mock_av, "CoreMedia": mock_cm}):
            result = _enumerate_avfoundation(0)

        assert result.count((1920, 1080)) == 1
        assert (1280, 720) in result
        assert list(result) == sorted(result)


class TestEnumerateDirectShow:
    def test_import_error_returns_empty(self):
        with patch.dict("sys.modules", {"comtypes": None, "comtypes.client": None}):
            result = _enumerate_directshow(0)
        assert result == []

    def test_delegates_to_directshow_resolutions_when_import_succeeds(self):
        mock_comtypes = MagicMock()
        mock_client = MagicMock()
        with (
            patch.dict("sys.modules", {"comtypes": mock_comtypes, "comtypes.client": mock_client}),
            patch(
                "kvm_serial.utils.resolution_probe._directshow_resolutions",
                return_value=[(1920, 1080)],
            ) as mock_fn,
        ):
            result = _enumerate_directshow(0)
        mock_fn.assert_called_once_with(0)
        assert result == [(1920, 1080)]

    def test_exception_in_directshow_resolutions_returns_empty(self):
        mock_comtypes = MagicMock()
        mock_client = MagicMock()
        with (
            patch.dict("sys.modules", {"comtypes": mock_comtypes, "comtypes.client": mock_client}),
            patch(
                "kvm_serial.utils.resolution_probe._directshow_resolutions",
                side_effect=RuntimeError("COM error"),
            ),
        ):
            result = _enumerate_directshow(0)
        assert result == []


class TestDirectShowResolutions:
    """Tests _directshow_resolutions with a fully mocked COM stack.

    Key wiring: `import comtypes.client` inside the function causes Python to set
    sys.modules['comtypes'].client = sys.modules['comtypes.client'], so we explicitly
    pre-set mock_comtypes.client = mock_client to be safe. `from comtypes.gen import
    DirectShowLib as ds` resolves to mock_gen.DirectShowLib.
    """

    def _build_stack(self, resolutions=None):
        """Return a fully wired COM mock stack as a dict of named objects."""
        if resolutions is None:
            resolutions = [(1920, 1080)]

        mock_ctypes = MagicMock(name="ctypes")
        mock_comtypes = MagicMock(name="comtypes")
        mock_client = MagicMock(name="comtypes.client")
        mock_gen = MagicMock(name="comtypes.gen")
        mock_comtypes.client = mock_client
        mock_comtypes.COMError = OSError  # must be a real exception class

        ds = mock_gen.DirectShowLib
        ds.FORMAT_VideoInfo = "FORMAT_VideoInfo_sentinel"  # real value for equality

        # Media types for the single output pin
        mts, cast_returns = [], []
        for w, h in resolutions:
            mt = MagicMock()
            mt.formattype = ds.FORMAT_VideoInfo
            vi = MagicMock()
            vi.bmiHeader.biWidth = w
            vi.bmiHeader.biHeight = h
            cr = MagicMock()
            cr.contents = vi
            mts.append(mt)
            cast_returns.append(cr)
        mock_ctypes.cast.side_effect = cast_returns

        enum_mt = MagicMock()
        enum_mt.Next.side_effect = [(mt, 1) for mt in mts] + [(None, 0)]

        pin = MagicMock()
        pin_info = MagicMock()
        pin_info.dir = 0  # PINDIR_OUTPUT
        pin.QueryPinInfo.return_value = pin_info
        pin.EnumMediaTypes.return_value = enum_mt

        enum_pins = MagicMock()
        enum_pins.Next.side_effect = [(pin, 1), (None, 0)]

        filter_ = MagicMock()
        filter_.EnumPins.return_value = enum_pins

        moniker = MagicMock()
        moniker.BindToObject.return_value = filter_

        enum_moniker = MagicMock()
        enum_moniker.Next.side_effect = [(moniker, 1), (None, 0)]

        dev_enum = MagicMock()
        dev_enum.CreateClassEnumerator.return_value = enum_moniker
        mock_client.CreateObject.return_value = dev_enum

        return {
            "modules": {
                "ctypes": mock_ctypes,
                "comtypes": mock_comtypes,
                "comtypes.client": mock_client,
                "comtypes.gen": mock_gen,
            },
            "ctypes": mock_ctypes,
            "comtypes": mock_comtypes,
            "client": mock_client,
            "ds": ds,
            "dev_enum": dev_enum,
            "enum_moniker": enum_moniker,
            "moniker": moniker,
            "filter_": filter_,
            "enum_pins": enum_pins,
            "pin": pin,
            "pin_info": pin_info,
            "enum_mt": enum_mt,
        }

    def test_enum_moniker_none_returns_empty(self):
        s = self._build_stack()
        s["dev_enum"].CreateClassEnumerator.return_value = None
        with patch.dict("sys.modules", s["modules"]):
            assert _directshow_resolutions(0) == []

    def test_device_index_out_of_range_returns_empty(self):
        s = self._build_stack()  # one moniker at index 0
        with patch.dict("sys.modules", s["modules"]):
            assert _directshow_resolutions(1) == []

    def test_com_error_in_moniker_loop_returns_empty(self):
        s = self._build_stack()
        s["enum_moniker"].Next.side_effect = OSError("COMError")
        with patch.dict("sys.modules", s["modules"]):
            assert _directshow_resolutions(0) == []

    def test_output_pin_with_wrong_dir_skipped(self):
        s = self._build_stack()
        s["pin_info"].dir = 1  # not PINDIR_OUTPUT → skipped
        with patch.dict("sys.modules", s["modules"]):
            assert _directshow_resolutions(0) == []

    def test_com_error_on_enum_media_types_skipped(self):
        s = self._build_stack()
        s["pin"].EnumMediaTypes.side_effect = OSError("COMError")
        with patch.dict("sys.modules", s["modules"]):
            assert _directshow_resolutions(0) == []

    def test_non_video_info_format_skipped(self):
        s = self._build_stack()
        mt = MagicMock()
        mt.formattype = "not_video_info"
        s["enum_mt"].Next.side_effect = [(mt, 1), (None, 0)]
        with patch.dict("sys.modules", s["modules"]):
            assert _directshow_resolutions(0) == []

    def test_exception_in_cast_is_swallowed(self):
        s = self._build_stack()
        s["ctypes"].cast.side_effect = RuntimeError("bad cast")
        with patch.dict("sys.modules", s["modules"]):
            assert _directshow_resolutions(0) == []

    def test_zero_dimension_filtered_out(self):
        s = self._build_stack(resolutions=[(0, 480), (1920, 1080)])
        with patch.dict("sys.modules", s["modules"]):
            result = _directshow_resolutions(0)
        assert (0, 480) not in result
        assert (1920, 1080) in result

    def test_com_error_in_pin_loop_returns_empty(self):
        s = self._build_stack()
        s["enum_pins"].Next.side_effect = OSError("COMError in pin loop")
        with patch.dict("sys.modules", s["modules"]):
            assert _directshow_resolutions(0) == []

    def test_com_error_in_media_type_loop_returns_partial(self):
        s = self._build_stack(resolutions=[(1920, 1080)])
        s["enum_mt"].Next.side_effect = OSError("COMError in mt loop")
        with patch.dict("sys.modules", s["modules"]):
            assert _directshow_resolutions(0) == []

    def test_returns_deduplicated_sorted_resolutions(self):
        s = self._build_stack(resolutions=[(1920, 1080), (1280, 720), (1920, 1080)])
        with patch.dict("sys.modules", s["modules"]):
            result = _directshow_resolutions(0)
        assert result.count((1920, 1080)) == 1
        assert (1280, 720) in result
        assert list(result) == sorted(result)
