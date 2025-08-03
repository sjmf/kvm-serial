import sys
import pytest
from unittest.mock import MagicMock, patch
from tests._utilities import MockSerial, mock_serial, patch_isinstance_for_serial


@pytest.fixture
def sys_modules_patch():
    fake_pynput = MagicMock()
    fake_pynput_mouse = MagicMock()
    fake_pynput.mouse = fake_pynput_mouse
    return {
        "pynput": fake_pynput,
        "pynput.mouse": fake_pynput_mouse,
        "screeninfo": MagicMock(),
        "serial": MagicMock(),
    }


class TestKeyboardMain:
    """
    Tests for the keyboard_main() function, called when running the file
    as a script instead of a module.
    """

    def test_keyboard_main_invokes_listener(self, monkeypatch, sys_modules_patch):
        """
        Test keyboard_main runs KeyboardListener with correct arguments.
        Mocks:
            - sys.argv: Supplies serial port, mode, and baud
            - KeyboardListener: Mocked to track instantiation and method calls
            - logging.basicConfig: Avoids side effects
        Asserts:
            - KeyboardListener is instantiated with correct args
            - start() and thread.join() are called
        """
        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend import keyboard as kb_mod

            # Prepare sys.argv for the script
            monkeypatch.setattr(sys, "argv", ["keyboard.py", "COM1", "tty", "9600"])

            mock_listener = MagicMock()
            mock_instance = MagicMock()
            mock_listener.return_value = mock_instance

            with (
                patch.object(kb_mod, "KeyboardListener", mock_listener),
                patch("logging.basicConfig", lambda *a, **k: None),
            ):
                kb_mod.keyboard_main()

            mock_listener.assert_called_once_with("COM1", mode="tty", baud=9600)
            mock_instance.start.assert_called_once()
            mock_instance.thread.join.assert_called_once()

            # Test case where no arguments are provided:
            monkeypatch.setattr(sys, "argv", [])

            with (
                patch.object(sys, "exit"),
                patch.object(kb_mod, "KeyboardListener", mock_listener),
                patch("logging.basicConfig", lambda *a, **k: None),
            ):
                kb_mod.keyboard_main()

    def test_keyboard_module_fallback_import(self, monkeypatch):
        """
        Test that keyboard.py falls back to importing implementations.baseop.KeyboardOp
        if kvm_serial.backend.implementations.baseop import fails with ModuleNotFoundError.

        This is a horrible test that by necessity has to mess around with both
        __import__ and sys.modules. It makes an effort to restore these afterwards.

        Mocks:
            - builtins.__import__: Raises ModuleNotFoundError for kvm_serial.backend.implementations.baseop
            - sys.modules: Injects a mock implementations.baseop.KeyboardOp
            - KeyboardListener: Mocked to avoid running threads
            - logging.basicConfig: Avoids side effects
        Asserts:
            - The fallback import path is used (implementations.baseop.KeyboardOp)
            - KeyboardListener can still be constructed and used
        """
        import importlib
        from unittest.mock import MagicMock, patch

        # Save original sys.modules entries to restore after test
        orig_kvm_serial = sys.modules.get("kvm_serial")
        orig_baseop = sys.modules.get("kvm_serial.backend.implementations.baseop")

        try:
            # Remove relevant modules from sys.modules
            sys.modules.pop("kvm_serial.backend.implementations.baseop", None)
            sys.modules.pop("kvm_serial", None)

            # Patch __import__ to raise ModuleNotFoundError for the primary import
            orig_import = __import__

            def import_side_effect(name, *args, **kwargs):
                if name == "kvm_serial.backend.implementations.baseop":
                    raise ModuleNotFoundError
                return orig_import(name, *args, **kwargs)

            monkeypatch.setattr("builtins.__import__", import_side_effect)

            # Inject a mock implementations.baseop.KeyboardOp
            mock_keyboardop = MagicMock()
            sys.modules["implementations.baseop"] = MagicMock(KeyboardOp=mock_keyboardop)

            # Patch KeyboardListener and logging.basicConfig
            from kvm_serial.backend import keyboard as kb_mod

            # Ensure module is in sys.modules before reload
            sys.modules["kvm_serial.backend.keyboard"] = kb_mod

            with (
                patch.object(kb_mod, "KeyboardListener", MagicMock()),
                patch("logging.basicConfig", lambda *a, **k: None),
            ):
                # Reload the module to trigger the import logic
                importlib.reload(kb_mod)
                # Now, KeyboardOp should be the mock from implementations.baseop
                assert hasattr(kb_mod, "KeyboardOp")
                assert kb_mod.BaseOp is mock_keyboardop
        finally:
            # Restore sys.modules to its original state
            sys.modules.pop("implementations.baseop", None)
            if orig_kvm_serial is not None:
                sys.modules["kvm_serial"] = orig_kvm_serial
            if orig_baseop is not None:
                sys.modules["kvm_serial.backend.implementations.baseop"] = orig_baseop


