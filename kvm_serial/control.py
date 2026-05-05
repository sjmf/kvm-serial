#!/usr/bin/env python
# Serial KVM controller for USB HID Serial Bridges (CH9329, CH9350L)
import signal
import sys
import argparse
import logging
import platform

# Allow running as a script directly (python kvm_serial/control.py) by ensuring
# the project root is on sys.path so that `kvm_serial.*` imports resolve.
try:
    from importlib import import_module

    import_module("kvm_serial.backend")
except ModuleNotFoundError:
    import os

    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from serial import Serial

logger = logging.getLogger(__name__)

# The single DataCommManager for this run; stop_threads() joins it.
mgr = None


# Provide different options for handling SIGINT so Ctrl+C can be passed to controller
#  (not that it matters under pyusb, which captures all keyboard output!)
def signal_handler_exit(sig, frame):
    logging.warning("Exiting...")
    stop_threads()
    sys.exit(0)


def signal_handler_ignore(sig, frame):
    logging.debug("Ignoring Ctrl+C")


def _build_comm_cls(args):
    """
    Resolve --ch9350 / --ch9350-state into a DataComm-producing callable.
    Defaults to CH9329Comm (the class itself, which is callable).
    """
    if args.ch9350:
        from kvm_serial.utils.ch9350 import CH9350Comm

        state = args.ch9350_state
        return lambda port: CH9350Comm(port, state=state)
    from kvm_serial.utils.ch9329 import CH9329Comm

    return CH9329Comm


def start_threads(args, serial_port):
    """Construct the DataCommManager, attach listeners per CLI flags, and
    start everything.

    Args:
        args: Parsed command line arguments.
        serial_port: Serial port object for communication.
    """
    global mgr
    from kvm_serial.backend.manager import DataCommManager

    mgr = DataCommManager(serial_port, comm_cls=_build_comm_cls(args))

    # Start mouse listener on --mouse (-e)
    if args.mouse:
        from kvm_serial.backend.mouse import MouseListener

        mgr.attach(MouseListener(serial_port))

    # Do not capture keyboard with --no-keyboard (-n)
    if not args.no_keyboard:
        from kvm_serial.backend.keyboard import KeyboardListener

        mgr.attach(KeyboardListener(serial_port, mode=args.mode, layout=args.keyboard_layout))

    mgr.start()


def join_threads():
    if mgr is not None:
        mgr.join()


def stop_threads():
    global mgr
    if mgr is not None:
        mgr.stop()
        # Drop the singleton so a subsequent run (e.g. from tests) can
        # build a fresh manager without tripping the "already initialised"
        # guard.
        from kvm_serial.backend.manager import DataCommManager

        DataCommManager.reset()
        mgr = None


def parse_args():
    # Parse arguments using argparse module. Example call:
    # python control.py /dev/cu.usbserial --verbose --mode usb
    parser = argparse.ArgumentParser(
        prog="Serial KVM Control Script",
        description="Use a serial terminal as a USB keyboard and mouse!",
        epilog="(c) 2023-25 Samantha Finnigan and contributors. MIT License",
    )

    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("port", action="store")
    parser.add_argument(
        "--baud",
        "-b",
        help="Set baud rate for serial device",
        default=9600,
        type=int,
    )
    parser.add_argument(
        "--sigint",
        "-s",
        help="Capture SIGINT (Ctrl+C) instead of handling in shell",
        action="store",
        default="nohandle",
        type=str,
        choices=["exit", "ignore", "nohandle"],
    )
    parser.add_argument(
        "--mode",
        "-m",
        help="Set keyboard capture mode",
        default="curses" if platform.system() != "Windows" else "pynput",
        type=str,
        choices=["usb", "pynput", "tty", "curses", "none"],
    )
    parser.add_argument(
        "--keyboard-layout",
        "-l",
        help="Set keyboard layout",
        default="en_GB",
        type=str,
        choices=["en_US", "en_GB"],
    )
    parser.add_argument(
        "--no-keyboard",
        "-n",
        help="Do not capture keyboard",
        action="store_true",
    )
    parser.add_argument(
        "--mouse",
        "-e",
        help="Capture mouse input",
        action="store_true",
    )
    proto_group = parser.add_mutually_exclusive_group()
    proto_group.add_argument(
        "--ch9329",
        help="Use the CH9329 protocol (default; flag for imperative declaration)",
        action="store_true",
    )
    proto_group.add_argument(
        "--ch9350",
        help="Use the CH9350L extender protocol",
        action="store_true",
    )
    parser.add_argument(
        "--ch9350-state",
        help="CH9350L working state to drive (default 2: legacy BIOS / UEFI CSM "
        "compatible). 0 = paired-mode descriptor handshake; 3 = absolute mouse; "
        "4 = HID Digitizers. See docs/CH9350L_PROTO.md.",
        type=int,
        default=2,
        choices=[0, 2, 3, 4],
    )
    vids_group = parser.add_argument_group(
        "Video Options (removed)",
        description="Headless video display has been removed. Switches accepted "
        "for backwards compatibility but error out if used. Use `kvm-gui` instead.",
    )
    vids_group.add_argument("--video", "-x", action="store_true", help=argparse.SUPPRESS)
    vids_group.add_argument("--windowed", "-w", action="store_true", help=argparse.SUPPRESS)
    vids_group.add_argument("--camindex", "-c", action="store", type=int, help=argparse.SUPPRESS)

    return parser.parse_args()


def log_warnings(args):
    # Log warnings for various options:
    if args.no_keyboard:
        logging.warning("Keyboard input will NOT be passed (--no-keyboard / -n)")
    if args.mode == "pynput" and args.sigint != "ignore":
        logging.warning("Consider using --mode='pynput' with --sigint=ignore")
    if args.mode != "pynput" and args.mouse:
        logging.warning("Consider using --mode='pynput' with --mouse (-e)")


def set_signalhandlers(args):
    # Handle SIGINT / Ctrl + C, which user might want to pass through
    if "exit" in args.sigint:
        signal.signal(signal.SIGINT, signal_handler_exit)
    elif "ignore" in args.sigint:
        signal.signal(signal.SIGINT, signal_handler_ignore)


def main():
    args = parse_args()

    # Set log level
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(message)s")

    if args.video or args.windowed or args.camindex is not None:
        logging.error(
            "The --video / --windowed / --camindex switches have been removed.\n"
            "Headless OpenCV-window video display is no longer supported.\n"
            "See https://github.com/sjmf/kvm-serial/issues/32 for more detail.\n"
            "Use the GUI (`kvm-gui`) for live video, or install the last working "
            "version with: pip install 'kvm-serial==1.5.4'"
        )
        sys.exit(2)

    set_signalhandlers(args)
    log_warnings(args)

    # Make serial connection
    serial_port = Serial(args.port, args.baud)

    try:
        start_threads(args, serial_port)
        join_threads()
    except KeyboardInterrupt:
        logging.warning("^C caught. Cleaning up!")
    except Exception as e:
        logging.error("An error occurred.")
        logging.error(e)
    finally:
        stop_threads()  # Stop remaining threads (if running)
        logging.info("Exiting. Bye!")
        logging.shutdown()  # Flush and close all handlers before exit


if __name__ == "__main__":
    main()
