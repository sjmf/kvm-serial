"""
Pytest configuration for all tests.

Mocks serial modules to prevent importing real pyserial during tests.
Mocks PyQt5 only in CI environments where it lacks system dependencies.

This runs before any test collection begins, ensuring mocks are in place
for module-level imports across all test directories.
"""

import sys
from unittest.mock import MagicMock


# Mock serial modules BEFORE any test imports happen
def pytest_configure(config):
    """Called before test collection begins"""
    from tests._utilities import MockSerial

    # Create mock hierarchy - must be connected so imports work
    mock_list_ports = MagicMock()
    mock_list_ports.comports = MagicMock(return_value=[])

    mock_tools = MagicMock()
    mock_tools.list_ports = mock_list_ports

    mock_serial_mod = MagicMock()
    mock_serial_mod.Serial = MockSerial
    mock_serial_mod.SerialException = Exception
    mock_serial_mod.tools = mock_tools

    # Inject into sys.modules - hierarchy must match
    sys.modules["serial"] = mock_serial_mod
    sys.modules["serial.tools"] = mock_tools
    sys.modules["serial.tools.list_ports"] = mock_list_ports

    # Mock PyQt5 only if it can't be imported (CI environments without multimedia libs)
    # Try to import real PyQt5 first
    try:
        import PyQt5.QtMultimedia
        import PyQt5.QtCore
    except ImportError:
        # CI environment lacks libpulse-mainloop-glib or other Qt multimedia dependencies
        # Mock only the modules needed for video.py to import gracefully
        mock_qcore = MagicMock()
        mock_qcore.QEventLoop = MagicMock()
        mock_qcore.QTimer = MagicMock()
        sys.modules["PyQt5.QtCore"] = mock_qcore

        mock_qmultimedia = MagicMock()
        mock_qmultimedia.QCamera = MagicMock()
        mock_qmultimedia.QCameraInfo = MagicMock()
        sys.modules["PyQt5.QtMultimedia"] = mock_qmultimedia
