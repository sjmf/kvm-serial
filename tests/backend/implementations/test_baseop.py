from pytest import fixture
from unittest.mock import patch, MagicMock
from tests._utilities import MockSerial, mock_serial

CLASS_PATH = "kvm_serial.backend.implementations.baseop"


@fixture
def sys_modules_patch():
    return {
        "serial": MagicMock(),
    }


class TestBaseOpImplementation:
    """Test suite for BaseOp base class implementation"""

    def test_baseop_init(self, mock_serial, sys_modules_patch):

        with (
            # I don't know why this makes test_mouse work, but at this point I'm too tired to care.
            patch.dict("sys.modules", sys_modules_patch),
            patch("kvm_serial.backend.implementations.baseop.CH9329Comm") as mock_datacomm,
        ):
            from kvm_serial.backend.implementations.baseop import BaseOp

            class ConcreteBaseOp(BaseOp):
                """Concrete implementation of BaseOp for testing"""

                def run(self):
                    return True

                def cleanup(self):
                    pass

                @property
                def name(self):
                    return "test_keyboard"

            # Create instance
            op = ConcreteBaseOp(mock_serial)

            # Verify initialization
            assert op.serial_port == mock_serial
            assert op.name == "test_keyboard"

            # Verify DataComm was initialized with correct serial port and
            # that BaseOp called start() on the comm to kick off any
            # background activity (handshake threads, LED echo).
            assert isinstance(op.hid_serial_out, MagicMock)
            mock_datacomm.assert_called_once_with(mock_serial)
            op.hid_serial_out.start.assert_called_once()

    def test_baseop_uses_comm_cls(self, mock_serial, sys_modules_patch):
        """A custom comm_cls is invoked with the serial port and its
        return value becomes hid_serial_out."""

        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.implementations.baseop import BaseOp

            class ConcreteBaseOp(BaseOp):
                def run(self):
                    return True

                @property
                def name(self):
                    return "test"

            mock_comm = MagicMock()
            mock_factory = MagicMock(return_value=mock_comm)

            op = ConcreteBaseOp(mock_serial, comm_cls=mock_factory)

            mock_factory.assert_called_once_with(mock_serial)
            assert op.hid_serial_out is mock_comm
            mock_comm.start.assert_called_once()

    def test_baseop_cleanup_stops_comm(self, mock_serial, sys_modules_patch):
        """Default cleanup() forwards to the comm's stop() so background
        threads (CH9350 state 0) can exit cleanly."""

        with patch.dict("sys.modules", sys_modules_patch):
            from kvm_serial.backend.implementations.baseop import BaseOp

            class ConcreteBaseOp(BaseOp):
                def run(self):
                    return True

                @property
                def name(self):
                    return "test"

            mock_comm = MagicMock()
            op = ConcreteBaseOp(mock_serial, comm_cls=MagicMock(return_value=mock_comm))

            op.cleanup()
            mock_comm.stop.assert_called_once()
