# Build Notes for KVM Serial

This document provides quick reference for building executables locally.

## Prerequisites

- Python 3.10+
- All dependencies from `requirements.txt` installed
- Development dependencies (includes PyInstaller):
  - Using pip: `pip install -e ".[dev]"`

## Building Locally

### macOS

```bash
# Activate your virtual environment
source .venv/bin/activate  # or conda activate ch9329

# Build the application
pyinstaller kvm-gui.spec

# Sign with ad-hoc signature (required for proper permissions handling)
codesign --force --deep --sign - --entitlements assets/entitlements.plist "dist/KVM Serial.app"

# Verify signature
codesign --verify --verbose "dist/KVM Serial.app"

# Output location:
# - dist/KVM Serial.app (macOS application bundle)
```

**Note:** Ad-hoc signing (using `-` as identity) is sufficient for local testing and allows the app to properly request camera permissions. For distribution, you'll need a proper Apple Developer certificate.

### Windows

```bash
# Activate your virtual environment
.venv\Scripts\activate

# Build the application
pyinstaller kvm-gui.spec

# Output location:
# - dist\kvm-gui.exe (Windows executable)
```

### Linux

```bash
# Activate your virtual environment
source .venv/bin/activate

# Build the application
pyinstaller kvm-gui.spec

# Output location:
# - dist/kvm-gui (Linux executable)
```

## Testing the Build

### macOS

```bash
# Run the built application
open "dist/KVM Serial.app"

# Or from command line
./dist/KVM\ Serial.app/Contents/MacOS/kvm-gui
```

### Windows

```bash
# Run the executable
dist\kvm-gui.exe
```

### Linux

```bash
# Make executable (if needed)
chmod +x dist/kvm-gui

# Run it
./dist/kvm-gui
```

## Build Configuration

The build is configured in `kvm-gui.spec`:

- **Build mode**:
  - macOS: onedir mode (required for PyInstaller 7.0+)
  - Windows/Linux: onefile mode for simpler distribution
- **Icons**: Platform-specific icons from `assets/` directory
- **Hidden imports**: Explicitly includes PyQt5, OpenCV, serial, pynput
- **Excludes**: Removes tkinter, matplotlib, scipy, pandas to reduce size
- **Console**: Disabled (GUI application)
- **macOS**:
  - Creates .app bundle with Info.plist for camera/input permissions
  - Includes entitlements file (`assets/entitlements.plist`) for:
    - Camera access
    - PyInstaller runtime compatibility (JIT, unsigned memory, library loading)

## Troubleshooting

### Missing modules error

If you get "ModuleNotFoundError" when running the built executable:

1. Add the missing module to `hiddenimports` in `kvm-gui.spec`
2. Rebuild with `pyinstaller kvm-gui.spec`

### Icon not showing

- Verify icon files exist in `assets/` directory
- Check `icon` parameter in spec file points to correct file

### Application won't start

- Run from terminal to see error messages
- Check that all dependencies are installed in your build environment

### macOS: App hangs on permission prompt

If the macOS app hangs when requesting camera access:

1. The app likely wasn't code signed with entitlements
2. Rebuild and sign the app:

   ```bash
   pyinstaller kvm-gui.spec
   codesign --force --deep --sign - --entitlements assets/entitlements.plist "dist/KVM Serial.app"
   ```

3. If permissions were previously denied, reset them:

   ```bash
   tccutil reset Camera dev.finnigan.kvm-serial
   ```

**Why this happens:** macOS requires apps to be code signed (even with ad-hoc signatures) to properly handle permission dialogs. Without signing, the permission callback system can fail, causing hangs.

### Size too large

The one-file executable will be 150-300MB due to:

- PyQt5 (GUI framework)
- OpenCV (video capture)
- Python runtime

This is normal for PyInstaller builds with these dependencies.

## CI/CD Builds

Automated builds are handled by GitHub Actions:

- Workflow: `.github/workflows/build-binaries.yml`
- Triggers: On version tags (`v*`) or manual dispatch
- Platforms: macOS, Windows, and Linux
- Build artifacts:
  - macOS: `KVM-Serial-{version}-macOS.zip` and `.dmg` (ad-hoc signed)
  - Windows: `KVM-Serial-{version}-Windows.zip`
  - Linux: `KVM-Serial-{version}-x86_64.AppImage`
- Artifacts: Automatically attached to GitHub releases

### Code Signing Status

- **macOS**: Ad-hoc signed in CI (sufficient for testing, not for distribution)
- **Windows**: Not signed (users will see SmartScreen warnings)
- **Linux**: AppImage format doesn't require signing

For public distribution, proper code signing certificates are needed:

- macOS: Apple Developer ID ($99/year)
- Windows: Code signing certificate (~$100-500/year)

See `.github/workflows/README.md` for detailed workflow documentation.
