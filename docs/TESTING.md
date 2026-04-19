# Testing Guide for kvm-serial

## Overview

This guide explains how `kvm-serial` achieves reliable automated testing for a PyQt5 GUI application that controls physical hardware. The challenge: how do you test an application that creates windows and talks to serial devices when you're running in a headless CI environment with no hardware attached?

The answer involves extensive mocking: done carefully to avoid turning tests into meaningless stub checks. This document explains the testing approach and why these patterns matter for maintaining a robust test suite.

## The Testing Challenge

### What Makes This Hard?

Testing kvm-serial isn't like testing a typical Python library. Several unique constraints exist:

**GUI Framework Limitations**: PyQt5 expects a graphical environment. When you import the main application module, Qt immediately tries to initialise windows, menus, and event loops. In a headless CI environment (like GitHub Actions), this fails with errors about missing display servers. While a virtual X server could be installed to work around this, mocking the GUI framework is cleaner and faster.

**Hardware Dependencies**: The application's core purpose is controlling serial devices and capturing video from cameras. Real hardware isn't available during testing, and even if it were, tests shouldn't depend on specific physical devices being connected.

**Import-Time Side Effects**: Python executes code during module import. If an application creates a `QApplication` instance at the module level, it spawns a GUI before any test mocking can intercept it.

**State Management**: Qt applications maintain global state. Without careful cleanup between tests, one test's mocks can pollute another test's environment, causing mysterious failures that only appear when running the full suite.

### The Core Strategy

The solution: **Mock everything external before it can be imported, test the logic without side effects, then aggressively clean up.**

This means mocking the Qt framework itself, mocking hardware APIs, and carefully controlling when and how modules get loaded into Python's import system. The result is tests that verify logic (event handling, state management, error recovery) without ever touching a GUI or serial port.

## Architecture

### Base Test Class Pattern

`KVMTestBase` provides centralised mocking infrastructure that all test classes inherit:

```python
class TestMyFeature(KVMTestBase):
    def test_something(self):
        app = self.create_kvm_app()  # Already mocked
        # Test logic here
```

This inheritance pattern centralises all the mocking complexity in one place. Instead of every test file duplicating the same Qt mocking setup, they inherit from `KVMTestBase` and get it automatically. The base class handles starting patches before tests run and stopping them afterwards, preventing mock leakage between tests. It also provides utility methods for common operations like creating mock cameras or serial ports, making tests more readable and maintainable.

### Mock Lifecycle

1. **setUp()** - Create and start all patches before module import
2. **Test execution** - Use mocked components
3. **tearDown()** - Stop patches and clear modules from `sys.modules`

**Critical:** Module cleanup prevents test cross-contamination by forcing fresh imports.

## Adding a New Test

The minimal skeleton for a KVM GUI test:

```python
from tests.kvm.test_kvm_base import KVMTestBase

class TestMyFeature(KVMTestBase):
    def test_something(self):
        app = self.create_kvm_app()   # KVMQtGui with all hardware mocked
        # arrange
        app.serial_port_var = "/dev/ttyUSB0"
        # act
        app._KVMQtGui__init_serial()  # double-underscore = name-mangled private method
        # assert
        self.assertIsNotNone(app.serial_port)
```

`KVMTestBase.setUp()` starts all mocks and imports `kvm_serial.kvm`; `tearDown()` stops them and flushes the module from `sys.modules`. You don't need to define `setUp`/`tearDown` at all — the base class handles both. If you do override `setUp`, call `super().setUp()` first.

To access private methods use Python's name-mangling convention: `__method` defined in `KVMQtGui` is called as `app._KVMQtGui__method()`.

For tests that need serial port or camera helpers, mix in the relevant class:

```python
class TestMyFeature(KVMTestBase, KVMTestMixins.SerialTestMixin):
    def test_port_list(self):
        ports = self.create_mock_serial_ports()   # from KVMTestBase
        self.setup_serial_test_data()              # from SerialTestMixin
```

