from abc import ABC, abstractmethod


class InputHandler(ABC):
    """
    Abstract base class for handling input to the system
    Contains thread-like functionality
    """

    @abstractmethod
    def run(self):
        """
        Start the handler and block until complete
        In practice, this will probably mean start threads and join them
        """

    @abstractmethod
    def start(self):
        """
        Start theads in non-blocking mode (i.e. don't call '.join()')
        """

    @abstractmethod
    def stop(self):
        """
        Stop operation threads. Should block until .join()ed
        """
