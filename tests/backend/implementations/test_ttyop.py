import sys
import pytest
from unittest.mock import patch, MagicMock
from tests._utilities import MockSerial, mock_serial

CLASS_PATH = "kvm_serial.backend.implementations.ttyop"


@pytest.fixture
def sys_modules_patch():
    return {
        "tty": MagicMock(),
        "termios": MagicMock(),
    }


@patch("serial.Serial", MockSerial)
class TestTTYOperation:

    class MockTermiosError(Exception):
        """A mock exception class replacing termios.error"""

    @pytest.fixture
    def op(self, mock_serial, sys_modules_patch):
        """
        Fixture that creates and configures a TtyOp instance for testing.
        """
        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.implementations.ttyop import TtyOp

            op = TtyOp(mock_serial)
            op.hid_serial_out = MagicMock()
            return op

    def test_ttyop_name_property(self, op, sys_modules_patch):
        """
        Test that the 'name' property of TtyOp returns 'tty'.
        """
        with patch.dict("sys.modules", sys_modules_patch):
            assert op.name == "tty"

    def test_ttyop_input_loop(self, op, sys_modules_patch):
        """
        Test that run() calls tty.setcbreak, enters the input loop, and calls time.sleep.
        Mocks:
            - op._parse_key: Returns True then False (loop runs twice)
            - time.sleep: To verify it is called once
        Asserts:
            - tty.setcbreak called once
            - time.sleep called once (after first loop iteration)
        """

        # Patch _parse_key for two iterations, and time.sleep for checking
        with (
            patch.dict("sys.modules", sys_modules_patch),
            patch.object(op, "_parse_key", side_effect=[True, False]),
            patch("time.sleep") as mock_sleep,
        ):
            import tty as mock_tty

            op.run()
            mock_tty.setcbreak.assert_called_once()
            # Loop exited on second call means sleep called once:
            mock_sleep.assert_called_once()

    def test_ttyop_run_termios_error(self, op, sys_modules_patch):
        """
        Test that run() raises Exception if termios.error is raised by tty.setcbreak.
        Mocks:
            - termios.error: Replaced with MockTermiosError
            - tty.setcbreak: Raises MockTermiosError
        Asserts:
            - Exception is raised with the expected error message
        """

        # Patch termios.error to the class, and tty.setcbreak to raise it
        with patch.dict("sys.modules", sys_modules_patch):
            import termios, tty

            with (
                patch.object(termios, "error", self.MockTermiosError),
                patch.object(tty, "setcbreak", side_effect=self.MockTermiosError),
            ):
                with pytest.raises(Exception) as e:
                    op.run()
                    assert "Run this app from a terminal!" in str(e.value)

    def test_ttyop_parse_key(self, caplog, sys_modules_patch, mock_serial):
        """
        Test that _parse_key reads a character, converts it to a scancode, logs, and sends it.
        Mocks:
            - sys.stdin.read: Returns 'a' to simulate user input
            - ascii_to_scancode: Returns a known scancode list
        Asserts:
            - ascii_to_scancode is called once with 'a'
            - scancode is logged at DEBUG level
            - hid_serial_out.send_scancode is called with the correct bytes
            - hid_serial_out.release is called once
            - _parse_key returns True
        """
        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.implementations import ttyop as ttyop_mod

            with patch.object(ttyop_mod, "ascii_to_scancode") as mock_scancode:
                mock_scancode.return_value = [0, 0, 42, 0, 0, 0, 0, 0]

                # We cannot use the op mock here, because ascii_to_scancode will already be initialised
                # when TtyOp is, resulting in a patching failure. We must re-create it here.
                op = ttyop_mod.TtyOp(mock_serial)
                op.hid_serial_out = MagicMock()

                with patch.object(sys.stdin, "read", lambda n=-1: "a"):
                    with caplog.at_level("DEBUG"):
                        assert op._parse_key() is True

                # Mock ascii_to_scancode called once with 'a'
                mock_scancode.assert_called_once_with("a")

                # Assert scancode logged at DEBUG level
                assert any(
                    "42" in record.getMessage() and record.levelname == "DEBUG"
                    for record in caplog.records
                )

                # Assert hid_serial_out.send_scancode and release called
                op.hid_serial_out.send_scancode.assert_called_once_with(
                    bytes(mock_scancode.return_value)
                )
                op.hid_serial_out.release.assert_called_once()

    def test_legacy_main_tty(self, mock_serial, sys_modules_patch):
        """
        Test that main_tty instantiates TtyOp, calls run, and returns None.
        Mocks:
            - TtyOp: Patched so instantiation and run can be tracked
        Asserts:
            - TtyOp instantiated with the correct argument
            - run() called once
            - main_tty returns None
        """
        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.implementations import ttyop as ttyop_mod

            with patch.object(ttyop_mod, "TtyOp") as mock_op:
                mock_op.return_value.run.return_value = None
                assert ttyop_mod.main_tty(mock_serial) is None
                mock_op.assert_called_once_with(mock_serial)
                mock_op.return_value.run.assert_called_once()
