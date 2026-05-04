from abc import ABC, abstractmethod
from typing import Type
from serial import Serial
from kvm_serial.utils.communication import DataComm
from kvm_serial.utils.ch9329 import CH9329Comm


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
        comm_cls: Type[DataComm] | None = None,
    ):
        """
        Initialise the operation with the given serial port, and
        instantiate the protocol implementation that will encapsulate
        HID events for the target chip family.

        :param serial_port: The serial port to communicate with.
        :param layout: Keyboard layout to use (default: 'en_GB')
        :param comm_cls: DataComm subclass to use (default: CH9329Comm)
        """
        self.serial_port = serial_port
        if comm_cls is None:
            comm_cls = CH9329Comm
        self.hid_serial_out = comm_cls(self.serial_port)
        self.layout = layout

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
        Optional cleanup method for implementations that need it.
        """
