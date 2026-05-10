"""
Per-directory pytest configuration for backend op tests.

Op tests (PyUSBOp, TtyOp, CursesOp, PynputOp, MouseOp, ...) all instantiate
a BaseOp subclass, which fetches its DataComm from the active
DataCommManager singleton. This autouse fixture installs a fresh manager
wrapping a MagicMock comm so op constructors succeed without each test
having to wire one up by hand.

The fixture deliberately lives in this subdirectory rather than the root
conftest: importing kvm_serial.backend.manager pre-loads kvm_serial.backend
into sys.modules, which interacts badly with patch.dict-based sys.modules
manipulation in tests that load other backend submodules inside a
patch.dict block (the patch evicts the submodule on exit, but the parent
package's stale attribute survives, leaving sys.modules and attribute-path
imports resolving to different module objects). Scoping the manager
import to the implementations/ subtree keeps the rest of tests/backend/
unaffected.
"""

from unittest.mock import MagicMock
import pytest


@pytest.fixture(autouse=True)
def _datacomm_manager():
    """Install a fresh DataCommManager singleton wrapping a MagicMock comm
    for every op test in this subtree. Reset on teardown."""
    from kvm_serial.backend.manager import DataCommManager

    DataCommManager.reset()
    mgr = DataCommManager(MagicMock(), comm_cls=lambda port: MagicMock())
    try:
        yield mgr
    finally:
        DataCommManager.reset()
