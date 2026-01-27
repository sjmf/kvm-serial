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
    hooksconfig={},
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
