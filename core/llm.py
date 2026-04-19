import httpx

from config.defaults import DEFAULT_PROMPT_MODE2, DEFAULT_PROMPT_MODE3


# Fallback prompts, used only when the caller doesn't pass a prompt in (e.g.
# a test or a plugin bypassing the settings layer). The authoritative source
# is ``config/defaults.py`` → ``DEFAULTS[llm_prompt_modeN]``, which the user
# can edit in the Settings window.
SYSTEM_PROMPTS = {
    2: DEFAULT_PROMPT_MODE2,
    3: DEFAULT_PROMPT_MODE3,
}

TIMEOUT = 30.0


def process_text(
    text: str,
    mode: int,
    provider: str,
    api_key: str,
    model: str,
    system_prompt: str | None = None,
) -> str:
    """Send transcribed text to the selected LLM provider and return the refined text.

    If ``system_prompt`` is provided (non-empty), it overrides the mode's
    built-in fallback prompt. Callers in main.py pass the user-edited prompt
    from the config so the Settings UI has the final word.
    """
    if mode not in SYSTEM_PROMPTS:
        raise ValueError(f"LLM-Modus {mode} wird nicht unterstützt.")

    system_prompt = system_prompt.strip() if system_prompt else ""
    if not system_prompt:
        system_prompt = SYSTEM_PROMPTS[mode]
    provider = (provider or "openrouter").lower()

    if provider == "openai":
        return _call_openai(system_prompt, text, api_key, model)
    if provider == "anthropic":
        return _call_anthropic(system_prompt, text, api_key, model)
    if provider == "gemini":
        return _call_gemini(system_prompt, text, api_key, model)
    if provider == "openrouter":
        return _call_openrouter(system_prompt, text, api_key, model)
    if provider == "ollama":
        return _call_ollama_cloud(system_prompt, text, api_key, model)

    raise RuntimeError(f"Unbekannter Provider: {provider}")


# --- Provider implementations ---

def _require_key(api_key: str, provider_label: str) -> None:
    if not api_key:
        raise RuntimeError(f"Kein API-Key für {provider_label} gesetzt. Bitte in Einstellungen eintragen.")


def _handle_error(response, provider_label: str) -> None:
    if response.status_code == 200:
        return
    if response.status_code == 401:
        raise RuntimeError(f"{provider_label}: API-Key ungültig.")
    if response.status_code == 429:
        raise RuntimeError(f"{provider_label}: Rate-Limit erreicht. Bitte anderes Modell oder später versuchen.")
    try:
        body = response.json()
        msg = body.get("error", {})
        if isinstance(msg, dict):
            msg = msg.get("message", response.text[:200])
    except Exception:
        msg = response.text[:200]
    raise RuntimeError(f"{provider_label}-Fehler ({response.status_code}): {msg}")


def _call_openai(system: str, user: str, api_key: str, model: str) -> str:
    _require_key(api_key, "OpenAI")
    r = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model or "gpt-4o-mini",
            "max_tokens": 1000,
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=TIMEOUT,
    )
    _handle_error(r, "OpenAI")
    try:
        return r.json()["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("OpenAI: Antwort konnte nicht gelesen werden.")


def _call_anthropic(system: str, user: str, api_key: str, model: str) -> str:
    _require_key(api_key, "Anthropic")
    r = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": model or "claude-haiku-4-5",
            "max_tokens": 1000,
            "temperature": 0.3,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=TIMEOUT,
    )
    _handle_error(r, "Anthropic")
    try:
        data = r.json()
        parts = [block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"]
        result = "".join(parts).strip()
        if not result:
            raise RuntimeError("Anthropic: Leere Antwort.")
        return result
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("Anthropic: Antwort konnte nicht gelesen werden.")


def _call_gemini(system: str, user: str, api_key: str, model: str) -> str:
    _require_key(api_key, "Gemini")
    model_name = model or "gemini-2.0-flash"
    r = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent",
        params={"key": api_key},
        headers={"Content-Type": "application/json"},
        json={
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "maxOutputTokens": 1000,
                "temperature": 0.3,
            },
        },
        timeout=TIMEOUT,
    )
    _handle_error(r, "Gemini")
    data = r.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError):
        raise RuntimeError("Gemini: Antwort konnte nicht gelesen werden.")


def _call_openrouter(system: str, user: str, api_key: str, model: str) -> str:
    _require_key(api_key, "OpenRouter")
    r = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model or "google/gemini-2.0-flash-001",
            "max_tokens": 1000,
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=TIMEOUT,
    )
    _handle_error(r, "OpenRouter")
    try:
        return r.json()["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("OpenRouter: Antwort konnte nicht gelesen werden.")


def _call_ollama_cloud(system: str, user: str, api_key: str, model: str) -> str:
    _require_key(api_key, "Ollama Cloud")
    r = httpx.post(
        "https://ollama.com/api/chat",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model or "gpt-oss:20b",
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": 0.3},
        },
        timeout=60.0,
    )
    _handle_error(r, "Ollama Cloud")
    try:
        data = r.json()
        content = data.get("message", {}).get("content", "").strip()
        if not content:
            raise RuntimeError("Ollama Cloud: Leere Antwort.")
        return content
    except (KeyError, TypeError):
        raise RuntimeError("Ollama Cloud: Antwort konnte nicht gelesen werden.")
