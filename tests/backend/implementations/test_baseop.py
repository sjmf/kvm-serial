from pytest import fixture
from unittest.mock import patch, MagicMock
from tests._utilities import MockSerial, mock_serial

CLASS_PATH = "kvm_serial.backend.implementations.baseop"


@fixture
def sys_modules_patch():
    return {
        "serial": MagicMock(),
    }


class TestKeyboardOpImplementation:
    """Test suite for KeyboardOp base class implementation"""

    def test_baseop_init(self, mock_serial, sys_modules_patch):

        with (
            # I don't know why this makes test_mouse work, but at this point I'm too tired to care.
            patch.dict("sys.modules", sys_modules_patch),
            patch(f"kvm_serial.utils.communication.DataComm") as mock_datacomm,
        ):
            from kvm_serial.backend.implementations.baseop import KeyboardOp

            class ConcreteKeyboardOp(KeyboardOp):
                """Concrete implementation of KeyboardOp for testing"""

                def run(self):
                    return True

                def cleanup(self):
                    pass

                @property
                def name(self):
                    return "test_keyboard"

            # Create instance
            op = ConcreteKeyboardOp(mock_serial)

            # Verify initialization
            assert op.serial_port == mock_serial
            assert op.name == "test_keyboard"

            # Verify DataComm was initialized with correct serial port
            assert isinstance(op.hid_serial_out, MagicMock)
            mock_datacomm.assert_called_once_with(mock_serial)
