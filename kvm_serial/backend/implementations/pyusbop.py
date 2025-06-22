# PyUSB implementation
import logging
import time
import usb.core
from typing import Callable
from kvm_serial.utils.utils import scancode_to_ascii
from .baseop import KeyboardOp

logger = logging.getLogger(__name__)


class PyUSBOp(KeyboardOp):
    """
    PyUSB operation mode: supports all modifier keys, requires superuser.

    This mode uses the PyUSB library to interact with USB devices directly.
    It reads keyboard scancodes from the USB endpoint and translates them
    into ASCII characters, printing them to the console.
    Use Ctrl+ESC to exit the operation.

    :param serial_port: Serial port to use for communication (not used in this mode)
    :type serial_port: str
    :raises usb.core.USBError: If there is an error accessing the USB device
    :raises usb.core.NoBackendError: If no suitable USB backend is found
    :raises usb.core.USBTimeoutError: If the USB operation times out
    :raises usb.core.USBError: For other USB-related errors
    :example:
        >>> from kvm_serial.backend.implementations.pyusb import PyUSBOp
        >>> op = PyUSBOp("/dev/ttyUSB0")
        >>> op.run()

    :note: This operation mode requires superuser permissions to access USB devices.
    :note: Input is blocked and collected outside of console focus.
    :note: This mode does not support paste functionality.
    """

    @property
    def name(self):
        return "usb"

    def __init__(self, serial_port):
        super().__init__(serial_port)
        self.usb_endpoints = get_usb_endpoints()
        self.debounce = None

    def _sleep_interval(self, callback: Callable, interval=0.05, *args, **kwargs):
        """Rate-limit a callback function to avoid busy-waiting.
        :param callback: Function to call
        :param interval: Minimum time interval between calls in seconds
        """
        start = time.time()
        retval = callback(*args, **kwargs)
        elapsed = time.time() - start
        if elapsed < interval:
            time.sleep(interval - elapsed)
        return retval

    def run(self):
        """
        Main method for control using pyusb (requires superuser)
        :return:
        """
        logging.info(
            "Using PyUSB operation mode.\n"
            "All modifier keys supported. Paste not supported.\n"
            "Requires superuser permission.\n"
            "Input blocked and collected outside console focus."
        )

        # Required scope for 'finally' block
        dev = interface_number = None

        try:
            endpoint, dev, interface_number = [*self.usb_endpoints.values()][0]
            self.debounce = None

            # Detach kernel driver to perform raw IO with device (requires elevated sudo privileges)
            # Otherwise you will receive "[Errno 13] Access denied (insufficient permissions)"
            if dev.is_kernel_driver_active(interface_number):
                dev.detach_kernel_driver(interface_number)

            logging.info("Press Ctrl+ESC to exit")

            while self._sleep_interval(self._parse_key, endpoint=endpoint):
                pass

        except usb.core.USBError as e:
            logging.error(e)
            if e.errno == 13:
                logging.error("This script does not seem to be running as superuser.")

        finally:
            usb.util.dispose_resources(dev)
            if dev is not None:
                dev.attach_kernel_driver(interface_number)

    def _parse_key(self, endpoint: usb.core.Endpoint):
        # Read keyboard scancodes
        try:
            data_in = endpoint.read(getattr(endpoint, "wMaxPacketSize"), timeout=100)
        except usb.core.USBError as e:
            if e.errno == 60:
                logging.debug("[Errno 60] Operation timed out. Continuing...")
                return True
            raise e

        # Check for escape sequence (and helpful prompt)
        if data_in[0] == 0x1 and data_in[2] == 0x6 and self.debounce != "c":  # Ctrl+C:
            logging.warning("\nCtrl+C passed through. Use Ctrl+ESC to exit!")

        if data_in[0] == 0x1 and data_in[2] == 0x29:  # Ctrl+ESC:
            logging.warning("\nCtrl+ESC escape sequence detected! Exiting...")
            return False

        key = scancode_to_ascii(data_in)

        # Debug print scancodes:
        logging.debug(f"{data_in}, \t({', '.join([hex(i) for i in data_in])}) \t{key}")

        if key != self.debounce and key:
            # print(key, end="", flush=True)
            self.debounce = key
        elif not key:
            self.debounce = None

        return self.hid_serial_out.send_scancode(data_in)


def get_usb_endpoints():
    endpoints = {}

    # Find all USB devices
    try:
        devices = usb.core.find(find_all=True)
    except usb.core.NoBackendError as e:
        logging.error(
            "The PyUSB library cannot find a suitable USB backend (such as libusb)"
            " on your system. Install one using your system's package manager, e.g.:\n"
            "\t$ sudo apt-get install libusb-1.0-0-dev (Debian/Ubuntu)\n"
            "\t$ sudo dnf install libusb1-devel (RHEL/Fedora)\n"
            "\t$ brew install libusb (MacOSX)\n"
        )
        raise e

    if devices is None:
        logging.warning("No USB devices found.")
        return endpoints

    # Iterate through connected USB devices
    for device in devices:
        # Ensure we only process Device objects (not Configuration)
        try:
            # Using duck typing, non-Device objects are skipped via exception.
            cfg = device.get_active_configuration()  # type: ignore[reportAttributeAccessIssue]

            # Check if the device is a keyboard
            if getattr(device, "bDeviceClass") != 0 or getattr(device, "bDeviceSubClass") != 0:
                continue

            interface_number = list(cfg)[0].bInterfaceNumber
            intf = usb.util.find_descriptor(
                cfg,
                bInterfaceNumber=interface_number,
            )

            endpoint = usb.util.find_descriptor(
                intf,
                custom_match=lambda e: (
                    usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
                    and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_INTR,
                ),
            )

            # Check if the endpoint is valid and if the interface is a keyboard
            # A keyboard will have the following: (https://wuffs.org/blog/mouse-adventures-part-5)
            # bInterfaceClass == 0x3
            # bInterfaceSubClass == 0x1
            # bInterfaceProtocol == 0x1 (mouse is protocol 0x2)
            if endpoint and (
                getattr(intf, "bInterfaceClass") == 0x03
                and getattr(intf, "bInterfaceSubClass") == 0x01
                and getattr(intf, "bInterfaceProtocol") == 0x01
            ):
                vendorID = getattr(device, "idVendor")
                productID = getattr(device, "idProduct")
                logger.info(
                    f"Found USB Keyboard: vID: 0x{vendorID:04x}; "
                    f"pID: 0x{productID:04x}; "
                    f"if: {interface_number}"
                )
                logger.debug(intf)

                endpoints[f"{vendorID:04x}:{productID:04x}"] = (
                    endpoint,
                    device,
                    interface_number,
                )

        except (AttributeError, TypeError):
            logging.info(f"Skipping non-device or non-interface object: {device}")
        except usb.core.USBError as e:
            logging.error(
                "USB error while processing device: '"
                f"{getattr(device, 'manufacturer')} {getattr(device, 'product')}'"
                f"\n{e}"
            )

    logging.debug(f"Found {len(endpoints)} USB Keyboard endpoints.")
    return endpoints


def main_usb(serial_port):
    return PyUSBOp(serial_port).run()
