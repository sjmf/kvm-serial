import sys
import pytest
from unittest.mock import patch, MagicMock
from tests._utilities import MockSerial, mock_serial

TTY_MOCKS = {
    "tty": MagicMock(),
    "termios": MagicMock(),
    "kvm_serial.utils.utils": MagicMock(),
}


@patch.dict(sys.modules, TTY_MOCKS)
@patch("serial.Serial", MockSerial)
class TestTTYOperation:

    class MockTermiosError(Exception):
        """A mock exception class replacing termios.error"""

    @pytest.fixture
    @patch.dict(sys.modules, TTY_MOCKS)
    def op(self, mock_serial):
        """
        Fixture that creates and configures a TtyOp instance for testing.
        """
        from kvm_serial.backend.implementations.ttyop import TtyOp

        op = TtyOp(mock_serial)
        op.hid_serial_out = MagicMock()
        return op

    def test_ttyop_name_property(self, op):
        """
        Test that the 'name' property of TtyOp returns 'tty'.
        """
        assert op.name == "tty"

    def test_ttyop_input_loop(self, op):
        """
        Test that run() calls tty.setcbreak, enters the input loop, and calls time.sleep.
        Mocks:
            - op._parse_key: Returns True then False (loop runs twice)
            - time.sleep: To verify it is called once
        Asserts:
            - tty.setcbreak called once
            - time.sleep called once (after first loop iteration)
        """
        import tty as mock_tty

        # Patch _parse_key for two iterations, and time.sleep for checking
        with (
            patch.object(op, "_parse_key", side_effect=[True, False]),
            patch("time.sleep") as mock_sleep,
        ):
            op.run()
            mock_tty.setcbreak.assert_called_once()
            # Loop exited on second call means sleep called once:
            mock_sleep.assert_called_once()

    def test_ttyop_run_termios_error(self, op):
        """
        Test that run() raises Exception if termios.error is raised by tty.setcbreak.
        Mocks:
            - termios.error: Replaced with MockTermiosError
            - tty.setcbreak: Raises MockTermiosError
        Asserts:
            - Exception is raised with the expected error message
        """
        import termios, tty

        # Patch termios.error to the class, and tty.setcbreak to raise it
        with (
            patch.object(termios, "error", self.MockTermiosError),
            patch.object(tty, "setcbreak", side_effect=self.MockTermiosError),
        ):
            with pytest.raises(Exception) as e:
                op.run()
                assert "Run this app from a terminal!" in str(e.value)

    def test_ttyop_parse_key(self, op, caplog):
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
        from kvm_serial.utils.utils import ascii_to_scancode as mock_scancode

        mock_scancode.return_value = [0, 0, 42, 0, 0, 0, 0, 0]

        with patch.object(sys.stdin, "read", lambda n=-1: "a"):
            with caplog.at_level("DEBUG"):
                assert op._parse_key() is True

        # Mock ascii_to_scancode called once with 'a'
        mock_scancode.assert_called_once_with("a")

        # Assert scancode logged at DEBUG level
        assert any(
            "42" in record.getMessage() and record.levelname == "DEBUG" for record in caplog.records
        )

        # Assert hid_serial_out.send_scancode and release called
        op.hid_serial_out.send_scancode.assert_called_once_with(bytes(mock_scancode.return_value))
        op.hid_serial_out.release.assert_called_once()

        mock_scancode.reset_mock()

    def test_legacy_main_tty(self, mock_serial):
        """
        Test that main_tty instantiates TtyOp, calls run, and returns None.
        Mocks:
            - TtyOp: Patched so instantiation and run can be tracked
        Asserts:
            - TtyOp is instantiated with the correct argument
            - run() is called once
            - main_tty returns None
        """
        from kvm_serial.backend.implementations.ttyop import main_tty

        with patch("kvm_serial.backend.implementations.ttyop.TtyOp") as mock_ttyop:
            mock_ttyop.return_value._parse_key.side_effect = False
            mock_ttyop.return_value.run.return_value = None
            assert main_tty(mock_serial) is None
            mock_ttyop.assert_called_once_with(mock_serial)
            mock_ttyop.return_value.run.assert_called_once()