## Mocking Strategies

### 1. PyQt5 GUI Component Mocking

**Why:** Prevent actual window creation and Qt application startup.

**Approach:**

```python
def _setup_qt_mocks(self):
    patches = []
    
    # Mock QApplication to prevent GUI startup
    patches.append(patch("PyQt5.QtWidgets.QApplication"))
    
    # Mock QMainWindow.__init__ to skip window creation
    def mock_qmainwindow_init(self):
        pass
    patches.append(patch("PyQt5.QtWidgets.QMainWindow.__init__", 
                        mock_qmainwindow_init))
    
    # Mock all widget classes
    for widget in ["QLabel", "QMenu", "QMessageBox", ...]:
        patches.append(patch(f"PyQt5.QtWidgets.{widget}"))
    
    return patches
```

**Key insight:** Mock both classes and methods. Class mocks prevent instantiation issues; method mocks handle calls on instances.

### 2. Hardware Abstraction Mocking

**Why:** Tests shouldn't require physical devices.

**Approach:**
```python
def _setup_hardware_mocks(self):
    from kvm_serial.backend import video as video_mod
    return [
        patch.object(video_mod, "CaptureDevice"),
        patch.object(video_mod, "CameraProperties"),
        patch("kvm_serial.kvm.CaptureDevice"),
        patch("kvm_serial.kvm.VideoCaptureWorker"),
        patch("kvm_serial.utils.communication.list_serial_ports"),
        patch("kvm_serial.kvm.list_serial_ports"),
        patch("kvm_serial.kvm.QtOp"),
        patch("kvm_serial.kvm.MouseOp"),
    ]
```

`patch.object` is used for the two `video_mod` patches rather than string-based `patch()` because `kvm_serial.backend` may already be in `sys.modules` without the `video` submodule attribute attached, which causes string-based patches to silently target a stale reference. Importing the module explicitly and using `patch.object` avoids this cross-group test pollution issue.

Three additional single-target mocks are set up via their own methods: `_setup_serial_mock()` patches `serial.Serial`, `_setup_cv2_mock()` patches `cv2.cvtColor`, and `_setup_settings_mock()` patches `kvm_serial.kvm.settings_util`.

**Pattern:** Mock at the point where the application module imports and uses hardware libraries, not at the library itself — this ensures the patch applies to the exact name binding in `kvm.py`.

### 3. Module-Level Import Mocking

**Critical timing issue:** Mocks must exist before importing the tested module.

```python
def setUp(self):
    # Start patches FIRST
    self.qt_patches = self._setup_qt_mocks()
    for patcher in self.qt_patches:
        patcher.start()
    
    # Import AFTER mocking
    from kvm_serial import kvm
    self.kvm_module = kvm
```

**Why this matters:** Python imports execute module code. If GUI initialisation happens during import, you've already created windows before mocking can prevent it.

### 4. Context Manager Pattern for Targeted Mocking

For test-specific mocking beyond the base infrastructure:

```python
def test_serial_port_selection(self):
    app = self.create_kvm_app()

    with self.patch_kvm_method(app, "_KVMQtGui__init_serial") as mock:
        app._on_serial_port_selected("/dev/ttyUSB0")
        mock.assert_called_once()
```

Python's context managers (`with` statements) provide automatic cleanup: when the block exits, the patch is automatically removed, even if an exception occurs. This makes it immediately clear which parts of the test are using mocked behaviour and which aren't, improving test readability.

### 5. Test Mixins for Domain-Specific Utilities

Mixins provide specialised testing utilities without cluttering the base class:

```python
class TestKVMDeviceManagement(
    KVMTestBase,
    KVMTestMixins.SerialTestMixin,
    KVMTestMixins.VideoTestMixin
):
    def test_populate_serial_ports(self):
        test_ports = self.create_mock_serial_ports()  # From mixin
        # Test logic
```

