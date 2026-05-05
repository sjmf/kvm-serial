# Supported Devices

kvm-serial supports two UART-to-USB-HID bridge chip families.

## CH9329

The CH9329 is a command-driven chip where the host sends HID reports over UART and the chip translates them into USB HID input on the target machine.

- Simple command-style protocol
- 4095x4095 12-bit absolute mouse coordinate space
- Relative mouse support
- Keyboard boot protocol

Protocol reference: [CH9329 Protocol](CH9329_PROTO.md)

## CH9350L

The CH9350L is a paired-chip extender. kvm-serial replaces the lower computer (LC) side in software and drives an upper computer (UC) module that presents USB HID to the target machine.

- Four working states selected via UC dipswitches
- State 0/1: full HID descriptor passthrough with pairing handshake
- State 2: BIOS keyboard + relative mouse for legacy BIOS / UEFI CSM
- State 3: BIOS keyboard + absolute mouse for modern OS use
- State 4: BIOS keyboard + absolute mouse + HID Digitizers for multi-monitor setups
- 65535x65535 16-bit absolute mouse coordinate space in states 3/4
- Heartbeat and keep-alive synchronization

Protocol reference: [CH9350L Protocol](CH9350L_PROTO.md)

## Hardware Notes

- CH9329 hardware is commonly sold as pre-assembled cables or small modules.
- CH9350L hardware is more commonly sold as breakout boards with dipswitches.
- Both families are typically used with a USB-to-UART adapter such as CP2102, CH340, FTDI, or similar.