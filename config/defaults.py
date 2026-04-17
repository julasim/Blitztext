DEFAULTS = {
    "version": "1.0.0",
    "hotkey_mode1": "ctrl+alt+1",
    "hotkey_mode2": "ctrl+alt+2",
    "hotkey_mode3": "ctrl+alt+3",
    "whisper_model": "small",
    "language": "de",
    "llm_provider": "openrouter",
    "llm_model": "google/gemini-2.0-flash-001",
    "start_with_windows": True,
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
