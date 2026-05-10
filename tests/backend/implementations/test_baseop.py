from unittest.mock import patch, MagicMock
from tests._utilities import MockSerial, mock_serial


class TestBaseOpImplementation:
    """Test suite for BaseOp base class implementation"""

    def test_baseop_init_uses_manager_comm(self, mock_serial, _datacomm_manager):
        """BaseOp fetches its DataComm from the active DataCommManager
        rather than instantiating one itself."""
        from kvm_serial.backend.implementations.baseop import BaseOp

        class ConcreteBaseOp(BaseOp):
            def run(self):
                return True

            @property
            def name(self):
                return "test"

        op = ConcreteBaseOp(mock_serial)

        assert op.serial_port is mock_serial
        assert op.name == "test"
        # The autouse _datacomm_manager fixture installs a singleton whose
        # comm is a MagicMock; BaseOp should hand out exactly that instance.
        assert op.hid_serial_out is _datacomm_manager.comm

    def test_baseop_init_raises_without_manager(self, mock_serial):
        """Constructing a BaseOp with no manager initialised raises a
        clear error rather than silently auto-creating a comm."""
        from kvm_serial.backend.implementations.baseop import BaseOp
        from kvm_serial.backend.manager import DataCommManager

        class ConcreteBaseOp(BaseOp):
            def run(self):
                return True

            @property
            def name(self):
                return "test"

        # The autouse fixture has a manager set up; tear it down for this
        # test to assert the no-manager error path.
        DataCommManager.reset()
        try:
            import pytest

            with pytest.raises(RuntimeError, match="not initialised"):
                ConcreteBaseOp(mock_serial)
        finally:
            # Restore a fresh manager so the autouse fixture's teardown
            # doesn't trip a stale singleton.
            DataCommManager(MagicMock(), comm_cls=lambda port: MagicMock())

    def test_baseop_cleanup_is_a_noop(self, mock_serial, _datacomm_manager):
        """BaseOp.cleanup() no longer touches the comm (lifecycle is the
        manager's responsibility); subclasses can override for their own
        cleanup needs."""
        from kvm_serial.backend.implementations.baseop import BaseOp

        class ConcreteBaseOp(BaseOp):
            def run(self):
                return True

            @property
            def name(self):
                return "test"

        op = ConcreteBaseOp(mock_serial)
        op.cleanup()
        _datacomm_manager.comm.stop.assert_not_called()
