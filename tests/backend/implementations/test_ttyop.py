from unittest.mock import patch
from kvm_serial.backend.implementations.ttyop import TtyOp
from tests._utilities import MockSerial, mock_serial


class TestTTYOperation:
    @patch("serial.Serial", MockSerial)
    def test_name_property(self, mock_serial):
        """Test that the name property returns 'tty'"""
        op = TtyOp(mock_serial)
        assert op.name == "tty"

    @patch("serial.Serial", MockSerial)
    @patch("kvm_serial.backend.implementations.ttyop.tty")
    def test_ttyop_input_loop(self, mock_tty, mock_serial):
        op = TtyOp(mock_serial)

        # Patch _parse_key to return False immediately
        with patch.object(TtyOp, "_parse_key", return_value=False):
            op.run()

        assert mock_tty.setcbreak.called

    # TODO: Implement further tests