# GitHub Actions Workflows

This directory contains CI/CD workflows for the KVM Serial project.

## Workflows

### `test.yml` - Continuous Testing
**Triggers:** Push to any branch, pull requests
**Purpose:** Run unit tests and code coverage

- Runs pytest test suite
- Generates coverage reports
- Uploads coverage to Codecov

### `lint.yml` - Code Quality
**Triggers:** Push to any branch, pull requests
**Purpose:** Enforce code style

- Runs Black code formatter check
- Ensures consistent code formatting

### `release.yml` - PyPI Release
**Triggers:** Push to tags matching `v*` (e.g., v1.5.2)
**Purpose:** Publish Python package to PyPI

**Jobs:**
1. **test** - Run full test suite
2. **build-and-publish** - Build and publish to PyPI using OIDC
3. **create-release** - Create GitHub release with auto-generated notes

### `build-binaries.yml` - Executable Builds
**Triggers:** Push to tags matching `v*`, manual dispatch
**Purpose:** Build platform-specific executables and attach to release

**Jobs:**
1. **build-macos** - Build macOS application
   - Runs on: `macos-latest`
   - Output: `KVM Serial.app` (onedir .app bundle)
   - Ad-hoc code signing with entitlements (camera access, PyInstaller compatibility)
   - Creates: ZIP and DMG for distribution
   - Size: ~331 MB

2. **build-windows** - Build Windows executable
   - Runs on: `windows-latest`
   - Output: `kvm-gui.exe` (onefile executable)
   - Creates: ZIP for distribution
   - Size: ~150-200 MB (estimated)

3. **build-linux** - Build Linux AppImage
   - Runs on: `ubuntu-latest`
   - Output: `KVM-Serial-x86_64.AppImage` (portable executable)
   - Creates: Standalone AppImage for distribution
   - Installs PyQt5 system dependencies
   - Size: ~200-250 MB (estimated)

4. **upload-release-assets** - Upload binaries to release
   - Waits for all three builds to complete
   - Downloads all build artifacts
   - Uploads to the GitHub release created by `release.yml`

## Release Process

When you push a version tag (e.g., `v1.5.2`), the following happens automatically:

```
Tag pushed: v1.5.2
├─ release.yml
│  ├─ 1. Run tests
│  ├─ 2. Build Python package
│  ├─ 3. Publish to PyPI
│  └─ 4. Create GitHub Release
│
└─ build-binaries.yml
   ├─ 1. Build macOS app (parallel)
   ├─ 2. Build Windows exe (parallel)
   ├─ 3. Build Linux AppImage (parallel)
   └─ 4. Upload binaries to release
```

**Result:** GitHub release with:
- Auto-generated release notes
- macOS: `KVM-Serial-v1.5.2-macOS.zip` and `.dmg`
- Windows: `KVM-Serial-v1.5.2-Windows.zip`
- Linux: `KVM-Serial-v1.5.2-x86_64.AppImage`

## Manual Testing

You can manually trigger the binary builds workflow:

1. Go to Actions → Build Executable Binaries
2. Click "Run workflow"
3. Select branch
4. Click "Run workflow"

This will build binaries but won't create a release (useful for testing).

## Platform-Specific Notes

### macOS
- Uses onedir mode (PyInstaller 7.0 compatible)
- Creates `.app` bundle with all dependencies in `Contents/Frameworks/`
- DMG creation uses `create-dmg` for professional installer
- Includes proper Info.plist with privacy permissions

### Windows
- Uses onefile mode for simpler distribution
- Single `.exe` file with all dependencies embedded
- Icon embedded in executable
- No console window (GUI mode)

### Linux
- Uses onefile mode with AppImage packaging
- Single portable `.AppImage` file that runs on most distros
- Includes PyQt5 system dependencies (xcb, GL, etc.)
- No installation required - just download, chmod +x, and run
- Compatible with Ubuntu, Fedora, Debian, and derivatives

## Build Requirements

Each platform runner has:
- Python 3.10
- All dependencies from `requirements.txt`
- PyInstaller 6.0+ (from dev dependencies)

## Troubleshooting

### Build fails on macOS
- Check if icon files exist in `assets/`
- Verify `kvm_serial/kvm.py` exists
- Check hidden imports in `kvm-gui.spec`

### Build fails on Windows
- Verify `icon.ico` exists
- Check Windows-specific dependencies
- Ensure `console=False` for GUI mode

### Build fails on Linux
- Check PyQt5 system dependencies are installed
- Verify AppImage tools downloaded successfully
- Ensure `icon.png` exists in `assets/`
- Check AppDir structure creation

### Binaries not attached to release
- Verify `contents: write` permission
- Check artifact upload/download steps
- Ensure tag format matches `v*`

## Security

- PyPI publishing uses OIDC (no API tokens)
- Release creation requires `contents: write` permission
- Workflows only trigger on tags (protected)

### Code Signing

- **macOS**: Builds are ad-hoc signed with entitlements for proper permission handling
  - Entitlements file: `assets/entitlements.plist`
  - Signing command: `codesign --force --deep --sign - --entitlements assets/entitlements.plist "dist/KVM Serial.app"`
  - Ad-hoc signatures work for local testing but not for distribution outside GitHub
- **Windows**: Not currently signed (users will see SmartScreen warnings)
- **Linux**: AppImage format doesn't require code signing

For public distribution, proper certificates are recommended:

- macOS: Apple Developer ID certificate ($99/year for notarization)
- Windows: Code signing certificate (~$100-500/year)

## Future Improvements

- [x] Add Linux builds (AppImage) - ✅ Completed
- [ ] Code signing for macOS (requires Apple Developer account)
- [ ] Code signing for Windows (requires certificate)
- [ ] Automated testing of built executables
- [ ] Build size optimization
