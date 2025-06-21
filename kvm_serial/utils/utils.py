"""
Utilities for character code conversion
"""

from array import array


def scancode_to_ascii(scancode, raise_err: bool = False):
    """
    Convert a keyboard scancode to its ASCII representation
    :param scancode:
    :param raise_err: Raise KeyError instead of returning None if mapping fails
    :return: mapping to ASCII
    """
    key = 0
    index = 2

    # If multiple keydowns come in before a key-up, they are buffered in the rollover buffer
    while index < len(scancode) <= 8:
        key = scancode[index]
        if key > 0:
            break
        index += 1

    # This function is customised to UK-ISO keyboard layout. ANSI scancodes have differences.
    # fmt: off
    hid_to_ascii_mapping = {
        0x04: 'a', 0x05: 'b', 0x06: 'c', 0x07: 'd', 0x08: 'e', 0x09: 'f', 0x0a: 'g', 0x0b: 'h',
        0x0c: 'i', 0x0d: 'j', 0x0e: 'k', 0x0f: 'l', 0x10: 'm', 0x11: 'n', 0x12: 'o', 0x13: 'p',
        0x14: 'q', 0x15: 'r', 0x16: 's', 0x17: 't', 0x18: 'u', 0x19: 'v', 0x1a: 'w', 0x1b: 'x',
        0x1c: 'y', 0x1d: 'z', 0x1E: '1', 0x1F: '2', 0x20: '3', 0x21: '4', 0x22: '5', 0x23: '6',
        0x24: '7', 0x25: '8', 0x26: '9', 0x27: '0', 0x2D: '-', 0x2E: '=', 0x2F: '[', 0x30: ']',
        0x31: '#', 0x32: '#', 0x33: ';', 0x34: "'", 0x35: '`', 0x36: ',', 0x37: '.', 0x38: '/',
        0x39: 'CAPSLOCK', 0x29: 'ESC', 0x4f: '→', 0x50: '←', 0x51: '↓', 0x52: '↑',
        0x49: 'Ins', 0x4a: 'Home', 0x4b: 'PgUp', 0x4c: 'Del', 0x4d: 'End', 0x4e: 'PgDn',
        0x28: '\n', 0x2C: ' ', 0x2B: '\t', 0x2a: '\b', 0x64: '\\',
    }

    # Overwrite dict values for shift-modified keys. Note: must deep-copy dict!
    modifier_ascii_mapping = hid_to_ascii_mapping.copy()
    modifier_ascii_mapping.update({
        0x04: 'A', 0x05: 'B', 0x06: 'C', 0x07: 'D', 0x08: 'E', 0x09: 'F', 0x0A: 'G', 0x0B: 'H',
        0x0C: 'I', 0x0D: 'J', 0x0E: 'K', 0x0F: 'L', 0x10: 'M', 0x11: 'N', 0x12: 'O', 0x13: 'P',
        0x14: 'Q', 0x15: 'R', 0x16: 'S', 0x17: 'T', 0x18: 'U', 0x19: 'V', 0x1A: 'W', 0x1B: 'X',
        0x1C: 'Y', 0x1D: 'Z', 0x1E: '!', 0x1F: '"', 0x20: '#', 0x21: '$', 0x22: '%', 0x23: '^',
        0x24: '&', 0x25: '*', 0x26: '(', 0x27: ')', 0x2D: '_', 0x2E: '+', 0x2F: '{', 0x30: '}',
        0x31: '~', 0x32: '~', 0x33: ':', 0x34: '@', 0x35: '¬', 0x36: '<', 0x37: '>', 0x38: '?',
        0x64: '|'
    })
    # fmt: on

    try:
        if scancode[0] & 0x22 or scancode[0] & 0x22:  # LShift 0x2 or RShift 0x20 held
            return modifier_ascii_mapping[key]
        return hid_to_ascii_mapping[key]
    except KeyError as e:
        if not raise_err:
            return None
        raise e