Each mixin adds domain-specific helper methods without forcing every test to inherit functionality it doesn't need. `SerialTestMixin` provides `setup_serial_test_data()` and `assert_serial_initialization()`. `VideoTestMixin` provides `setup_video_test_data()` and `assert_video_device_selection()`. `SettingsTestMixin` provides `create_test_settings()` and `assert_settings_loaded()`. Tests can mix and match these based on what they're testing.

A `create_kvm_test_class(*mixins)` factory function is also available to build combined test classes programmatically.

## Common Patterns

### Creating Mock Devices

`KVMTestBase` provides these factory helpers:

```python
# Serial port name lists
test_ports = self.create_mock_serial_ports()
# Returns: ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0"]

# Camera MagicMock objects with .index, .width, .height, __str__()
cameras = self.create_mock_cameras(count=2)

# A mock Serial instance with .close() pre-configured
serial = self.create_mock_serial_instance()

# Default application settings dict (for settings tests)
settings = self.get_default_settings()

# Default baud rate list as the app defines it
rates = self.get_default_baud_rates()

# Instantiate a KVMQtGui with all hardware safely mocked
app = self.create_kvm_app()
```

### Patching App Methods

`patch_kvm_method()` patches a method on a live `KVMQtGui` instance without string-based target lookup:

```python
app = self.create_kvm_app()
with self.patch_kvm_method(app, "_populate_serial_ports") as mock_populate:
    app._KVMQtGui__init_devices()
    mock_populate.assert_called_once()
```

### Error Handling Tests

`assert_error_handling(mock_messagebox_method, expected_calls=1)` wraps `assert_called_once()` / `assertEqual(call_count, N)` on a mocked `QMessageBox` method, giving a consistent failure message across tests.

**Pattern for exception testing:**

```python
with (
    patch("module.function", side_effect=Exception("Failed")),
    patch("PyQt5.QtWidgets.QMessageBox.critical") as mock_msg
):
    app.method_under_test()
    self.assert_error_handling(mock_msg)
```

This pattern ensures robust error handling: the test verifies that exceptions don't crash the application *and* that users receive appropriate error messages. Many tests only check one or the other, missing subtle bugs where errors are caught but users aren't informed.

### Testing Invalid Input

Use `subTest` for multiple invalid cases:

```python
invalid_ports = ["None found", "Error", None, ""]
for invalid_port in invalid_ports:
    with self.subTest(port=invalid_port):
        app.serial_port_var = invalid_port
        app._KVMQtGui__init_serial()
        self.assertIsNone(app.serial_port)
```

Without `subTest`, the first failure would stop the test, leaving other cases untested. Using `subTest` means all invalid inputs get tested even if some fail, and test output clearly identifies which specific input caused problems, making debugging much faster.

## Best Practices

### 1. Mock at Boundaries, Not Implementation

❌ **Don't mock:**

```python
patch("kvm_serial.kvm.KVMQtGui._internal_helper")
```

✅ **Do mock:**

```python
patch("serial.Serial")   # external library — pre-mocked by conftest, patched before kvm.py imports it
patch("cv2.cvtColor")    # external library attribute used by the application
```

Mock external dependencies, not internal code (except when deliberately isolating units). Note that for names imported into a module via `from x import y`, you must patch them at the application's import point rather than the library — see [Hardware Abstraction Mocking](#2-hardware-abstraction-mocking) for detail.

### 2. Prefer Observable Outcomes Over Call Assertions

Where possible, verify state rather than implementation:

❌ **Fragile** — breaks if the implementation is refactored even when behaviour is correct:

```python
mock_method.assert_called()
```

✅ **Robust** — tests what the user or caller would actually observe:

```python
self.assertEqual(app.serial_port_var, expected_port)
self.assertTrue(app.keyboard_op is not None)
```

Call-count assertions (`assert_called_once`, `assert_not_called`) are still appropriate when the *number of calls* is itself the observable behaviour — for example, verifying that an expensive device enumeration is not repeated unnecessarily, or that an error dialog is shown exactly once. Use them deliberately, not as a substitute for checking outcomes.

