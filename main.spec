# -*- mode: python ; coding: utf-8 -*-
import sys
import os

# Fix "__file__ is not defined" error (compatible with PyInstaller)
if '__file__' not in locals():
    __file__ = sys.argv[0]
# Get project root (spec file directory)
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
# Add project root and src to Python path (critical for module finding)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

block_cipher = None

a = Analysis(
    ['src/main.py'],  # Entry file (correct path)
    pathex=[
        PROJECT_ROOT, 
        os.path.join(PROJECT_ROOT, 'src')  # Specify src root for flat folders
    ],
    binaries=[],
    # ******** KEY FIX: Flat folders under src (data_sources/visualization) ********
    datas=[
        (os.path.join(PROJECT_ROOT, 'src/data_sources'), 'src/data_sources'),
        (os.path.join(PROJECT_ROOT, 'src/visualization'), 'src/visualization'),
        (os.path.join(PROJECT_ROOT, 'src/core'), 'src/core'),  # Optional: package core if needed
    ],
    hiddenimports=[
        # Exact module path (flat under src)
        'src.data_sources',
        'src.data_sources.base',
        'src.data_sources.DataProcessing',
        'src.data_sources.data_saver',
        'src.data_sources.manager',
        'src.data_sources.serial_source',
        'src.data_sources.udp_source',
        'src.visualization',
        'src.visualization.waveform_widget',
        'src.core',  # Optional: add core if used in main.py
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Fix Qt plugin missing (avoid exe crash on Windows)
qt_plugins_path = os.path.join(os.path.dirname(sys.executable), 'Lib', 'site-packages', 'PyQt5', 'Qt5', 'plugins')
if os.path.exists(qt_plugins_path):
    a.datas += [
        (os.path.join(qt_plugins_path, 'platforms', 'qwindows.dll'), 'PyQt5/Qt5/plugins/platforms'),
    ]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Python上位机',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # Disable UPX (avoid Qt binary corruption)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Keep console to check runtime errors (disable after success)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)