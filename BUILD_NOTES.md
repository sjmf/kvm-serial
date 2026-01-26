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

# Output location:
# - dist/KVM Serial.app (macOS application bundle)
```

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
- **One-file mode**: All dependencies bundled into single executable
- **Icons**: Platform-specific icons from `assets/` directory
- **Hidden imports**: Explicitly includes PyQt5, OpenCV, serial, pynput
- **Excludes**: Removes tkinter, matplotlib, scipy, pandas to reduce size
- **Console**: Disabled (GUI application)
- **macOS**: Creates .app bundle with Info.plist for permissions

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

### Size too large
The one-file executable will be 150-300MB due to:
- PyQt5 (GUI framework)
- OpenCV (video capture)
- Python runtime

This is normal for PyInstaller builds with these dependencies.

## CI/CD Builds

Automated builds are handled by GitHub Actions:
- Workflow: `.github/workflows/build-binaries.yml`
- Triggers: On version tags (`v*`)
- Platforms: macOS and Windows
- Artifacts: Attached to GitHub releases

See `docs/BUILD.md` for complete build documentation.
