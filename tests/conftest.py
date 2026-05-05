"""
Pytest configuration for all tests.

Mocks serial modules to prevent importing real pyserial during tests.
This runs before any test collection begins, ensuring mocks are in place
for module-level imports across all test directories.
"""

import sys
from unittest.mock import MagicMock

import pytest


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

    # Mock usb / usb.core for pyusbop. USBError must be a real Exception
    # class so the `except USBError as e:` clause inside pyusbop validates.
    class _MockUSBError(Exception):
        pass

    mock_usb_core = MagicMock()
    mock_usb_core.USBError = _MockUSBError
    mock_usb = MagicMock()
    mock_usb.core = mock_usb_core
    sys.modules["usb"] = mock_usb
    sys.modules["usb.core"] = mock_usb_core
    sys.modules["usb.util"] = MagicMock()

    # Pre-import backend submodules that tests later pull in inside
    # `patch.dict("sys.modules", ...)` blocks. If a submodule is loaded
    # *during* the patch, patch.dict evicts it on exit and the parent
    # package's stale `.<submodule>` attribute survives, causing later
    # `from kvm_serial.backend import x as mod` (attribute path) and
    # `from kvm_serial.backend.x import Y` (sys.modules path) to resolve
    # to *different* module objects. Pre-loading anchors the modules in
    # sys.modules before any patch sees them.
    import kvm_serial.backend.keyboard  # noqa: F401
    import kvm_serial.backend.implementations.pyusbop  # noqa: F401


@pytest.fixture
def _datacomm_manager():
    """
    Provide a fresh DataCommManager singleton wrapping a MagicMock comm to
    every test. Ops constructed during the test fetch the mock via
    ``DataCommManager.get().comm`` and any writes are observable on it.
    The singleton is reset on teardown so tests don't pollute each other.

    Tests that need to assert on specific comm behaviour can grab the mock
    with ``DataCommManager.get().comm``; tests that want to install their
    own manager can call ``DataCommManager.reset()`` first and re-init.
    """
    try:
        from kvm_serial.backend.manager import DataCommManager
    except ImportError:
        yield
        return

    DataCommManager.reset()
    mgr = DataCommManager(MagicMock(), comm_cls=lambda port: MagicMock())
    try:
        yield mgr
    finally:
        DataCommManager.reset()
