# --- Default LLM system prompts for modes 2, 3 and 5 ---
# These are editable in Settings; the defaults below are what the app ships
# with and also the values the "Auf Standard zurücksetzen"-button restores.

DEFAULT_PROMPT_MODE2 = (
    "Du bist ein Textassistent. Der User hat folgenden Text gesprochen. Bereinige ihn: "
    "Entferne Füllwörter (äh, ähm, halt, sozusagen), korrigiere offensichtliche "
    "Versprecher, vervollständige abgebrochene Sätze. Der Ton bleibt locker und "
    "natürlich. Gib NUR den bereinigten Text zurück, keine Erklärungen."
)

DEFAULT_PROMPT_MODE3 = (
    "Du bist ein professioneller Texter. Der User hat folgenden Text gesprochen. "
    "Formuliere ihn als professionellen, förmlichen Text um – geeignet für E-Mails "
    "oder geschäftliche Nachrichten. Behalte den Kerninhalt bei. "
    "Gib NUR den umformulierten Text zurück, keine Erklärungen."
)

DEFAULT_PROMPT_MODE5 = (
    "Du bist ein Assistent für Obsidian-Notizen. Der User hat seine Gedanken "
    "frei diktiert. Formatiere sie als gut lesbare Notiz für Obsidian in Markdown.\n\n"
    "REGELN:\n"
    "- Entscheide SELBST, ob Fließtext (ganze Sätze) oder Stichpunkte "
    "(- Liste) passender sind – je nach Inhalt. Strukturierte Aufzählungen "
    "→ Stichpunkte. Zusammenhängende Ideen → Fließtext. Beides mischen ist "
    "erlaubt, wenn es den Inhalt klarer macht.\n"
    "- Nutze Markdown: `## Überschrift` wenn sinnvoll, **fett** für "
    "Schlüsselbegriffe, `Code` für Befehle / Pfade / Dateinamen, > für Zitate.\n"
    "- Erkenne und korrigiere typische Transkriptionsfehler bei Tech-Begriffen: "
    "Anthropic, Claude, Claude Code, GPT, GPT-4, GPT-5, OpenAI, Gemini, "
    "LLM, API, SDK, MCP, Obsidian, Cursor, VS Code, Python, TypeScript, "
    "JavaScript, Markdown, Whisper, Ollama, OpenRouter, HuggingFace, "
    "GitHub, Docker, Kubernetes, PyQt, npm, Node.js.\n"
    "- Entferne Füllwörter (äh, ähm, halt, sozusagen, also) und korrigiere "
    "offensichtliche Versprecher.\n"
    "- Behalte den Kerninhalt – erfinde nichts dazu.\n"
    "- KEINE Meta-Einleitung (kein 'Hier ist deine Notiz…'). Gib NUR die "
    "formatierte Notiz zurück."
)


DEFAULTS = {
    "version": "1.0.0",
    "hotkey_mode1": "ctrl+alt+1",
    "hotkey_mode2": "ctrl+alt+2",
    "hotkey_mode3": "ctrl+alt+3",
    # Mode 4 = TTS (read selected / clipboard text aloud)
    "hotkey_mode4": "ctrl+alt+4",
    # Mode 5 = Obsidian note formatting (LLM decides prose vs bullet points)
    "hotkey_mode5": "ctrl+alt+5",
    "whisper_model": "medium",
    "language": "de",
    "llm_provider": "openrouter",
    "llm_model": "google/gemini-2.0-flash-001",
    "start_with_windows": True,
    # User-editable system prompts for the LLM modes.
    "llm_prompt_mode2": DEFAULT_PROMPT_MODE2,
    "llm_prompt_mode3": DEFAULT_PROMPT_MODE3,
    "llm_prompt_mode5": DEFAULT_PROMPT_MODE5,
    # TTS settings — provider pattern mirrors llm_provider so we can add
    # Edge TTS / OpenAI TTS later without restructuring.
    "tts_provider": "sapi",        # sapi | (future: edge, openai)
    "tts_voice": "",               # empty = pick first SAPI voice matching `language`
    "tts_rate": 0,                 # -10 .. +10, 0 = engine default
}


# Suggested default models per provider (used as placeholders)
PROVIDER_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5",
    "gemini": "gemini-2.0-flash",
    "openrouter": "google/gemini-2.0-flash-001",
    "ollama": "gpt-oss:20b",
}

PROVIDER_LABELS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
    "openrouter": "OpenRouter",
    "ollama": "Ollama Cloud",
}


# Whisper models available in the settings dropdown.
# Order: fastest → highest quality.
WHISPER_MODELS = [
    ("small",            "Schnell (500 MB)"),
    ("medium",           "Ausgewogen (1,5 GB)"),
    ("large-v3-turbo",   "Höchste Qualität (1,6 GB)"),
]


# ---------------------------------------------------------------------------
# TTS providers
# ---------------------------------------------------------------------------

TTS_PROVIDER_LABELS = {
    "sapi":  "Windows (SAPI)",
    "piper": "Piper (neuronal, offline)",
}


# Piper voices live on HuggingFace under rhasspy/piper-voices. Each voice
# is a ``.onnx`` model + ``.onnx.json`` config; we download both on first
# use to %APPDATA%\Blitztext\voices\. The URLs below link directly to the
# raw files so we don't need the HF API.
_PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE"

PIPER_VOICES = {
    "de_DE-thorsten-medium": {
        "label":     "Thorsten (männlich, empfohlen)",
        "size_mb":   63,
        "onnx_url":  f"{_PIPER_BASE}/thorsten/medium/de_DE-thorsten-medium.onnx",
        "json_url":  f"{_PIPER_BASE}/thorsten/medium/de_DE-thorsten-medium.onnx.json",
    },
    "de_DE-kerstin-low": {
        "label":     "Kerstin (weiblich, schnell)",
        "size_mb":   30,
        "onnx_url":  f"{_PIPER_BASE}/kerstin/low/de_DE-kerstin-low.onnx",
        "json_url":  f"{_PIPER_BASE}/kerstin/low/de_DE-kerstin-low.onnx.json",
    },
    "de_DE-eva_k-x_low": {
        "label":     "Eva K. (weiblich, sehr klein)",
        "size_mb":   15,
        "onnx_url":  f"{_PIPER_BASE}/eva_k/x_low/de_DE-eva_k-x_low.onnx",
        "json_url":  f"{_PIPER_BASE}/eva_k/x_low/de_DE-eva_k-x_low.onnx.json",
    },
}

# Sensible defaults per provider so the settings UI can auto-pick when the
# user switches provider for the first time.
TTS_DEFAULT_VOICE = {
    "sapi":  "",                          # empty → SAPI's first voice matching the UI language
    "piper": "de_DE-thorsten-medium",
}
