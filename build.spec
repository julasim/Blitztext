# -*- mode: python ; coding: utf-8 -*-
# Build with:  pyinstaller build.spec
# Produces:    dist/Blitztext/Blitztext.exe  (+ supporting files)
# Then wrap:   iscc installer/blitztext.iss

from PyInstaller.utils.hooks import collect_data_files

# faster_whisper ships asset files (e.g. silero_vad_v6.onnx) that must travel
# with the bundle; PyInstaller doesn't detect them automatically.
_fw_data = collect_data_files("faster_whisper")

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('ui/assets', 'ui/assets'),
    ] + _fw_data,
    hiddenimports=[
        'faster_whisper',
        'sounddevice',
        'keyboard',
        'pyperclip',
        'pyautogui',
        'keyring',
        'keyring.backends.Windows',
        'numpy',
        'httpx',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,        # <-- key change: don't bundle into single file
    name='Blitztext',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                # --windowed: no console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='ui/assets/icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Blitztext',             # produces dist/Blitztext/
)
