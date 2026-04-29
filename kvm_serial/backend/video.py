#!/usr/bin/env python
"""Qt-based video capture for KVM Serial.

Replaces the previous OpenCV implementation. Enumeration and capture both go
through QtMultimedia (QCamera / QCameraInfo), which wraps AVFoundation on
macOS, DirectShow on Windows, and V4L2 on Linux. Because the same Qt object
both enumerates and opens a device, the platform-specific introspection layer
that previously lived in utils/resolution_probe.py is no longer needed.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

try:
    from PyQt5.QtCore import QEventLoop, QTimer
    from PyQt5.QtMultimedia import QCamera, QCameraInfo
except ImportError as e:  # pragma: no cover - environment-specific
    raise ImportError(
        "PyQt5 QtMultimedia is required for video capture. "
        "On Debian/Ubuntu, install with: "
        "apt install python3-pyqt5.qtmultimedia libqt5multimedia5-plugins"
    ) from e


# Maximum time to wait for QCamera.load() to populate supported settings.
# load() is documented as asynchronous; in practice AVFoundation/DirectShow
# return synchronously, but V4L2 may take a moment on first access.
PROBE_TIMEOUT_MS = 2000


class CaptureDeviceException(Exception):
    pass


@dataclass
class CameraProperties:
    """Capabilities of a camera device.

    Derived from QCameraInfo + QCamera.supportedViewfinderSettings(). The live
    QCameraInfo is retained so the GUI can pass it to QCamera() when opening.

    `index` is the position in the enumerated list; it has no relationship to
    any platform-native device index (that abstraction is a thing of the past
    now that Qt is both enumerator and opener).
    """

    index: int
    name: str
    unique_id: str
    width: int
    height: int
    fps: int
    resolutions: List[Tuple[int, int]]
    default_resolution: Tuple[int, int]
    info: Optional[QCameraInfo] = None

    def __getitem__(self, key):
        return getattr(self, key)

    def __str__(self) -> str:
        return self.name  # f"{self.name} ({self.width}x{self.height}@{self.fps}fps)"


def _wait_for_loaded(cam: QCamera, timeout_ms: int = PROBE_TIMEOUT_MS) -> bool:
    """Spin a local event loop until the camera reaches LoadedStatus or times out."""
    if cam.status() == QCamera.LoadedStatus:
        return True

    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)

    def _on_status(status):
        if status == QCamera.LoadedStatus:
            loop.quit()

    cam.statusChanged.connect(_on_status)
    timer.start(timeout_ms)
    loop.exec_()
    cam.statusChanged.disconnect(_on_status)
    return cam.status() == QCamera.LoadedStatus


def _probe_camera(info: QCameraInfo, index: int) -> CameraProperties:
    """Load a camera in viewfinder-only mode to read its capabilities."""
    cam = QCamera(info)
    cam.load()
    if not _wait_for_loaded(cam):
        logger.warning(
            "Camera %d (%s) did not reach LoadedStatus within %dms; "
            "capabilities may be incomplete",
            index,
            info.description(),
            PROBE_TIMEOUT_MS,
        )

    settings_list = cam.supportedViewfinderSettings()
    seen: set = set()
    resolutions: List[Tuple[int, int]] = []
    max_fps = 0
    for s in settings_list:
        size = s.resolution()
        wh = (size.width(), size.height())
        if wh[0] > 0 and wh[1] > 0 and wh not in seen:
            seen.add(wh)
            resolutions.append(wh)
        fps = int(s.maximumFrameRate())
        if fps > max_fps:
            max_fps = fps

    # Sort by pixel count so the menu shows largest-first below "Use Default".
    resolutions.sort(key=lambda wh: (wh[0] * wh[1], wh[0]), reverse=True)

    current = cam.viewfinderSettings()
    current_size = current.resolution()
    if current_size.isValid() and current_size.width() > 0:
        default_res = (current_size.width(), current_size.height())
    elif resolutions:
        default_res = resolutions[0]
    else:
        default_res = (0, 0)

    cam.unload()

    # Only include default_res as a fallback when it is a valid (non-zero) size.
    # If both supportedViewfinderSettings() and viewfinderSettings() return nothing
    # useful, leave resolutions empty rather than propagating a "0x0" entry into
    # the GUI where it would appear as a selectable option and later be passed to
    # QCameraViewfinderSettings.setResolution(0, 0).
    if not resolutions and default_res[0] > 0:
        resolutions = [default_res]

    return CameraProperties(
        index=index,
        name=info.description() or info.deviceName() or f"Camera {index}",
        unique_id=info.deviceName() or str(index),
        width=default_res[0],
        height=default_res[1],
        fps=max_fps,
        resolutions=resolutions,
        default_resolution=default_res,
        info=info,
    )


def enumerate_cameras() -> List[CameraProperties]:
    """Return a CameraProperties list for every camera QtMultimedia can see.

    Requires a running QCoreApplication (or QApplication). Safe to call from
    the main GUI thread; QCamera signals will be delivered via the local event
    loop spun by _wait_for_loaded.
    """
    infos = QCameraInfo.availableCameras()
    cameras: List[CameraProperties] = []
    for i, info in enumerate(infos):
        try:
            cameras.append(_probe_camera(info, i))
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Failed to probe camera %d (%s): %s", i, info.description(), e)
    logger.info("Found %d cameras via QtMultimedia.", len(cameras))
    logger.debug(cameras)
    return cameras


class CaptureDevice:
    """Backwards-compatible namespace exposing the enumeration entrypoint.

    The previous class wrapped cv2.VideoCapture and ran a frame-capture loop in
    a worker thread. Under Qt, the camera is a QObject owned by the GUI thread
    that streams directly into a QGraphicsVideoItem, so there is no per-instance
    state to hold here.
    """

    @staticmethod
    def getCameras() -> List[CameraProperties]:
        return enumerate_cameras()
