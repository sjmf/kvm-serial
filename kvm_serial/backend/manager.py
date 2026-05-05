"""
DataCommManager: lifecycle owner for the protocol comm and the input
listeners attached to it.

The manager exists because a single serial port can drive at most one
comm instance — CH9350L state 0/1 in particular spawns rx + tx-maintenance
threads, so two MouseOp/KeyboardOp ops each instantiating their own
CH9350Comm would race for the UART, run the descriptor handshake twice,
and emit interleaved frames with desynchronised counters.

Singleton-of-one: ``DataCommManager(serial_port, comm_cls=...)`` constructs
the comm and registers itself; ``DataCommManager.get()`` returns the same
instance from anywhere (typically from BaseOp.__init__, which fetches the
shared comm). ``reset()`` is the test escape hatch.
"""

from __future__ import annotations

import logging
from typing import Callable, ClassVar

from serial import Serial

from kvm_serial.backend.inputhandler import InputHandler
from kvm_serial.utils.communication import DataComm

logger = logging.getLogger(__name__)

CommCls = Callable[[Serial], DataComm]


class DataCommManager:
    """
    Singleton owning the DataComm instance and the input listeners
    attached to it. Centralises start/join/stop so individual ops and
    listeners don't manage lifecycle.
    """

    _instance: ClassVar["DataCommManager | None"] = None

    def __init__(self, serial_port: Serial, comm_cls: CommCls):
        if DataCommManager._instance is not None:
            raise RuntimeError(
                "DataCommManager already initialised; call reset() first or "
                "use DataCommManager.get() to retrieve the existing instance"
            )
        self.serial_port = serial_port
        self.comm: DataComm = comm_cls(serial_port)
        self._listeners: list[InputHandler] = []
        DataCommManager._instance = self

    @classmethod
    def get(cls) -> "DataCommManager":
        """Return the singleton. Raises if no manager has been initialised."""
        if cls._instance is None:
            raise RuntimeError(
                "DataCommManager not initialised; construct one before " "instantiating any BaseOp"
            )
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """
        Test hook: drop the singleton so the next constructor call succeeds.
        Stops the comm and any attached listeners first, best-effort, so
        background threads don't leak across tests.
        """
        if cls._instance is None:
            return
        try:
            cls._instance.stop()
        except Exception:
            logger.exception("DataCommManager.reset(): stop() raised, ignoring")
        cls._instance = None

    def attach(self, listener: InputHandler) -> None:
        """Register an input listener. Listeners are started in attach order."""
        self._listeners.append(listener)

    def start(self) -> None:
        """Start the comm (handshake / threads) then every attached listener."""
        self.comm.start()
        for listener in self._listeners:
            listener.start()

    def join(self) -> None:
        """
        Block on the primary listener's thread. The keyboard listener owns
        the exit key (e.g. Ctrl+ESC) when present; otherwise fall back to
        the first attached listener.
        """
        # Avoid a circular import: KeyboardListener imports manager indirectly.
        from kvm_serial.backend.keyboard import KeyboardListener

        primary = next(
            (l for l in self._listeners if isinstance(l, KeyboardListener)),
            self._listeners[0] if self._listeners else None,
        )
        if primary is None:
            return
        thread = getattr(primary, "thread", None)
        if thread is not None and hasattr(thread, "join"):
            thread.join()

    def stop(self) -> None:
        """Stop every listener (best-effort) then the comm."""
        for listener in self._listeners:
            try:
                listener.stop()
            except Exception:
                logger.exception("Listener stop() raised, continuing")
        try:
            self.comm.stop()
        except Exception:
            logger.exception("Comm stop() raised")
