#!/usr/bin/env python
# CH9329 keyboard controller
import signal
import sys
import argparse
import logging

from serial import Serial

logger = logging.getLogger(__name__)

# Globally visible listener objects for thread stop
ml = None
keeb = None


# Provide different options for handling SIGINT so Ctrl+C can be passed to controller
#  (not that it matters under pyusb, which captures all keyboard output!)
def signal_handler_exit(sig, frame):
    logging.warning("Exiting...")
    stop_threads()
    sys.exit(0)


def signal_handler_ignore(sig, frame):
    logging.debug("Ignoring Ctrl+C")


def start_threads(args, serial_port):
    """Start handler threads based on command line arguments.

    Args:
        args: Parsed command line arguments.
        serial_port: Serial port object for communication.
    """
    global ml, keeb

    # Start mouse listner on --mouse (-e)
    if args.mouse:
        from kvm_serial.backend.mouse import MouseListener

        ml = MouseListener(serial_port)
        ml.start()

    # Do not capture keyboard with --no-keyboard (-n)
    if not args.no_keyboard:
        from kvm_serial.backend.keyboard import KeyboardListener

        keeb = KeyboardListener(serial_port, mode=args.mode, layout=args.keyboard_layout)
        keeb.start()


def join_threads(args):
    global ml, keeb

    # Wait for threads to finish. The main thread depends on which inputs are active.
    if (args.mode == "none" or args.no_keyboard) and ml is not None:
        # Mouse-only: Ctrl+C raises KeyboardInterrupt and exits.
        logging.info("Waiting for mouse listener...")
        ml.thread.join()
    elif not args.no_keyboard and keeb is not None:
        # Keyboard listener owns the exit key (e.g. Ctrl+ESC).
        logging.info("Waiting for keyboard listener...")
        keeb.thread.join()


def stop_threads():
    global ml, keeb
    if ml is not None and ml.thread.is_alive():
        ml.stop()

    if keeb is not None and keeb.thread.is_alive():
        keeb.stop()


def parse_args():
    # Parse arguments using argparse module. Example call:
    # python control.py /dev/cu.usbserial --verbose --mode usb
    parser = argparse.ArgumentParser(
        prog="CH9329 Control Script",
        description="Use a serial terminal as a USB keyboard!",
        epilog="(c) 2023 Samantha Finnigan. MIT License",
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
        default="curses",
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
            "The --video / --windowed / --camindex switches have been removed."
            "Headless OpenCV-window video display is no longer supported.\n"
            "See https://github.com/sjmf/kvm-serial/issues/32 for more detail."
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
        join_threads(args)
    except KeyboardInterrupt:
        logging.warning("^C caught. Cleaning up!")
    except Exception as e:
        logging.error("An error occurred.")
        logging.error(e)
    finally:
        stop_threads()  # Stop remaining threads (if running)
        logging.info("Exiting. Bye!")


if __name__ == "__main__":
    main()
