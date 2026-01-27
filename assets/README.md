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

## Entitlements

### `entitlements.plist`

macOS entitlements file used during code signing. Required for:

1. **Camera access** - Allows the app to capture video from the remote machine
2. **PyInstaller compatibility** - Allows the bundled Python runtime to work properly:
   - Unsigned executable memory (bootloader requirement)
   - Dynamic library loading (OpenCV, PyQt5, etc.)
   - JIT compilation (NumPy and other numeric libraries)

Used during build:

```bash
codesign --force --deep --sign - --entitlements assets/entitlements.plist "dist/KVM Serial.app"
```

This file is automatically referenced in `kvm-gui.spec` for macOS builds.