### 3. Use Type-Appropriate Assertions

```python
# For lists
self.assertEqual(len(app.baud_rates), 8)
self.assertIn(9600, app.baud_rates)

# For booleans
self.assertFalse(app.keyboard_var)
self.assertTrue(hasattr(app, "video_worker"))

# For None
self.assertIsNone(app.serial_port)
```

### 4. Test Initialisation State

After creating the app, verify default values:

```python
def test_default_values(self):
    app = self.create_kvm_app()
    
    self.assertEqual(app.target_fps, 30)
    self.assertFalse(app.keyboard_var)
    self.assertEqual(app.video_var, -1)
```

Catches regression in default configuration.

### 5. Module Cleanup

**Always** remove tested modules in tearDown:

```python
def tearDown(self):
    patch.stopall()

    for module in [
        "kvm_serial.kvm",
        "kvm_serial.backend.video",
        "kvm_serial.utils.communication",
        "kvm_serial.utils.settings",
    ]:
        if module in sys.modules:
            del sys.modules[module]
```

Prevents test interdependencies and ensures fresh imports.

### 6. Early Module Mocking with pytest_configure

**The Problem**: Some production modules use module-level imports like `from serial.tools import list_ports`. This import executes when Python loads the module, *before* any test setup can mock it. The real `serial` module gets loaded and cached in `sys.modules`, making any subsequent mocking attempts ineffective since Python won't re-import an already cached module.

**Why Not Modify Production Code?**: We could add `try/except` blocks or lazy imports to production code, but that would be polluting the codebase to accommodate tests: exactly backwards. Tests should adapt to production code, not the other way around.

**The Solution**: Use pytest's `pytest_configure` hook in `tests/conftest.py` to inject mocks into Python's module system before any test collection begins. This runs even before pytest discovers test files, ensuring mocks are in place for module-level imports across the entire test suite.

```python
# tests/conftest.py
import sys
from unittest.mock import MagicMock
from tests._utilities import MockSerial

def pytest_configure(config):
    """Called before test collection begins"""
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
    sys.modules['serial'] = mock_serial_mod
    sys.modules['serial.tools'] = mock_tools
    sys.modules['serial.tools.list_ports'] = mock_list_ports
```

**Why the Hierarchy Matters**: Notice how `mock_serial_mod.tools` points to the same object as `sys.modules['serial.tools']`. This is crucial. When Python imports `serial.tools.list_ports`, it follows the hierarchy: first it finds `serial` in `sys.modules`, then accesses its `.tools` attribute, then accesses `.list_ports`. If these aren't the same object references, Python creates multiple mock instances. Tests will fail with mysterious assertion errors like `Expected 'method' to be called once. Called 0 times.` because the code under test called a *different* mock instance than the one being asserted against.

By placing this in the root `tests/conftest.py`, the mocks apply to all test groups in a single pytest run, so `pytest tests/` works correctly. The CI workflow still runs each group as a separate step, but this is for coverage accumulation (`--cov-append`), not for isolation.

**Caution — sys.modules is global state**: the injected mocks persist for the entire pytest session and cannot be undone. If a future test ever needs the *real* `serial` module (e.g. an integration test against physical hardware), it cannot coexist in the same pytest invocation. Similarly, adding a second `pytest_configure` hook in a subdirectory `conftest.py` that tries to install a different mock for the same module keys will silently win or lose depending on conftest load order, causing hard-to-diagnose failures. Keep all serial mocking in the single root conftest.

## Test Organisation

### Categories

Tests are organised by feature area:

1. **Initialization & Configuration** (`test_kvm_init.py`)
   - Window setup, menu creation, device discovery

2. **Device Management** (`test_kvm_device_mgmt.py`)
   - Serial port selection, camera enumeration, baud rate configuration, connection error handling

