# KVM Serial Application Assets

This directory contains application icons and branding assets for the KVM Serial application.

## Icon Files

- `icon.png` - Main icon (1024x1024)
- `icon.ico` - Windows icon format (multi-resolution)
- `icon.icns` - macOS icon format (multi-resolution)
- `icon_*.png` - Individual PNG sizes for various uses

## Regenerating Icons

To regenerate the icon files, run:

```bash
python create_icon.py
iconutil -c icns icon.iconset  # macOS only
```

## Requirements

- Python 3.10+
- Pillow (PIL): `pip install pillow`
- iconutil (macOS built-in, for .icns generation)
