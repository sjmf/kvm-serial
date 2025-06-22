from pytest import fixture
from unittest.mock import MagicMock
from typing import Optional
from io import StringIO


class MockSerial:
    """Mock class for Serial object"""

    def __init__(self, port=None) -> None:
        self.output = StringIO()
        self.fd = self.output

        self.is_open: bool = False
        self.portstr: Optional[str] = None
        self.name: Optional[str] = None

        self.write = MagicMock(return_value=1)  # Mock the write method
        self.close = MagicMock(return_value=1)  # ...      close method


@fixture
def mock_serial():
    return MockSerial()


@fixture
def patch_isinstance_for_serial(mock_serial):
    """
    Keyboard __init__ makes extensive use of isinstance() for typechecking
    This is a /huge/ pain to test.
    So, patch isinstance() to treat mock_serial as Serial.
    This is nicer to test, albeit terrifying to look at.
    """
    import builtins

    orig_isinstance = builtins.isinstance

    def fake_isinstance(obj, typ):
        if obj is mock_serial and getattr(typ, "__name__", None) == "Serial":
            return True
        return orig_isinstance(obj, typ)

    builtins.isinstance = fake_isinstance

    try:
        yield
    finally:
        builtins.isinstance = orig_isinstance