def ascii_to_scancode(ascii_char):
    """
    Convert an ASCII character to a scancode
    :param ascii_char:
    :return: scancode (bytes array)
    """
    # No modifier (L/RShift) held
    # fmt: off
    ascii_to_hid_mapping = {
        'a': 0x04, 'b': 0x05, 'c': 0x06, 'd': 0x07, 'e': 0x08, 'f': 0x09, 'g': 0x0a,
        'h': 0x0b, 'i': 0x0c, 'j': 0x0d, 'k': 0x0e, 'l': 0x0f, 'm': 0x10, 'n': 0x11,
        'o': 0x12, 'p': 0x13, 'q': 0x14, 'r': 0x15, 's': 0x16, 't': 0x17, 'u': 0x18,
        'v': 0x19, 'w': 0x1a, 'x': 0x1b, 'y': 0x1c, 'z': 0x1d, '1': 0x1e, '2': 0x1f,
        '3': 0x20, '4': 0x21, '5': 0x22, '6': 0x23, '7': 0x24, '8': 0x25, '9': 0x26,
        '0': 0x27, '-': 0x2d, '=': 0x2e, '[': 0x2f, ']': 0x30, '#': 0x32, ';': 0x33,
        "'": 0x34, '`': 0x35, ',': 0x36, '.': 0x37, '/': 0x38, '\\': 0x64,
        # Paragraph control characters
        '\n': 0x28, '\t': 0x2b, '\b': 0x2a, ' ': 0x2c,
    }

    # With modifier (still same scancode for char)
    ascii_to_modifier = {
        'A': 0x04, 'B': 0x05, 'C': 0x06, 'D': 0x07, 'E': 0x08, 'F': 0x09, 'G': 0x0a,
        'H': 0x0b, 'I': 0x0c, 'J': 0x0d, 'K': 0x0e, 'L': 0x0f, 'M': 0x10, 'N': 0x11,
        'O': 0x12, 'P': 0x13, 'Q': 0x14, 'R': 0x15, 'S': 0x16, 'T': 0x17, 'U': 0x18,
        'V': 0x19, 'W': 0x1a, 'X': 0x1b, 'Y': 0x1c, 'Z': 0x1d, '!': 0x1e, '"': 0x1f,
        '£': 0x20, '$': 0x21, '%': 0x22, '^': 0x23, '&': 0x24, '*': 0x25, '(': 0x26,
        ')': 0x27, '_': 0x2d, '+': 0x2e, '{': 0x2f, '}': 0x30, '~': 0x32, ':': 0x33,
        '@': 0x34, '¬': 0x35, '<': 0x36, '>': 0x37, '?': 0x38, '|': 0x64,
    }
    # fmt: on

    try:
        return build_scancode(ascii_to_hid_mapping[ascii_char])
    except KeyError:
        pass

    try:
        return build_scancode(ascii_to_modifier[ascii_char], 0x2)
    except KeyError:
        return build_scancode(0x0)


def build_scancode(byte, modifier=0x0):
    """
    Build a scancode bytes array from a given scancode and modifier
    :param byte:
    :param modifier:
    :return:
    """
    bytes_array = array("B", [b for b in b"\x00" * 8])
    bytes_array[2] = byte
    bytes_array[0] = modifier
    return bytes_array


def merge_scancodes(byte_arrays, max_packet_size=8):
    """
    Merge together a list of scancodes. For example, given the following list:
        byte_arrays = [
            array('B', [1, 0, 4, 0, 0, 0, 0, 0]),
            array('B', [0, 0, 22, 0, 0, 0, 0, 0]),
            array('B', [0, 0, 7, 0, 0, 0, 0, 0]),
            array('B', [2, 0, 5, 0, 0, 0, 0, 0]),
        ]
    Calling merge_scancodes(byte_arrays) should return a packet like:
        array('B', [3, 0, 4, 22, 7, 5, 0, 0])

    Modifier keys will be merged using bitwise OR
    :param byte_arrays:
    :param max_packet_size:
    :return:
    """
    retval = array("B", [b for b in b"\x00" * max_packet_size])
    filled = 2
    for code in byte_arrays:
        # Logical OR any modifiers
        retval[0] = retval[0] | code[0]
        # Pack additional values up to max packet size
        offset = 2
        while code[offset]:  # i.e. !== 0x0
            retval[filled] = code[offset]
            filled += 1
            offset += 1

            if filled >= max_packet_size:
                raise OverflowError("Unable to pack into single packet")

    return retval


def string_to_scancodes(input_string, key_repeat: int = 1, key_up: int = 0):
    """
    Convert a string into a list of scancodes, as if typed
    :param key_repeat: Keyboard keys repeat when held down. Emulate this functionality using param.
    :param key_up: Number of key up signals to insert as scancodes
    :param input_string: The input string to create
    :return: A list of keyboard scancodes (byte arrays)
    """
    scancodes = []

    # Input validation
    if key_repeat < 1 or key_up < 0:
        raise ValueError("key_repeat and key_up should be non-negative integers.")

    # Create list of scancodes from string
    for char in input_string:
        scancodes.append(ascii_to_scancode(char))

    # Duplicate scancodes by the key_repeat parameter
    if key_repeat > 1:
        scancodes = [val for val in scancodes for _ in range(key_repeat)]

    # Insert key-up (full zero) scancodes in-between values, with attention to key_repeat frequency
    if key_up:
        new_scancodes = []
        for i, key in enumerate(scancodes):
            new_scancodes.append(key)
            if i % key_repeat == key_repeat - 1:
                for j in range(key_up):
                    new_scancodes.append(build_scancode(0x0))
        scancodes = new_scancodes

    return scancodes
