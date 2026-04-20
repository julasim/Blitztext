# -*- mode: python ; coding: utf-8 -*-
# Build with:  pyinstaller build.spec
# Produces:    dist/Blitztext/Blitztext.exe  (+ supporting files)
# Then wrap:   iscc installer/blitztext.iss

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# faster_whisper ships asset files (e.g. silero_vad_v6.onnx) that must travel
# with the bundle; PyInstaller doesn't detect them automatically.
_fw_data = collect_data_files("faster_whisper")

# piper-tts bundles espeak-ng-data (phoneme tables per language) and a few
# runtime assets. Without these the Piper TTS voice fails to initialise on
# the user's installed .exe even though it works in dev.
_piper_data = collect_data_files("piper")
_onnx_data = collect_data_files("onnxruntime")

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('ui/assets', 'ui/assets'),
    ] + _fw_data + _piper_data + _onnx_data,
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
        # SAPI TTS: pyttsx3 lazy-loads its Windows driver via importlib,
        # so PyInstaller can't auto-discover these.
        'pyttsx3',
        'pyttsx3.drivers',
        'pyttsx3.drivers.sapi5',
        'pywintypes',
        'pythoncom',
        'win32com',
        'win32com.client',
        # Piper neural TTS + onnxruntime. collect_submodules pulls every
        # piper.* / onnxruntime.* submodule the lazy loader might reach for.
        'piper',
        'onnxruntime',
    ] + collect_submodules("piper") + collect_submodules("onnxruntime"),
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
