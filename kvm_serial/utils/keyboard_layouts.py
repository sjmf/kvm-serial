"""
Keyboard layout definitions and utilities.

This module provides keyboard layout mappings for different languages/regions.
It uses a base layout (en_GB) with override dictionaries for layout-specific differences.
"""

from typing import Dict, Optional

# Base layout (en_GB ISO) - source of truth for all standard HID mappings
# Maps ASCII characters to HID scan codes
BASE_LAYOUT = {
    # fmt: off
    # Lowercase letters
    'a': 0x04, 'b': 0x05, 'c': 0x06, 'd': 0x07, 'e': 0x08, 'f': 0x09, 'g': 0x0a, 'h': 0x0b,
    'i': 0x0c, 'j': 0x0d, 'k': 0x0e, 'l': 0x0f, 'm': 0x10, 'n': 0x11, 'o': 0x12, 'p': 0x13,
    'q': 0x14, 'r': 0x15, 's': 0x16, 't': 0x17, 'u': 0x18, 'v': 0x19, 'w': 0x1a, 'x': 0x1b,
    'y': 0x1c, 'z': 0x1d,
    # Numbers (without shift)
    '1': 0x1e, '2': 0x1f, '3': 0x20, '4': 0x21, '5': 0x22, '6': 0x23, '7': 0x24, '8': 0x25,
    '9': 0x26, '0': 0x27,
    # Symbols (without shift)
    '-': 0x2d, '=': 0x2e, '[': 0x2f, ']': 0x30, '#': 0x32, ';': 0x33, "'": 0x34, '`': 0x35,
    ',': 0x36, '.': 0x37, '/': 0x38, '\\': 0x64,
    # Control characters
    '\n': 0x28, '\t': 0x2b, '\b': 0x2a, ' ': 0x2c,
    # Uppercase letters (with shift)
    'A': 0x04, 'B': 0x05, 'C': 0x06, 'D': 0x07, 'E': 0x08, 'F': 0x09, 'G': 0x0a, 'H': 0x0b,
    'I': 0x0c, 'J': 0x0d, 'K': 0x0e, 'L': 0x0f, 'M': 0x10, 'N': 0x11, 'O': 0x12, 'P': 0x13,
    'Q': 0x14, 'R': 0x15, 'S': 0x16, 'T': 0x17, 'U': 0x18, 'V': 0x19, 'W': 0x1a, 'X': 0x1b,
    'Y': 0x1c, 'Z': 0x1d,
    # Symbols (with shift) - UK ISO layout
    '!': 0x1e, '"': 0x1f, '£': 0x20, '$': 0x21, '%': 0x22, '^': 0x23, '&': 0x24, '*': 0x25,
    '(': 0x26, ')': 0x27, '_': 0x2d, '+': 0x2e, '{': 0x2f, '}': 0x30, '~': 0x32, ':': 0x33,
    '@': 0x34, '¬': 0x35, '<': 0x36, '>': 0x37, '?': 0x38, '|': 0x64,
    # fmt: on
}

# Layout-specific overrides
# Each layout specifies only the characters that differ from the base layout
# Set value to None to mark a character as unavailable in that layout
LAYOUT_OVERRIDES: Dict[str, Dict[str, Optional[int]]] = {
    "en_GB": {
        # No overrides needed - uses base layout
    },
    "en_US": {
        # US ANSI layout differences from UK ISO
        # Double quote: in US it's Shift+' (0x34), in UK it's Shift+2 (0x1f)
        '"': 0x34,
        # At sign: in US it's Shift+2 (0x1f), in UK it's Shift+' (0x34)
        "@": 0x1F,
        # Hash/Pound: in US it's Shift+3 (0x20), in UK it's Shift+3 but outputs £
        # In UK base, '£': 0x20, so we need to make '#' also 0x20 for US
        "#": 0x20,
        # Pound sterling: not available in US layout
        "£": None,
        # Not sign (¬): not available in US layout
        "¬": None,
    },
}


def get_layout(layout_name: str) -> Dict[str, int]:
    """
    Get complete keyboard layout by merging base layout with overrides.

    Args:
        layout_name: Name of the layout (e.g., 'en_US', 'en_GB')

    Returns:
        Dictionary mapping ASCII characters to HID scan codes

    Raises:
        ValueError: If layout_name is not recognized
    """
    if layout_name not in LAYOUT_OVERRIDES:
        raise ValueError(
            f"Unknown keyboard layout: {layout_name}. "
            f"Available layouts: {', '.join(get_available_layouts())}"
        )

    # Start with base layout
    layout = BASE_LAYOUT.copy()

    # Apply overrides
    overrides = LAYOUT_OVERRIDES[layout_name]
    for char, scancode in overrides.items():
        if scancode is None:
            # Remove character if marked as unavailable
            layout.pop(char, None)
        else:
            # Override with new scancode
            layout[char] = scancode

    return layout


def get_available_layouts() -> list[str]:
    """
    Get list of available keyboard layouts.

    Returns:
        List of layout names
    """
    return sorted(list(LAYOUT_OVERRIDES.keys()))