3. **Settings Persistence** (`test_kvm_settings_persistence.py`)
   - INI file operations, default value handling, invalid settings recovery

4. **Event Handling** (`test_kvm_events.py`)
   - Mouse coordinate translation, keyboard event processing, focus management

5. **Video Processing** (`test_kvm_video.py`)
   - Frame capture logic, frame rate management, error handling

6. **Paste** (`test_kvm_paste.py`)
   - Clipboard-to-remote text transmission, scancode sequencing

7. **Screenshot** (`test_kvm_screenshot.py`)
   - Screen capture and save functionality

### File Naming

- `test_kvm_base.py` - Base classes and utilities
- `test_kvm_*.py` - Feature-specific test suites
- Mirrors source structure for easy navigation

### Directory Structure

```text
tests/
├── conftest.py        # Root-level serial module mocking (applies to all groups)
├── _utilities.py      # Shared test utilities and MockSerial
├── backend/           # Backend implementation tests
│   └── ...
├── kvm/               # GUI application tests
│   └── ...
├── utils/             # Utility module tests
│   └── ...
└── test_control.py    # Control module tests
```

The root `tests/conftest.py` contains the `pytest_configure` hook that mocks serial modules for the entire suite. Running `pytest tests/` works correctly. The CI workflow runs each group in a separate step for coverage accumulation (`--cov-append`), not because isolation requires it.

## Running Tests

### Basic Execution

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/kvm/test_kvm_init.py

# Run specific test
pytest tests/kvm/test_kvm_init.py::TestKVMInitialization::test_window_initialization

# Verbose output
pytest -v

# With coverage
pytest --cov=kvm_serial
```

### Configuration

Tests configured in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = ["-v", "--tb=short", "--cov=kvm_serial", "--cov-report=term-missing", "--cov-report=lcov:lcov.info"]
timeout = 5
```

**Timeout protection:** Safeguard against event loop issues or runaway threads during testing.

## Common Issues and Solutions

### Issue: Tests Fail with Display Errors

**Cause:** GUI initialisation not properly mocked, causing Qt to attempt creating windows.

**Solution:** Ensure `_setup_qt_mocks` includes all used Qt components. Add missing widgets to mock lists. Tests may also timeout if event loops are created: check that `QApplication` and `QTimer` are mocked.

### Issue: Import Errors in Tests

**Cause:** Module imported before mocks established.

**Solution:** Move import inside `setUp` after starting patches.

### Issue: Tests Pass Individually but Fail in Suite

**Cause:** Missing module cleanup in `tearDown`.

**Solution:** Verify all tested modules are removed from `sys.modules`.

### Issue: "AttributeError: Mock object has no attribute X"

**Cause:** Mock needs return value or side effect configuration.

**Solution:**
```python
mock_obj = MagicMock()
mock_obj.method.return_value = expected_value
```

### Issue: Serial Exception Not Caught

**Cause:** Exception mock not configured properly.

**Solution:**
```python
with patch("serial.Serial", side_effect=SerialException("Port not available")):
    # Test code
```

## Continuous Integration

Tests run automatically via GitHub Actions (see `.github/workflows/test.yml`). Key considerations:

- Headless environment (no X server)
- All GUI mocking must be comprehensive  
- Timeout protection essential
- Coverage reporting to track test completeness

## Future Enhancements

Potential test suite improvements:

1. **Integration Tests**
   - End-to-end workflows
   - Settings persistence across restarts
   - Device reconnection scenarios

2. **Performance Tests**
   - Frame rate under load
   - Memory usage patterns
   - Serial communication latency

## Summary

The kvm-serial test suite demonstrates effective PyQt5 application testing through:

- **Comprehensive mocking** preventing unwanted side effects
- **Inheritance-based organisation** providing reusable infrastructure
- **Clear patterns** for common testing scenarios
- **Proper isolation** ensuring test independence

These strategies enable confident refactoring and feature development while maintaining reliable test coverage.
