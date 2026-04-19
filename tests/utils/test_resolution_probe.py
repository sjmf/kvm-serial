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
    _enumerate_directshow,
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


class TestEnumerateAVFoundation:
    def test_import_error_returns_empty(self):
        with patch.dict("sys.modules", {"AVFoundation": None, "CoreMedia": None}):
            result = _enumerate_avfoundation(0)
        assert result == []

    def test_out_of_range_index_returns_empty(self):
        mock_av = MagicMock()
        mock_cm = MagicMock()
        mock_av.AVCaptureDevice.devicesWithMediaType_.return_value = []
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
        mock_av.AVCaptureDevice.devicesWithMediaType_.return_value = [device]

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
