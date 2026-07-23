"""LLM-Zugriff für den Sidecar — ausschließlich lokales Ollama.

Übrig geblieben nach dem Rückbau des PyQt-Trays: der Tray schickte Text an
fünf Cloud-Provider (OpenAI/Anthropic/Gemini/OpenRouter/Ollama-Cloud) über
``process_text``. Für Blitztext gilt „alles on-device", also bleibt hier nur
der lokale Pfad. Wer die alten Provider braucht, findet sie in der Historie
(Branch ``main``, vor dem Aufräumen 2026-07-23).

Einziger Konsument: ``cleanup_turn`` — Füllwörter-Bereinigung eines
Sprecher-Turns, aufgerufen aus ``sidecar/methods.py`` (cleanup.run) und
``sidecar/dictate.py``.
"""

import httpx


OLLAMA_LOCAL_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_LOCAL_DEFAULT_MODEL = "qwen2.5:7b-instruct"


def _handle_error(response, provider_label: str) -> None:
    if response.status_code == 200:
        return
    if response.status_code == 404:
        raise RuntimeError(
            f"{provider_label}: Modell nicht gefunden. Mit `ollama pull "
            f"{OLLAMA_LOCAL_DEFAULT_MODEL}` laden oder anderes Modell wählen."
        )
    try:
        body = response.json()
        msg = body.get("error", {})
        if isinstance(msg, dict):
            msg = msg.get("message", response.text[:200])
    except Exception:
        msg = response.text[:200]
    raise RuntimeError(f"{provider_label}-Fehler ({response.status_code}): {msg}")


def _call_ollama_local(
    system: str,
    user: str,
    model: str | None = None,
    temperature: float = 0.1,
    timeout: float = 60.0,
) -> str:
    """Call a local Ollama server and return the assistant message text."""
    try:
        r = httpx.post(
            OLLAMA_LOCAL_URL,
            json={
                "model": model or OLLAMA_LOCAL_DEFAULT_MODEL,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "options": {"temperature": temperature},
            },
            timeout=timeout,
        )
    except httpx.ConnectError as e:
        raise RuntimeError(
            "Ollama lokal nicht erreichbar (127.0.0.1:11434). "
            "Starte `ollama serve` oder prüfe, ob der Dienst läuft."
        ) from e
    except httpx.TimeoutException as e:
        raise RuntimeError(f"Ollama-Timeout nach {timeout}s.") from e

    _handle_error(r, "Ollama lokal")
    try:
        data = r.json()
        content = data.get("message", {}).get("content", "").strip()
        if not content:
            raise RuntimeError("Ollama lokal: Leere Antwort.")
        return content
    except (KeyError, TypeError) as e:
        raise RuntimeError("Ollama lokal: Antwort konnte nicht gelesen werden.") from e


# --- Turn-Cleanup für Meeting-Transkripte ----------------------------------
#
# Sehr bewusst konservativ: die Aufgabe ist Glättung, NICHT Umformulierung.
# Der Prompt definiert harte Regeln. Bei Zweifelsfällen gibt das Modell
# den Text unverändert zurück.

CLEANUP_SYSTEM_PROMPT = """\
Du bereinigst Meeting-Transkripte. Deine einzige Aufgabe: aus dem markierten \
Abschnitt Füllwörter und unmittelbare Stotter-Wiederholungen entfernen.

Erlaubt zu entfernen:
- Füllwörter: ähm, äh, also, halt, ja halt, eh, nun, tja, ne, gell
- Unmittelbare Stotter-Wiederholungen: "ich ich ich dachte" → "ich dachte"
- Abgebrochene Satzanfänge (false starts), WENN direkt danach derselbe \
Gedanke ausformuliert wird: "ich würde vor- ich würde vorschlagen" → \
"ich würde vorschlagen"

Strikt verboten:
- Inhaltliche Wörter ändern oder ersetzen.
- Wörter hinzufügen, die nicht im Original stehen.
- Satzbau oder Wortreihenfolge ändern.
- Eigennamen, Fachbegriffe, Zahlen anpassen.
- Kommentare, Erklärungen oder Markierungen in die Antwort schreiben.
- Den Sinn einer Aussage verändern.

Wenn nichts zu bereinigen ist, gib den Text wortgleich zurück. Gib \
AUSSCHLIESSLICH den bereinigten Text zurück, nichts davor, nichts danach.\
"""


def cleanup_turn(
    turn_text: str,
    prev_text: str | None = None,
    next_text: str | None = None,
    model: str | None = None,
    timeout: float = 60.0,
) -> str:
    """Bereinigt einen einzelnen Sprecher-Turn via lokales Ollama.

    Parameters
    ----------
    turn_text:
        Der zu bereinigende Text (ein Sprecher-Turn aus dem Transkript).
    prev_text, next_text:
        Nachbar-Turns als Kontext. Werden NICHT bearbeitet, helfen aber
        dem Modell, Anaphern / abgebrochene Sätze zu verstehen.
    model:
        Ollama-Modell-Tag. Default `qwen2.5:7b-instruct`.

    Returns
    -------
    Bereinigter Text. Bei leerem Input: leerer String zurück (kein LLM-Call).
    """
    turn_text = (turn_text or "").strip()
    if not turn_text:
        return ""

    prev_text = (prev_text or "").strip()
    next_text = (next_text or "").strip()

    user = (
        f"Vorheriger Abschnitt (nur Kontext, NICHT bearbeiten):\n"
        f"{prev_text or '(Anfang des Meetings)'}\n"
        f"\n"
        f"Aktueller Abschnitt (diesen bereinigen):\n"
        f"{turn_text}\n"
        f"\n"
        f"Folgender Abschnitt (nur Kontext):\n"
        f"{next_text or '(Ende des Meetings)'}\n"
        f"\n"
        f"Gib NUR den bereinigten aktuellen Abschnitt zurück."
    )

    result = _call_ollama_local(
        CLEANUP_SYSTEM_PROMPT, user, model=model, timeout=timeout
    )
    return result.strip()