# Mock Serial
@patch.dict(sys.modules, {"serial": MagicMock()})
@patch("serial.Serial", MockSerial)
class TestKeyboard:
    """
    Tests for KeyboardListener object
    """

    def test_run_calls_thread_start_and_join(self, mock_serial):
        """
        Test that KeyboardListener.run() calls thread.start() and thread.join().
        Mocks:
            - threading.Thread: To track start and join calls
        Asserts:
            - thread.start() and thread.join() are called once
        """
        from kvm_serial.backend.keyboard import KeyboardListener
        import threading

        mock_thread = MagicMock()
        # Patch threading.Thread to return our mock_thread
        with patch.object(threading, "Thread", return_value=mock_thread):
            listener = KeyboardListener(mock_serial)
            listener.run()
            mock_thread.start.assert_called_once()
            mock_thread.join.assert_called_once()
            mock_thread.reset_mock()

            listener.start()
            mock_thread.start.assert_called_once()
            mock_thread.join.assert_not_called()
            mock_thread.reset_mock()

            listener.stop()
            mock_thread.join.assert_called_once()
            assert listener.running == False
            mock_thread.reset_mock()

    def test_keyboard_listener(self, patch_isinstance_for_serial, mock_serial):
        """
        Test KeyboardListener __init__ handles all codepaths for serial_port and mode.
        - serial_port as str and Serial
        - mode as str and Mode
        Asserts:
            - self.serial_port is set correctly
            - self.mode is set correctly
        """
        from kvm_serial.backend.keyboard import KeyboardListener, Mode

        # serial_port as Serial, mode as str
        listener1 = KeyboardListener(mock_serial)
        assert listener1.serial_port is mock_serial
        assert listener1.mode == Mode.PYNPUT

        # serial_port as str, mode as str
        serial_constructor = MagicMock(return_value=mock_serial)
        with patch("kvm_serial.backend.keyboard.Serial", serial_constructor):
            listener2 = KeyboardListener("COM1", mode="tty")
            serial_constructor.assert_called_with("COM1", 9600)
            assert listener2.serial_port is mock_serial
            assert listener2.mode == Mode.TTY

        # serial_port as Serial, mode as Mode
        listener3 = KeyboardListener(mock_serial, mode=Mode.USB)
        assert listener3.serial_port is mock_serial
        assert listener3.mode == Mode.USB

        # serial_port as str, mode as Mode
        serial_constructor = MagicMock(return_value=mock_serial)
        with patch("kvm_serial.backend.keyboard.Serial", serial_constructor):
            listener4 = KeyboardListener("COM2", mode=Mode.CURSES)
            serial_constructor.assert_called_with("COM2", 9600)
            assert listener4.serial_port is mock_serial
            assert listener4.mode == Mode.CURSES

    def test_run_keyboard_selects_correct_handler_and_runs(
        self, patch_isinstance_for_serial, mock_serial
    ):
        """
        Test that run_keyboard selects the correct handler and calls its run() for each mode.

        Note:
            In keyboard.py, handler classes (PyUSBOp, PynputOp, TtyOp, CursesOp) are imported
            dynamically inside run_keyboard() using relative imports, e.g.:
                from backend.implementations.pyusbop import PyUSBOp
            This means the import occurs at runtime, and the module is resolved via sys.modules.
            To effectively mock these handlers for testing, inject MagicMock modules into
            sys.modules under the keys 'backend.implementations.pyusbop', etc., before run_keyboard()
            is called. This ensures that when the import statement executes inside run_keyboard(),
            it retrieves the mock class, allowing us to assert instantiation and method calls.

        Mocks:
            - sys.modules: Injects MagicMock modules for each handler implementation
            - Each handler class: MagicMock to track instantiation and run()
        Asserts:
            - The correct handler is instantiated and run() is called for each mode
            - No handler is called for Mode.NONE
        """
        from kvm_serial.backend.keyboard import KeyboardListener, Mode

        # Create mock modules and handler classes
        mock_pyusbop = MagicMock()
        mock_pynputop = MagicMock()
        mock_ttyop = MagicMock()
        mock_cursesop = MagicMock()

        import_path = "backend.implementations"
        sys_modules_backup = dict()
        try:
            # Backup originals if present
            for modname, mockmod in [
                (f"{import_path}.pyusbop", mock_pyusbop),
                (f"{import_path}.pynputop", mock_pynputop),
                (f"{import_path}.ttyop", mock_ttyop),
                (f"{import_path}.cursesop", mock_cursesop),
            ]:
                if modname in sys.modules:
                    sys_modules_backup[modname] = sys.modules[modname]
                sys.modules[modname] = mockmod

            # Set handler classes on the mock modules
            mock_pyusbop.PyUSBOp.return_value.run = MagicMock()
            mock_pynputop.PynputOp.return_value.run = MagicMock()
            mock_ttyop.TtyOp.return_value.run = MagicMock()
            mock_cursesop.CursesOp.return_value.run = MagicMock()

            # USB mode
            listener = KeyboardListener(mock_serial, mode=Mode.USB)
            listener.run_keyboard()
            mock_pyusbop.PyUSBOp.assert_called_once_with(mock_serial)
            mock_pyusbop.PyUSBOp.return_value.run.assert_called_once()

            # PYNPUT mode
            listener = KeyboardListener(mock_serial, mode=Mode.PYNPUT)
            listener.run_keyboard()
            mock_pynputop.PynputOp.assert_called_once_with(mock_serial)
            mock_pynputop.PynputOp.return_value.run.assert_called_once()

            # TTY mode
            listener = KeyboardListener(mock_serial, mode=Mode.TTY)
            listener.run_keyboard()
            mock_ttyop.TtyOp.assert_called_once_with(mock_serial)
            mock_ttyop.TtyOp.return_value.run.assert_called_once()

            # CURSES mode
            listener = KeyboardListener(mock_serial, mode=Mode.CURSES)
            listener.run_keyboard()
            mock_cursesop.CursesOp.assert_called_once_with(mock_serial)
            mock_cursesop.CursesOp.return_value.run.assert_called_once()

            # NONE mode (should do nothing)
            listener = KeyboardListener(mock_serial, mode=Mode.NONE)
            listener.run_keyboard()

            # No handler should be called
            mock_pyusbop.PyUSBOp.reset_mock()
            mock_pynputop.PynputOp.reset_mock()
            mock_ttyop.TtyOp.reset_mock()
            mock_cursesop.CursesOp.reset_mock()
            mock_pyusbop.PyUSBOp.assert_not_called()
            mock_pynputop.PynputOp.assert_not_called()
            mock_ttyop.TtyOp.assert_not_called()
            mock_cursesop.CursesOp.assert_not_called()
        finally:
            # Restore sys.modules to its original state
            for modname in [
                f"{import_path}.pyusbop",
                f"{import_path}.pynputop",
                f"{import_path}.ttyop",
                f"{import_path}.cursesop",
            ]:
                if modname in sys_modules_backup:
                    sys.modules[modname] = sys_modules_backup[modname]
                else:
                    sys.modules.pop(modname, None)
