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

from PyInstaller.utils.hooks import collect_all
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
    # onnx_asr bringt die NeMo-Preprocessor-Gewichte als Datendateien mit
    # (nemo80.onnx u.a.). Ohne collect_all findet PyInstaller nur den
    # Modulcode — Parakeet bricht dann erst auf der Zielmaschine ab.
    "onnx_asr",
    "pyannote",
    "pyannote.audio",
    "lightning_fabric",
    "asteroid_filterbanks",
    "huggingface_hub",
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
#
# Jedes Modul, das NUR function-local importiert wird, muss hier stehen —
# PyInstaller sieht solche Importe beim Bytecode-Scan nicht. Das trifft auf
# fast alles zu, weil der Sidecar-Start bewusst schlank gehalten ist.
hiddenimports.extend(
    [
        "core.transcription",
        "core.parakeet",  # nur in meeting_pipeline._get_transcriber importiert
        "core.llm",
        "core.log",
        "sidecar",
        "sidecar.rpc",
        "sidecar.methods",
        "sidecar.jobs",  # nur in methods.queue_* importiert
        "sidecar.diarization",
        "sidecar.merger",
        "sidecar.protocol",  # nur in methods.protocol_generate importiert
        "sidecar.protokoll_vorlage",  # nur in protocol.fuelle_vorlage
        "sidecar.vokabular_bau",  # nur in methods.settings_vocabulary_suggestion
        "sidecar.meeting_pipeline",
        "sidecar.meeting_store",
        "sidecar.audio_io",
        # Engine von Parakeet — lädt seine Backends dynamisch.
        "onnx_asr",
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
        # ACHTUNG: `pandas` darf hier NICHT stehen. Es sah nach totem Gewicht
        # aus („wir nutzen es nicht"), aber `pyannote.database.util` importiert
        # es auf Modulebene — und diese Datei liegt in der Importkette von
        # `pyannote.audio`. Mit dem Ausschluss ließ sich pyannote im gepackten
        # Sidecar nicht laden: die Sprechertrennung fiel still aus, jedes
        # Transkript hatte genau einen Sprecher, und die Meldung im Log
        # behauptete „pyannote.audio ist nicht installiert". Genau so ist die
        # 0.2.0 ausgeliefert worden.
    ],
    noarchive=False,
)

# --- Ballast raus ---------------------------------------------------------
#
# collect_all("torch") nimmt das komplette Paket mit, auch die Teile, die
# nur zum KOMPILIEREN gegen torch gebraucht werden: statische Bibliotheken
# (.lib, allein dnnl.lib ist 2,2 GB), C++-Header und Typ-Stubs. Zur
# Laufzeit lädt niemand davon etwas. Zusammen 2,7 GB von 7,4 — das
# entscheidet darüber, ob sich das Paket überhaupt noch bündeln lässt.
_DEAD_WEIGHT = (".lib", ".h", ".hpp", ".pdb", ".cmake", ".pyi")


def _is_build_only(dest: str) -> bool:
    lowered = dest.lower()
    return lowered.endswith(_DEAD_WEIGHT)


_before = len(a.datas) + len(a.binaries)
a.datas = [entry for entry in a.datas if not _is_build_only(entry[0])]
a.binaries = [entry for entry in a.binaries if not _is_build_only(entry[0])]
print(f"[spec] Nicht-Laufzeit-Dateien entfernt: {_before - len(a.datas) - len(a.binaries)}")

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
