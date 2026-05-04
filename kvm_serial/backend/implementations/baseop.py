from abc import ABC, abstractmethod
from typing import Callable
from serial import Serial
from kvm_serial.utils.communication import DataComm
from kvm_serial.utils.ch9329 import CH9329Comm


CommCls = Callable[[Serial], DataComm]


class BaseOp(ABC):
    """
    Abstract base class for input capture implementations.
    All implementations must provide a run() method that takes a serial_port argument.
    """

    serial_port: Serial
    hid_serial_out: DataComm
    layout: str

    def __init__(
        self,
        serial_port: Serial,
        layout: str = "en_GB",
        comm_cls: CommCls | None = None,
    ):
        """
        Initialise the operation with the given serial port, and instantiate
        the protocol implementation that will encapsulate HID events for the
        target chip family.

        :param serial_port: The serial port to communicate with.
        :param layout: Keyboard layout to use (default: 'en_GB')
        :param comm_cls: Callable taking a Serial and returning a DataComm.
            Defaults to CH9329Comm. Pass a lambda / partial to select an
            alternative protocol (e.g. ``lambda p: CH9350Comm(p, state=2)``).
        """
        self.serial_port = serial_port
        if comm_cls is None:
            comm_cls = CH9329Comm
        self.hid_serial_out = comm_cls(self.serial_port)
        self.layout = layout
        # Start any background threads or handshake the comm needs. CH9329Comm
        # inherits the ABC's no-op; CH9350Comm overrides for state 0/1
        # descriptor announce + state 2/3/4 LED echo.
        self.hid_serial_out.start()

    @abstractmethod
    def run(self):
        """
        Start the operation mode using the given serial port.
        :param serial_port: The serial port to communicate with.
        """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Return the name of the implementation.
        """

    def cleanup(self):
        """
        Stop the comm's background activity. Override to add implementation-
        specific cleanup, but call ``super().cleanup()`` to release the comm.
        """
        self.hid_serial_out.stop()
