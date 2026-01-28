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
    return [
        patch("kvm_serial.backend.video.CaptureDevice"),
        patch("kvm_serial.utils.communication.list_serial_ports"),
        patch("kvm_serial.kvm.Serial"),
    ]
```

**Pattern:** Mock at the interface boundary where the application interacts with hardware libraries.

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

Each mixin adds domain-specific helper methods without forcing every test to inherit functionality it doesn't need. `SerialTestMixin` provides methods for creating mock serial ports, `VideoTestMixin` handles mock cameras, and `SettingsTestMixin` helps with configuration file testing. Tests can mix and match these based on what they're testing.

## Common Patterns

### Creating Mock Devices

**Serial ports:**

```python
test_ports = self.create_mock_serial_ports()
# Returns: ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0"]
```

**Cameras:**

```python
cameras = self.create_mock_cameras(count=2)
# Each has: .index, .width, .height, __str__()
```

### Error Handling Tests

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
patch("serial.Serial")
patch("cv2.VideoCapture")
```

Mock external dependencies, not internal code (except when deliberately isolating units).

### 2. Verify Behaviour, Not Implementation

❌ **Don't test:**

```python
mock_method.assert_called()
```

✅ **Do test:**

```python
self.assertEqual(app.serial_port_var, expected_port)
self.assertTrue(app.keyboard_op is not None)
```

Focus on observable outcomes rather than internal method calls.

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

    for module in ["kvm_serial.kvm", "kvm_serial.backend.video"]:
        if module in sys.modules:
            del sys.modules[module]
```

Prevents test interdependencies and ensures fresh imports.

### 6. Early Module Mocking with pytest_configure

**The Problem**: Some production modules use module-level imports like `from serial.tools import list_ports`. This import executes when Python loads the module, *before* any test setup can mock it. The real `serial` module gets loaded and cached in `sys.modules`, making any subsequent mocking attempts ineffective since Python won't re-import an already cached module.

**Why Not Modify Production Code?**: We could add `try/except` blocks or lazy imports to production code, but that would be polluting the codebase to accommodate tests: exactly backwards. Tests should adapt to production code, not the other way around.

**The Solution**: Use pytest's `pytest_configure` hook to inject mocks into Python's module system before any test collection begins. This runs even before pytest discovers test files, ensuring mocks are in place for module-level imports.

```python
# tests/utils/conftest.py
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

**The sys.modules Pollution Tradeoff**: This approach modifies global state (`sys.modules`) that persists across all tests in a pytest session. That sounds dangerous: and it is. The tradeoff is that `pytest tests/` will fail in ways that are unclear to the developer, so we have to work around this. The CI workflow runs test groups in separate pytest invocations (backend, utils, kvm, control), giving each a fresh Python process with clean `sys.modules`.

This means:

- Each test group can safely mock `sys.modules` without affecting others
- Running `pytest tests/` locally might fail due to mock conflicts, but CI will pass
- Always test using the same commands as CI: `pytest tests/backend/`, `pytest tests/utils/`, etc.

**Where to Use This**: Only test directories that import production code with module-level serial imports need this pattern. Currently: `tests/utils/` and `tests/backend/`. The KVM tests don't need it because they mock at a higher level.

## Test Organisation

### Categories

Tests are organised by feature area (see Test_Categories document):

1. **Initialization & Configuration** (`test_kvm_init.py`)
   - Window setup
   - Menu creation
   - Settings loading/saving
   - Device discovery

2. **Device Management** (`test_kvm_device_mgmt.py`)
   - Serial port selection
   - Camera enumeration
   - Baud rate configuration
   - Connection error handling

3. **Settings Persistence** (covered in init tests)
   - INI file operations
   - Default value handling
   - Invalid settings recovery

4. **Event Handling** (future expansion)
   - Mouse coordinate translation
   - Keyboard event processing
   - Focus management

5. **Video Processing** (future expansion)
   - Frame capture logic
   - Frame rate management
   - Error handling

### File Naming

- `test_kvm_base.py` - Base classes and utilities
- `test_kvm_*.py` - Feature-specific test suites
- Mirrors source structure for easy navigation

### Directory Structure and Test Isolation

The test suite is organised to match how CI runs tests: this organisation isn't arbitrary, it's essential for the mocking strategy to work:

```text
tests/
├── backend/           # Backend implementation tests
│   ├── conftest.py   # Serial module mocking for backend
│   └── ...
├── kvm/              # GUI application tests
│   └── ...
├── utils/            # Utility module tests
│   ├── conftest.py   # Serial module mocking for utils
│   └── ...
└── test_control.py   # Control module tests
```

#### Why Separate pytest Invocations Matter

The GitHub Actions workflow (`.github/workflows/test.yml`) deliberately runs each test group as a separate command:

```bash
pytest tests/backend/  # Separate process
pytest tests/utils/    # Separate process
pytest tests/kvm/      # Separate process
pytest tests/test_control.py  # Separate process
```

This isn't just for organisation: it's fundamental to how the mocking works. Each pytest invocation spawns a fresh Python interpreter with a clean `sys.modules` dictionary. This means:

**The Good**: Test groups with different mocking needs (like `tests/utils/` and `tests/kvm/`) can each pollute `sys.modules` however they want without interfering with each other. The `pytest_configure` hook in `tests/utils/conftest.py` mocks the serial module for utils tests, and by the time `tests/kvm/` runs, that's in a completely different process with no memory of those mocks.

**The Gotcha**: Running `pytest tests/` locally runs *all* test groups in one process. The `pytest_configure` hooks from multiple `conftest.py` files all run in the same `sys.modules`, causing conflicts. Tests might fail locally but pass in CI.

**Best Practice**: Always test using the CI commands. If you're working on backend code, run `pytest tests/backend/`. If you need to verify everything works, run each group separately just like CI does.

This is an intentional tradeoff: running the entire suite locally is awkward in exchange for being able to mock aggressively without complex isolation machinery.

## Running Tests

### Basic Execution

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_kvm_init.py

# Run specific test
pytest tests/test_kvm_init.py::TestKVMInitialization::test_window_initialization

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
addopts = ["-v", "--tb=short", "--cov=kvm_serial"]
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

1. **Event Handling Tests**
   - Mouse coordinate translation logic
   - Keyboard event processing
   - Serial communication triggers

2. **Video Processing Tests**  
   - Frame capture request logic
   - Frame rate management
   - Canvas size updates

3. **Integration Tests**
   - End-to-end workflows
   - Settings persistence across restarts
   - Device reconnection scenarios

4. **Performance Tests**
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
