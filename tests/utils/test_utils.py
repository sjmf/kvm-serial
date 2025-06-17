"""Tests for utility functions in utils.py"""

import pytest
from array import array
from kvm_serial.utils.utils import (
    scancode_to_ascii,
    ascii_to_scancode,
    build_scancode,
    merge_scancodes,
    string_to_scancodes,
)


class TestScancodeToAscii:
    def test_basic_keys(self):
        """Test basic letter conversions"""
        # Test a few basic letters
        assert scancode_to_ascii(array("B", [0, 0, 0x04, 0, 0, 0, 0, 0])) == "a"
        assert scancode_to_ascii(array("B", [0, 0, 0x05, 0, 0, 0, 0, 0])) == "b"
        assert scancode_to_ascii(array("B", [0, 0, 0x1A, 0, 0, 0, 0, 0])) == "w"

    def test_shifted_keys(self):
        """Test shift-modified keys"""
        # Test with left shift modifier (0x02)
        assert scancode_to_ascii(array("B", [0x02, 0, 0x04, 0, 0, 0, 0, 0])) == "A"
        assert scancode_to_ascii(array("B", [0x02, 0, 0x05, 0, 0, 0, 0, 0])) == "B"
        # Test with right shift modifier (0x20)
        assert scancode_to_ascii(array("B", [0x20, 0, 0x1A, 0, 0, 0, 0, 0])) == "W"

    def test_special_chars(self):
        """Test special characters and symbols"""
        assert scancode_to_ascii(array("B", [0, 0, 0x2D, 0, 0, 0, 0, 0])) == "-"
        assert scancode_to_ascii(array("B", [0x02, 0, 0x2D, 0, 0, 0, 0, 0])) == "_"
        assert scancode_to_ascii(array("B", [0, 0, 0x2C, 0, 0, 0, 0, 0])) == " "

    def test_invalid_scancode(self):
        """Test invalid scancode returns None"""
        assert scancode_to_ascii(array("B", [0, 0, 0xFF, 0, 0, 0, 0, 0])) is None

    def test_raise_error(self):
        """Test invalid scancode returns None"""
        with pytest.raises(KeyError):
            scancode_to_ascii(array("B", [0, 0, 0xFF, 0, 0, 0, 0, 0]), raise_err=True)

    # TODO: Test multiple keydowns before keyup

class TestAsciiToScancode:
    def test_basic_letters(self):
        """Test basic letter conversions"""
        expected = array("B", [0, 0, 0x04, 0, 0, 0, 0, 0])
        assert ascii_to_scancode("a") == expected

        expected = array("B", [0, 0, 0x1A, 0, 0, 0, 0, 0])
        assert ascii_to_scancode("w") == expected

    def test_capital_letters(self):
        """Test capital letter conversions (with shift modifier)"""
        expected = array("B", [0x2, 0, 0x04, 0, 0, 0, 0, 0])
        assert ascii_to_scancode("A") == expected

        expected = array("B", [0x2, 0, 0x1A, 0, 0, 0, 0, 0])
        assert ascii_to_scancode("W") == expected

    def test_special_chars(self):
        """Test special character conversions"""
        # Test space
        expected = array("B", [0, 0, 0x2C, 0, 0, 0, 0, 0])
        assert ascii_to_scancode(" ") == expected

        # Test newline
        expected = array("B", [0, 0, 0x28, 0, 0, 0, 0, 0])
        assert ascii_to_scancode("\n") == expected

    def test_invalid_char(self):
        """Test invalid character returns zero scancode"""
        expected = array("B", [0, 0, 0, 0, 0, 0, 0, 0])
        assert ascii_to_scancode("€") == expected


class TestBuildScancode:
    def test_basic_scancode(self):
        """Test building basic scancode"""
        expected = array("B", [0, 0, 0x04, 0, 0, 0, 0, 0])
        assert build_scancode(0x04) == expected

    def test_with_modifier(self):
        """Test building scancode with modifier"""
        expected = array("B", [0x02, 0, 0x04, 0, 0, 0, 0, 0])
        assert build_scancode(0x04, 0x02) == expected


class TestMergeScancodes:
    def test_basic_merge(self):
        """Test basic merging of scancodes"""
        scancodes = [
            array("B", [1, 0, 4, 0, 0, 0, 0, 0]),
            array("B", [0, 0, 22, 0, 0, 0, 0, 0]),
            array("B", [0, 0, 7, 0, 0, 0, 0, 0]),
        ]
        expected = array("B", [1, 0, 4, 22, 7, 0, 0, 0])
        assert merge_scancodes(scancodes) == expected

    def test_merge_with_modifiers(self):
        """Test merging scancodes with modifiers"""
        scancodes = [
            array("B", [1, 0, 4, 0, 0, 0, 0, 0]),
            array("B", [0, 0, 22, 0, 0, 0, 0, 0]),
            array("B", [0, 0, 7, 0, 0, 0, 0, 0]),
            array("B", [2, 0, 5, 0, 0, 0, 0, 0]),
        ]
        expected = array("B", [3, 0, 4, 22, 7, 5, 0, 0])
        assert merge_scancodes(scancodes) == expected

    def test_overflow_error(self):
        """Test that overflow of max_packet_size raises an error"""
        scancodes = [array("B", [i for i in range(1, 32)])]
        with pytest.raises(OverflowError):
            merge_scancodes(scancodes, max_packet_size=8)


class TestStringToScancodes:
    def test_basic_string(self):
        """Test basic string conversion"""
        result = string_to_scancodes("ab")
        expected = [
            array("B", [0, 0, 0x04, 0, 0, 0, 0, 0]),
            array("B", [0, 0, 0x05, 0, 0, 0, 0, 0]),
        ]
        assert result == expected

    def test_with_key_repeat(self):
        """Test string conversion with key repeat"""
        result = string_to_scancodes("a", key_repeat=2)
        expected = [
            array("B", [0, 0, 0x04, 0, 0, 0, 0, 0]),
            array("B", [0, 0, 0x04, 0, 0, 0, 0, 0]),
        ]
        assert result == expected

    def test_with_key_up(self):
        """Test string conversion with key up signals"""
        result = string_to_scancodes("a", key_up=1)
        expected = [
            array("B", [0, 0, 0x04, 0, 0, 0, 0, 0]),
            array("B", [0, 0, 0x00, 0, 0, 0, 0, 0]),
        ]
        assert result == expected

    def test_invalid_params(self):
        """Test invalid parameters raise ValueError"""
        with pytest.raises(ValueError):
            string_to_scancodes("a", key_repeat=0)
        with pytest.raises(ValueError):
            string_to_scancodes("a", key_up=-1)
