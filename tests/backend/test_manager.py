"""
Tests for DataCommManager — the singleton that owns the comm + listener
lifecycle for a kvm-serial run.
"""

from unittest.mock import MagicMock, call
import pytest

from kvm_serial.backend.manager import DataCommManager


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Make sure no stale singleton from another test leaks into this file."""
    DataCommManager.reset()
    yield
    DataCommManager.reset()


def test_init_invokes_comm_cls_with_serial_port():
    """The comm_cls callable receives the serial port and the resulting
    comm becomes the manager's ``comm`` attribute."""
    serial = MagicMock()
    comm = MagicMock()
    cls = MagicMock(return_value=comm)

    mgr = DataCommManager(serial, comm_cls=cls)

    cls.assert_called_once_with(serial)
    assert mgr.comm is comm
    assert mgr.serial_port is serial


def test_double_init_raises():
    """Attempting to construct a second manager without resetting raises."""
    DataCommManager(MagicMock(), comm_cls=lambda p: MagicMock())
    with pytest.raises(RuntimeError, match="already initialised"):
        DataCommManager(MagicMock(), comm_cls=lambda p: MagicMock())


def test_get_without_init_raises():
    """get() before any constructor surfaces a clear error rather than
    silently auto-creating one."""
    with pytest.raises(RuntimeError, match="not initialised"):
        DataCommManager.get()


def test_get_returns_singleton():
    """get() hands back the same instance on repeated calls."""
    mgr = DataCommManager(MagicMock(), comm_cls=lambda p: MagicMock())
    assert DataCommManager.get() is mgr
    assert DataCommManager.get() is mgr


def test_reset_drops_singleton_and_stops_comm():
    """reset() stops the comm and clears the singleton so a fresh one can
    be constructed."""
    comm = MagicMock()
    DataCommManager(MagicMock(), comm_cls=lambda p: comm)

    DataCommManager.reset()

    comm.stop.assert_called_once()
    with pytest.raises(RuntimeError):
        DataCommManager.get()


def test_attach_registers_listeners_in_order():
    mgr = DataCommManager(MagicMock(), comm_cls=lambda p: MagicMock())
    a, b = MagicMock(), MagicMock()

    mgr.attach(a)
    mgr.attach(b)

    assert mgr._listeners == [a, b]


def test_start_runs_comm_then_listeners():
    """start() calls comm.start() before any listener.start() so handshake
    completes (CH9350 state 0) before user input can fire."""
    comm = MagicMock()
    mgr = DataCommManager(MagicMock(), comm_cls=lambda p: comm)
    a, b = MagicMock(), MagicMock()
    mgr.attach(a)
    mgr.attach(b)

    # Use an order-preserving manager mock to verify call sequencing.
    order = MagicMock()
    order.attach_mock(comm.start, "comm_start")
    order.attach_mock(a.start, "a_start")
    order.attach_mock(b.start, "b_start")

    mgr.start()

    assert order.mock_calls == [call.comm_start(), call.a_start(), call.b_start()]


def test_stop_runs_listeners_then_comm():
    """stop() halts listeners first then the comm, mirroring start()."""
    comm = MagicMock()
    mgr = DataCommManager(MagicMock(), comm_cls=lambda p: comm)
    a, b = MagicMock(), MagicMock()
    mgr.attach(a)
    mgr.attach(b)

    order = MagicMock()
    order.attach_mock(a.stop, "a_stop")
    order.attach_mock(b.stop, "b_stop")
    order.attach_mock(comm.stop, "comm_stop")

    mgr.stop()

    assert order.mock_calls == [call.a_stop(), call.b_stop(), call.comm_stop()]


def test_stop_continues_past_listener_exception():
    """A listener whose stop() raises shouldn't prevent the others from
    being stopped, nor the comm."""
    comm = MagicMock()
    mgr = DataCommManager(MagicMock(), comm_cls=lambda p: comm)
    bad = MagicMock()
    bad.stop.side_effect = RuntimeError("listener exploded")
    good = MagicMock()
    mgr.attach(bad)
    mgr.attach(good)

    mgr.stop()

    bad.stop.assert_called_once()
    good.stop.assert_called_once()
    comm.stop.assert_called_once()


def test_join_blocks_on_keyboard_listener_when_present():
    """join() prefers the keyboard listener (it owns the exit key
    Ctrl+ESC); falls back to the first attached otherwise."""
    from kvm_serial.backend.keyboard import KeyboardListener

    mgr = DataCommManager(MagicMock(), comm_cls=lambda p: MagicMock())

    mouse_listener = MagicMock()
    mouse_listener.thread = MagicMock()
    keeb_listener = MagicMock(spec=KeyboardListener)
    keeb_listener.thread = MagicMock()

    mgr.attach(mouse_listener)
    mgr.attach(keeb_listener)

    mgr.join()

    keeb_listener.thread.join.assert_called_once()
    mouse_listener.thread.join.assert_not_called()


def test_join_falls_back_to_first_listener():
    """No keyboard listener attached: join() blocks on the first one."""
    mgr = DataCommManager(MagicMock(), comm_cls=lambda p: MagicMock())

    listener = MagicMock()
    listener.thread = MagicMock()
    mgr.attach(listener)

    mgr.join()

    listener.thread.join.assert_called_once()


def test_join_with_no_listeners_is_a_noop():
    """No listeners = nothing to wait on; join() returns silently."""
    mgr = DataCommManager(MagicMock(), comm_cls=lambda p: MagicMock())
    mgr.join()  # should not raise
