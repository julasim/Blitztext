# -*- mode: python ; coding: utf-8 -*-
# Build with:  pyinstaller build.spec
# Produces:    dist/VoiceType/VoiceType.exe  (+ supporting files)
# Then wrap:   iscc installer/voicetype.iss

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('ui/assets', 'ui/assets'),
    ],
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
    name='VoiceType',
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
    name='VoiceType',             # produces dist/VoiceType/
)
