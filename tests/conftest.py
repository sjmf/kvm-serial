"""
Pytest configuration for all tests.

Mocks serial modules to prevent importing real pyserial during tests.
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
