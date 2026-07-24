"""PyInstaller spec — Blitztext Python sidecar.

Output:  dist/blitztext-sidecar/blitztext-sidecar.exe + supporting files
         (onedir mode — onefile is too slow to start with torch+pyannote
         and tends to hit antivirus heuristics anyway).

Usage:
    .venv-sidecar\\Scripts\\pyinstaller build-sidecar.spec --noconfirm

Notes:
* All ML dependencies (torch, pyannote.audio, faster-whisper, ...) are
  declared via collect_all so PyInstaller picks up data files (model
  metadata, ONNX runtime DLLs, etc.) on top of the Python modules.
* CUDA DLLs are copied as binaries — without these, torch.cuda fails
  silently on the target machine even if the user has a separate
  CUDA install.
* hidden imports cover lazy-loaded modules that PyInstaller's bytecode
  scan would otherwise miss.
"""

# pylint: disable=undefined-variable

from PyInstaller.utils.hooks import collect_all, collect_submodules
from pathlib import Path

block_cipher = None

datas = []
binaries = []
hiddenimports = []


def _collect(pkg: str) -> None:
    d, b, h = collect_all(pkg)
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)


# --- Heavy ML stack (largest contributor to bundle size) -----------------
for pkg in (
    "torch",
    "torchaudio",
    "faster_whisper",
    "pyannote",
    "pyannote.audio",
    "lightning_fabric",
    "asteroid_filterbanks",
    "huggingface_hub",
    "transformers",
    "tokenizers",
    "soundfile",
    "av",  # PyAV
    "scipy",
    "sklearn",
    "matplotlib",
):
    try:
        _collect(pkg)
    except Exception as exc:
        print(f"[spec] WARN: collect_all({pkg!r}) failed: {exc}")

# Common opaque imports PyInstaller's static scan misses.
hiddenimports.extend(
    [
        "torch._C",
        "torch._C._distributed_c10d",
        "torch.distributed",
        "torch.distributed.elastic",
        "torch.distributed.elastic.multiprocessing.errors",
        "lightning_fabric.utilities.cloud_io",
        "asteroid_filterbanks.scripting",
        "pyannote.audio.tasks",
        "pyannote.audio.pipelines",
        "pyannote.audio.pipelines.speaker_diarization",
        "huggingface_hub.utils._http",
        "av._core",
        "soundfile._soundfile",
        "scipy.special._cdflib",
        "scipy.signal._spline_filters",
        "scipy._lib.array_api_compat.numpy",
        "scipy._lib.array_api_compat.numpy.fft",
    ]
)

# --- Project deps ---------------------------------------------------------
hiddenimports.extend(
    [
        "core.transcription",
        "core.llm",
        "core.log",
        "sidecar",
        "sidecar.rpc",
        "sidecar.methods",
        "sidecar.diarization",
        "sidecar.merger",
        "sidecar.meeting_pipeline",
        "sidecar.meeting_store",
        "sidecar.audio_io",
    ]
)

# --- Analysis ------------------------------------------------------------
a = Analysis(
    ["sidecar/__main__.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Things we definitely don't need; saves ~hundreds of MB.
        "tkinter",
        "PIL.ImageQt",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "IPython",
        "jupyter",
        "notebook",
        "pandas",  # we don't use it; pyannote/speechbrain might pull it though
    ],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="blitztext-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX breaks torch's vendored DLLs.
    console=True,  # The Tauri shell pipes our stdin/stdout — console=True is fine
                   # because the parent grabs the handles and the window never shows.
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="blitztext-sidecar",
)
