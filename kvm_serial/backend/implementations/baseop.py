from abc import ABC, abstractmethod
from serial import Serial
from kvm_serial.utils.communication import DataComm


class BaseOp(ABC):
    """
    Abstract base class for input capture implementations.

    All implementations must provide a run() method. The shared DataComm
    instance is fetched from the DataCommManager singleton; lifecycle
    (start/stop) is the manager's responsibility, not the op's.
    """

    serial_port: Serial
    hid_serial_out: DataComm
    layout: str

    def __init__(self, serial_port: Serial, layout: str = "en_GB"):
        """
        Initialise the operation, binding the shared protocol implementation
        from the active DataCommManager.

        :param serial_port: The serial port to communicate with.
        :param layout: Keyboard layout to use (default: 'en_GB')
        """
        # Import locally to avoid a circular import at module load time
        # (manager -> keyboard -> backend.implementations.* -> baseop).
        from kvm_serial.backend.manager import DataCommManager

        self.serial_port = serial_port
        self.layout = layout
        self.hid_serial_out = DataCommManager.get().comm

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
        Hook for implementation-specific cleanup. The shared comm's
        lifecycle is owned by DataCommManager.stop(), not by individual
        BaseOps.
        """
