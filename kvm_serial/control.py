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
cap = None
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
    global ml, cap, keeb

    # Start mouse listner on --mouse (-e)
    if args.mouse:
        from kvm_serial.backend.mouse import MouseListener

        ml = MouseListener(serial_port)
        ml.start()

    # Do not capture keyboard with --no-keyboard (-n)
    if not args.no_keyboard:
        from kvm_serial.backend.keyboard import KeyboardListener

        keeb = KeyboardListener(serial_port, mode=args.mode)
        keeb.start()

    # Display video window if --video (-x)
    if args.video:
        from kvm_serial.backend.video import CaptureDevice

        cap = CaptureDevice(fullscreen=(not args.windowed))
        if args.camindex:
            cap.setCamera(args.camindex)


def join_threads(args):
    global ml, cap, keeb

    # Wait for threads to finish.
    # The main thread is different depending on the options provided.
    if (args.mode == "none" or args.no_keyboard) and not args.video:
        # Wait on mouse if no keyboard capture, unless video
        # If only mouse is captured, Ctrl+C will raise a keyboard interrupt,
        # which allows us to exit the program
        logging.info("Waiting for mouse listener...")
        ml.thread.join()  # type: ignore (static analysis doesn't know about MouseListener)

    elif not args.no_keyboard and not args.video:
        # If not running video, wait on KeyboardListener to exit
        # (unless no keyboard capture)
        # Exit is handled by the listener implementation (e.g. Ctrl+ESC)
        logging.info("Waiting for keyboard listener...")
        keeb.thread.join()  # type: ignore

    else:
        # Video only
        # Exit handled by closing the video window or ESC
        logging.info("Waiting for video capture...")
        cap.capture()  # type: ignore
        # Video window does not work in a thread on OSX. :/
        # I bet CV2 is using Tk internally.
        # Perform capture() in our main thread for now.
        # If we're using pynput, can disable ESC key: it's Ctrl+ESC only (prevent crash)
        # exitKey=(0 if args.mode == "pynput" and args.mouse else 27)
        # nope, this will only work if video runs in a thread.


def stop_threads():
    global ml, cap, keeb
    if ml is not None and ml.thread.is_alive():
        ml.stop()

    if cap is not None and cap.thread is not None and cap.thread.is_alive():
        cap.stop()

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
        "Video Options",
        description="Define video options",
    )
    vids_group.add_argument(
        "--video",
        "-x",
        help="Display video",
        action="store_true",
    )
    vids_group.add_argument(
        "--windowed",
        "-w",
        help="Display video in window",
        action="store_true",
    )
    vids_group.add_argument(
        "--camindex",
        "-c",
        help="Use video device at specific offset",
        action="store",
        type=int,
    )

    return parser.parse_args()


def log_warnings(args):
    # Log warnings for various options:
    if args.no_keyboard:
        logging.warning("Keyboard input will NOT be passed (--no-keyboard / -n)")
    if args.mode == "pynput" and args.sigint != "ignore":
        logging.warning("Consider using --mode='pynput' with --sigint=ignore")
    if args.mode != "pynput" and args.mouse:
        logging.warning("Consider using --mode='pynput' with --mouse (-e)")
    if args.windowed and not args.video:
        logging.warning("--windowed (-w) arg will not work without --video (-x)")
    if args.camindex and not args.video:
        logging.warning("--camindex (-c) arg will not work without --video (-x)")


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
