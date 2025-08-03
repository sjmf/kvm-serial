from abc import ABC, abstractmethod
from serial import Serial
from kvm_serial.utils.communication import DataComm


class BaseOp(ABC):
    """
    Abstract base class for input capture implementations.
    All implementations must provide a run() method that takes a serial_port argument.
    """

    serial_port: Serial
    hid_serial_out: DataComm

    def __init__(self, serial_port: Serial):
        """
        Initialize the operation with the given serial port, and
        establish DataComm class for ch9329 communication
        :param serial_port: The serial port to communicate with.
        """
        self.serial_port = serial_port
        self.hid_serial_out = DataComm(self.serial_port)

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
