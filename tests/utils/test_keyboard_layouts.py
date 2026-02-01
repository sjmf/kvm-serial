"""
Unit tests for keyboard layout functionality.
"""

import pytest
from kvm_serial.utils.keyboard_layouts import (
    get_layout,
    get_available_layouts,
    BASE_LAYOUT,
    LAYOUT_OVERRIDES,
)


class TestKeyboardLayouts:
    """Test keyboard layout selection and mapping."""

    def test_get_available_layouts(self):
        """Test that available layouts are returned correctly."""
        layouts = get_available_layouts()
        assert isinstance(layouts, list)
        assert len(layouts) >= 2
        assert "en_GB" in layouts
        assert "en_US" in layouts
        # Layouts should be sorted
        assert layouts == sorted(layouts)

    def test_get_layout_en_gb(self):
        """Test getting en_GB layout returns base layout."""
        layout = get_layout("en_GB")
        assert isinstance(layout, dict)
        # Should have all base mappings
        assert layout["a"] == 0x04
        assert layout["@"] == 0x34
        assert layout['"'] == 0x1F
        assert layout["#"] == 0x32
        assert layout["£"] == 0x20
        assert layout["¬"] == 0x35

    def test_get_layout_en_us(self):
        """Test getting en_US layout with overrides applied."""
        layout = get_layout("en_US")
        assert isinstance(layout, dict)
        # Should have overridden mappings
        assert layout["a"] == 0x04  # Same as base
        assert layout['"'] == 0x34  # US override
        assert layout["@"] == 0x1F  # US override
        assert layout["#"] == 0x20  # US override
        # Should not have unavailable characters
        assert "£" not in layout
        assert "¬" not in layout

    def test_layout_base_unchanged(self):
        """Test that getting a layout doesn't modify BASE_LAYOUT."""
        original_base = BASE_LAYOUT.copy()
        get_layout("en_US")
        assert BASE_LAYOUT == original_base

    def test_invalid_layout(self):
        """Test that requesting invalid layout raises ValueError."""
        with pytest.raises(ValueError) as excinfo:
            get_layout("invalid_layout")
        assert "Unknown keyboard layout" in str(excinfo.value)

    def test_layout_mappings_are_complete(self):
        """Test that all layouts have valid HID scan codes."""
        for layout_name in get_available_layouts():
            layout = get_layout(layout_name)
            # All values should be positive integers (HID scan codes)
            for char, scancode in layout.items():
                assert isinstance(scancode, int)
                assert 0 <= scancode <= 0xFF

    def test_common_characters_available(self):
        """Test that common ASCII characters are available in all layouts."""
        common_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        for layout_name in get_available_layouts():
            layout = get_layout(layout_name)
            for char in common_chars:
                assert char in layout, f"Character '{char}' missing from {layout_name}"

    def test_us_layout_differences(self):
        """Test that US layout correctly overrides UK layout differences."""
        en_gb = get_layout("en_GB")
        en_us = get_layout("en_US")

        # Quote and at sign should be swapped
        assert en_gb['"'] != en_us['"']
        assert en_gb["@"] != en_us["@"]

        # Hash should be different (US is 0x20, UK is 0x32 but outputs £)
        assert en_gb["#"] == 0x32
        assert en_us["#"] == 0x20

        # Pound and not sign should not exist in US
        assert "£" in en_gb
        assert "£" not in en_us
        assert "¬" in en_gb
        assert "¬" not in en_us


class TestCharacterMappings:
    """Test specific character mappings for correctness."""

    def test_digit_mappings_consistent(self):
        """Test that digit mappings are same across layouts."""
        en_gb = get_layout("en_GB")
        en_us = get_layout("en_US")

        for digit in "0123456789":
            assert en_gb[digit] == en_us[digit]

    def test_lowercase_letter_mappings_consistent(self):
        """Test that lowercase letters are same across layouts."""
        en_gb = get_layout("en_GB")
        en_us = get_layout("en_US")

        for letter in "abcdefghijklmnopqrstuvwxyz":
            assert en_gb[letter] == en_us[letter]

    def test_uppercase_letter_mappings_consistent(self):
        """Test that uppercase letters are same across layouts."""
        en_gb = get_layout("en_GB")
        en_us = get_layout("en_US")

        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            assert en_gb[letter] == en_us[letter]

    def test_control_characters_available(self):
        """Test that control characters are available."""
        for layout_name in get_available_layouts():
            layout = get_layout(layout_name)
            assert "\n" in layout
            assert "\t" in layout
            assert "\b" in layout
            assert " " in layout
