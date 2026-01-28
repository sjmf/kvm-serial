# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for KVM Serial GUI application.
Builds a standalone executable for kvm-gui.

Usage:
    pyinstaller kvm-gui.spec

Platforms:
    - macOS: Creates a .app bundle
    - Windows: Creates a .exe executable
    - Linux: Creates a standalone executable
"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect all kvm_serial submodules
hiddenimports = [
    # PyQt5 modules and plugins
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
    'PyQt5.sip',

    # OpenCV modules
    'cv2',
    'numpy',

    # Serial communication
    'serial',
    'serial.tools',
    'serial.tools.list_ports',

    # Input capture
    'pynput',
    'pynput.keyboard',
    'pynput.mouse',

    # Other dependencies
    'screeninfo',
    'toml',

    # KVM serial modules
    'kvm_serial',
    'kvm_serial.kvm',
    'kvm_serial.backend',
    'kvm_serial.backend.video',
    'kvm_serial.backend.keyboard',
    'kvm_serial.backend.mouse',
    'kvm_serial.backend.implementations',
    'kvm_serial.backend.implementations.qtop',
    'kvm_serial.backend.implementations.mouseop',
    'kvm_serial.utils',
    'kvm_serial.utils.settings',
    'kvm_serial.utils.communication',
]

# Collect any data files from kvm_serial package
datas = []

a = Analysis(
    ['kvm_serial/kvm.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={
        # Disable OpenCV's Qt backend to prevent bundling Qt plugins
        # This prevents conflicts with PyQt5's Qt
        'cv2': {
            'backends': ['headless']  # Use headless backend only
        }
    },
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary packages to reduce size
        'tkinter',
        'matplotlib',
        'scipy',
        'pandas',
        'PIL.ImageQt',  # Not needed for our use case
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Remove OpenCV's bundled Qt plugins and libraries to prevent conflicts with PyQt5
# OpenCV bundles its own Qt libraries which conflict with PyQt5's Qt
# This causes "Could not load Qt platform plugin" errors on Linux
# See: https://github.com/sjmf/kvm-serial/issues/12#issuecomment-3808456623

import sys

print("=" * 80, file=sys.stderr)
print("FILTERING cv2 Qt files...", file=sys.stderr)
print("=" * 80, file=sys.stderr)

# Filter out cv2's Qt from datas (includes plugins and other data files)
original_datas_count = len(a.datas)
filtered_datas = []
excluded_datas = []
for dest, src, type_ in a.datas:
    # Skip anything under cv2/qt/ directory (Windows and Unix paths)
    dest_lower = dest.lower().replace('\\', '/')
    if 'cv2/qt/' in dest_lower:
        excluded_datas.append(dest)
        continue
    # Also exclude specific Qt-related files in cv2 root
    if dest_lower.startswith('cv2/') and '/qt' in dest_lower:
        excluded_datas.append(dest)
        continue
    filtered_datas.append((dest, src, type_))

print(f"Filtered {len(excluded_datas)} cv2/qt data files:", file=sys.stderr)
for excluded in excluded_datas[:10]:  # Show first 10
    print(f"  - {excluded}", file=sys.stderr)
if len(excluded_datas) > 10:
    print(f"  ... and {len(excluded_datas) - 10} more", file=sys.stderr)

a.datas = filtered_datas

# Filter out cv2's Qt binaries (shared libraries)
original_binaries_count = len(a.binaries)
filtered_binaries = []
excluded_binaries = []
for dest, src, type_ in a.binaries:
    # Skip cv2 binaries with Qt in the name (case insensitive, handle both path separators)
    dest_lower = dest.lower().replace('\\', '/')
    src_lower = src.lower().replace('\\', '/')

    if dest_lower.startswith('cv2/'):
        if 'qt' in dest_lower or 'qt' in src_lower:
            excluded_binaries.append(dest)
            continue
    filtered_binaries.append((dest, src, type_))

print(f"\nFiltered {len(excluded_binaries)} cv2 Qt binaries:", file=sys.stderr)
for excluded in excluded_binaries[:10]:
    print(f"  - {excluded}", file=sys.stderr)
if len(excluded_binaries) > 10:
    print(f"  ... and {len(excluded_binaries) - 10} more", file=sys.stderr)

a.binaries = filtered_binaries

print(f"\nTotal: removed {original_datas_count - len(filtered_datas)} datas, {original_binaries_count - len(filtered_binaries)} binaries", file=sys.stderr)

# Verify no cv2/qt files remain
cv2_qt_check = [d for d in a.datas if 'cv2/qt' in d[0].lower().replace('\\', '/')]
cv2_qt_check += [b for b in a.binaries if 'cv2/qt' in b[0].lower().replace('\\', '/')]

if cv2_qt_check:
    print("\n" + "!" * 80, file=sys.stderr)
    print("ERROR: cv2/qt files still present after filtering!", file=sys.stderr)
    print("!" * 80, file=sys.stderr)
    for item in cv2_qt_check[:20]:
        print(f"  - {item[0]}", file=sys.stderr)
    print("\n", file=sys.stderr)
    sys.exit(1)
else:
    print("\nSUCCESS: No cv2/qt files detected in build", file=sys.stderr)

print("=" * 80, file=sys.stderr)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Platform-specific build configuration
# macOS: Use onedir mode (recommended and required for PyInstaller 7.0+)
# Windows/Linux: Use onefile mode for simpler distribution
if sys.platform == 'darwin':
    # macOS: onedir mode
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,  # onedir: binaries in separate folder
        name='kvm-gui',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file='assets/entitlements.plist',
        icon='assets/icon.icns',
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='kvm-gui',
    )

    app = BUNDLE(
        coll,
        name='KVM Serial.app',
        icon='assets/icon.icns',
        bundle_identifier='dev.finnigan.kvm-serial',
        info_plist={
            'CFBundleName': 'KVM Serial',
            'CFBundleDisplayName': 'KVM Serial',
            'CFBundleShortVersionString': '1.5.1',
            'CFBundleVersion': '1.5.1',
            'NSHumanReadableCopyright': 'Copyright © 2023-2025 Samantha Finnigan',
            'NSHighResolutionCapable': 'True',
            # Camera and input monitoring permissions
            'NSCameraUsageDescription': 'KVM Serial needs camera access to capture video from the remote machine.',
            'NSMicrophoneUsageDescription': 'KVM Serial does not use the microphone.',
            # Accessibility for keyboard/mouse capture
            'NSAppleEventsUsageDescription': 'KVM Serial needs to capture keyboard and mouse events to control the remote machine.',
        },
    )
else:
    # Windows/Linux: onefile mode
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name='kvm-gui',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon='assets/icon.ico' if sys.platform == 'win32' else None,
    )
