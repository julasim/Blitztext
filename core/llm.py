"""LLM-Zugriff für den Sidecar — ausschließlich lokales Ollama.

Übrig geblieben nach dem Rückbau des PyQt-Trays: der Tray schickte Text an
fünf Cloud-Provider (OpenAI/Anthropic/Gemini/OpenRouter/Ollama-Cloud) über
``process_text``. Für Blitztext gilt „alles on-device", also bleibt hier nur
der lokale Pfad. Wer die alten Provider braucht, findet sie in der Historie
(Branch ``main``, vor dem Aufräumen 2026-07-23).

Einziger Konsument: ``cleanup_turn`` — Füllwörter-Bereinigung eines
Sprecher-Turns, aufgerufen aus ``sidecar/methods.py`` (cleanup.run).
"""

import logging

import httpx


OLLAMA_LOCAL_URL = "http://127.0.0.1:11434/api/chat"

#: Vorgabemodell. Am 06.08.2026 an einer echten Bauberatung (69 min, 346
#: Absätze) gegen ``qwen3.5:9b`` gemessen — gleiche Prompts, gleiches
#: Transkript:
#:
#:   gemma4:12b   12:15 min   7.027 Zeichen   Gliederung erhalten,
#:                                            Namensvarianten konsolidiert
#:   qwen3.5:9b    5:44 min  13.650 Zeichen   Gliederung verloren,
#:                                            drei Schreibweisen einer Person
#:
#: Gemma gewinnt bei der Struktur, und die entscheidet über die
#: Brauchbarkeit. Die doppelte Laufzeit fällt nicht ins Gewicht: Das
#: Protokoll läuft als Stapelauftrag nach der Besprechung.
#:
#: **Beide rechnen unzuverlässig** (180 statt 181 m², 10 statt 30 m²). Das
#: ist die Grenze dieser Modellgröße und der Grund für den Warnhinweis über
#: dem Protokoll in der Oberfläche.
OLLAMA_LOCAL_DEFAULT_MODEL = "gemma4:12b"


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


#: Kontextfenster in Token. **Muss gesetzt werden.** Ollama begrenzt sonst
#: still auf rund 2.000 Token und schneidet den Überhang **vorne** ab — die
#: Anfrage meldet Erfolg, das Modell hat den Anfang der Eingabe aber nie
#: gesehen. Gemessen am 06.08.2026: 9.271 Token Eingabe, davon ohne Vorgabe
#: 2.050 verarbeitet; mit Vorgabe 11.992.
#:
#: 8192 ist der Kompromiss für 8 GB VRAM: genug für einen Transkript-
#: Abschnitt, und der KV-Cache sprengt den Speicher noch nicht. Die
#: Zusammenführung vieler Abschnitte braucht mehr und setzt eigens hoch.
OLLAMA_NUM_CTX = 8192


def _call_ollama_local(
    system: str,
    user: str,
    model: str | None = None,
    temperature: float = 0.1,
    timeout: float = 60.0,
    think: bool = False,
    num_ctx: int = OLLAMA_NUM_CTX,
) -> str:
    """Call a local Ollama server and return the assistant message text.

    ``think=False`` schaltet den Reasoning-Modus ab. Das ist kein Detail:
    Modelle wie Qwen 3.5 legen ihren Gedankengang in ein eigenes Feld
    (``message.thinking``) und schreiben die eigentliche Antwort erst
    danach nach ``message.content``. Bei langen Eingaben ist das
    Token-Budget aufgebraucht, bevor die Antwort beginnt — Ollama liefert
    dann HTTP 200 mit **leerem** ``content``. Unsere Aufgaben
    (Zusammenfassen, Glätten) brauchen kein Reasoning; es kostet nur Zeit.
    """
    try:
        r = httpx.post(
            OLLAMA_LOCAL_URL,
            json={
                "model": model or OLLAMA_LOCAL_DEFAULT_MODEL,
                "stream": False,
                "think": think,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "options": {"temperature": temperature, "num_ctx": num_ctx},
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

        # Wurde die Eingabe beschnitten? Ollama sagt es nicht, aber
        # `prompt_eval_count` verrät, wie viele Token wirklich gelesen
        # wurden. Grob ein Token je vier Zeichen — liegt der Wert deutlich
        # darunter, fehlt dem Modell der Anfang der Eingabe.
        gelesen = int(data.get("prompt_eval_count") or 0)
        geschaetzt = (len(system) + len(user)) // 4
        if gelesen and geschaetzt > gelesen * 1.4:
            logging.getLogger("core.llm").warning(
                "Eingabe vermutlich beschnitten: ~%d Token geschickt, %d "
                "verarbeitet (num_ctx=%d). Der Anfang der Eingabe fehlt dem "
                "Modell.", geschaetzt, gelesen, num_ctx,
            )

        message = data.get("message", {})
        content = (message.get("content") or "").strip()
        if not content:
            # Sagen, WORAN es lag: ein leeres content bei gefülltem thinking
            # ist der Reasoning-Fall von oben und hat eine klare Abhilfe.
            if (message.get("thinking") or "").strip():
                raise RuntimeError(
                    f"Ollama lokal: Das Modell hat nur seinen Gedankengang "
                    f"ausgegeben, keine Antwort ({data.get('eval_count', '?')} "
                    f"Token verbraucht). Reasoning-Modelle brauchen "
                    f"`think: false` oder ein größeres Token-Budget."
                )
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

READABLE_SYSTEM_PROMPT = """\
Du machst Meeting-Transkripte lesbar. Der Text stammt aus gesprochener \
Sprache und ist deshalb oft unvollständig interpunktiert.

Erlaubt:
- Füllwörter entfernen: ähm, äh, also, halt, ja halt, eh, nun, tja, ne, gell
- Stotter-Wiederholungen zusammenziehen: "ich ich dachte" → "ich dachte"
- Abgebrochene Satzanfänge entfernen, wenn derselbe Gedanke direkt danach \
ausformuliert wird
- Satzzeichen setzen und Groß-/Kleinschreibung am Satzanfang korrigieren
- Einen abgebrochenen Satz mit den Wörtern zu Ende führen, die im \
Abschnitt bereits stehen — durch Umstellen, NICHT durch Erfinden

Strikt verboten:
- Inhaltliche Wörter ändern, ersetzen oder hinzufügen
- Zahlen, Maße, Normbezeichnungen, Eigennamen, Fachbegriffe anpassen
- Text aus den Kontext-Abschnitten in die Antwort übernehmen
- Aussagen zusammenfassen, deuten oder bewerten
- Kommentare oder Markierungen in die Antwort schreiben

Der Text muss weiterhin belegen, was gesagt wurde — er soll nur ohne \
Stolpern lesbar sein. Im Zweifel weniger ändern.

Gib AUSSCHLIESSLICH den bearbeiteten Abschnitt zurück, nichts davor, \
nichts danach.\
"""

#: Verfügbare Stufen. ``faithful`` ist Default und bleibt es — ein
#: Besprechungsprotokoll kann im Bauverfahren Beleg sein.
CLEANUP_MODES: dict[str, str] = {
    "faithful": CLEANUP_SYSTEM_PROMPT,
    "readable": READABLE_SYSTEM_PROMPT,
}


# --- Sachprotokoll ---------------------------------------------------------
#
# Anderer Zweck als der Cleanup oben: dort wird Satz für Satz geglättet, hier
# wird verdichtet. Gebraucht wird nicht das Wortprotokoll (dafür gibt es die
# Audiodatei), sondern der Sachverhalt — was besprochen wurde, worauf
# hingewiesen wurde, was entschieden wurde.
#
# Zwei Stufen, weil ein einstündiges Gespräch nicht in ein Kontextfenster
# passt und die Qualität mit der Eingabelänge fällt:
#   1. je Abschnitt eine sachliche Zusammenfassung
#   2. aus allen Zusammenfassungen ein Protokoll
#
# Die Regeln sind streng, weil ein Bauprotokoll ein Beleg ist: erfundene
# Zahlen oder verdrehte Zusagen sind schlimmer als eine Lücke.

ABSCHNITT_SYSTEM_PROMPT = """\
Du wertest den Abschnitt eines Besprechungstranskripts aus und hältst fest, \
was sachlich besprochen wurde.

Halte fest, sofern im Abschnitt vorhanden:
- Sachverhalte und Feststellungen (Was liegt vor? Was ist der Stand?)
- Hinweise und Vorbehalte (Worauf wurde aufmerksam gemacht?)
- Entscheidungen (Was wurde festgelegt?)
- Offene Punkte (Was ist ungeklärt? Was fehlt noch?)
- Zusagen mit Verantwortlichen (Wer macht was?)
- Zahlen, Maße, Fristen, Normen, Aktenzeichen — WÖRTLICH übernehmen

Strikt verboten:
- Zahlen, Maße oder Daten verändern, runden oder ergänzen
- SELBST RECHNEN. Übernimm nur Zahlen, die wörtlich genannt werden. Summen, \
Differenzen und Umrechnungen niemals selbst bilden
- Eigennamen oder Fachbegriffe „korrigieren"
- Etwas hinzufügen, das nicht im Abschnitt steht
- Vermutungen anstellen, was gemeint sein könnte
- Bewerten, kommentieren oder Empfehlungen aussprechen
- Deine Überlegungen in die Antwort schreiben („vermutlich…", „Nein: …", \
Fragezeichen hinter eigenen Annahmen). Die Antwort enthält nur Ergebnisse
- Scherze, Übertreibungen und beiläufige Bemerkungen als Sachverhalt \
festhalten. In Besprechungen wird gewitzelt („dann steht die Gemeinde unter \
Wasser") — das gehört NICHT ins Protokoll

Das Transkript ist maschinell erstellt und stellenweise fehlerhaft. Ist eine \
Passage unverständlich, lass sie weg — rate nicht. Wirkt eine Zahl \
offensichtlich verhört, gib sie so wieder wie sie dasteht und schreib \
dahinter: (laut Transkript)

Schreib in knappen Stichpunkten, sachlich, ohne Einleitung und ohne \
Schlusssatz. Enthält der Abschnitt nichts Protokollwürdiges (Begrüßung, \
Small Talk, Suche nach Dateien), antworte nur mit: OHNE INHALT\
"""

RUBRIK_SYSTEM_PROMPT = """\
Du beantwortest EINE bestimmte Frage anhand der Zusammenfassungen einer \
Besprechung. Es geht um einen einzigen Abschnitt eines Protokolls, nicht um \
das ganze Protokoll.

Regeln:
- Antworte NUR auf die gestellte Frage. Alles andere gehört in andere \
Abschnitte und wird hier weggelassen
- Zahlen, Maße, Fristen und Namen unverändert übernehmen
- NIEMALS selbst rechnen. Keine Summen, Differenzen oder Umrechnungen
- Nichts ergänzen, was nicht in den Zusammenfassungen steht
- Widersprechen sich zwei Angaben, beide nennen
- Keine Bewertung, keine Empfehlung, keine Einleitung, kein Schlusswort
- Keine eigenen Überlegungen im Text („vermutlich", „Nein: …")
- Erscheint dieselbe Person in mehreren Schreibweisen, durchgehend die \
häufigste verwenden und keine zweite Person daraus machen
- Scherze und beiläufige Bemerkungen gehören nicht ins Protokoll

Antworte als Markdown-Liste mit `-` je Punkt, ein Punkt je Sachverhalt, in \
vollständigen Sätzen. Keine Überschrift — die setzt die Vorlage.

Findet sich in den Zusammenfassungen nichts zu dieser Frage, antworte nur \
mit: KEINE ANGABEN\
"""


#: Jede Rubrik sieht ALLE Abschnitts-Zusammenfassungen auf einmal. Bei einer
#: Stunde Gespräch sind das schnell 6.000–8.000 Token; mit dem Standardfenster
#: fiele der Anfang der Besprechung weg — und genau dort stehen erfahrungs-
#: gemäß die Grundlagen, auf die sich der Rest bezieht.
PROTOKOLL_NUM_CTX = 16384


def answer_section(
    frage: str,
    summaries_text: str,
    *,
    model: str | None = None,
    timeout: float = 600.0,
    num_ctx: int = PROTOKOLL_NUM_CTX,
) -> str:
    """Eine Protokoll-Rubrik füllen: gezielte Frage → Markdown-Liste.

    Gibt einen leeren String zurück, wenn die Besprechung dazu nichts
    hergibt — die Vorlage lässt die Rubrik dann weg.
    """
    antwort = _call_ollama_local(
        RUBRIK_SYSTEM_PROMPT,
        f"FRAGE: {frage}\n\n--- Zusammenfassungen ---\n{summaries_text}",
        model=model,
        timeout=timeout,
        num_ctx=num_ctx,
    )
    if antwort.strip().upper().startswith("KEINE ANGABEN"):
        return ""
    return antwort


def summarize_section(
    text: str,
    *,
    model: str | None = None,
    timeout: float = 300.0,
) -> str:
    """Stufe 1: ein Gesprächsabschnitt → sachliche Stichpunkte.

    Gibt einen leeren String zurück, wenn der Abschnitt nichts
    Protokollwürdiges enthält.
    """
    antwort = _call_ollama_local(
        ABSCHNITT_SYSTEM_PROMPT, text, model=model, timeout=timeout
    )
    if antwort.strip().upper().startswith("OHNE INHALT"):
        return ""
    return antwort


def cleanup_turn(
    turn_text: str,
    prev_text: str | None = None,
    next_text: str | None = None,
    model: str | None = None,
    timeout: float = 60.0,
    mode: str = "faithful",
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
    mode:
        ``"faithful"`` (Default) entfernt nur Füllwörter und Stotterer.
        ``"readable"`` darf zusätzlich Satzzeichen setzen und einen
        angefangenen Satz zu Ende führen. Beide Stufen ändern **nie** die
        Turn-Struktur — Fragmente zusammenzuführen ist Aufgabe des
        Mergers, sonst zerfielen Sprecherzuordnung und Zeitstempel.

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

    system = CLEANUP_MODES.get(mode)
    if system is None:
        raise ValueError(
            f"Unbekannte Cleanup-Stufe {mode!r}. "
            f"Erlaubt: {', '.join(sorted(CLEANUP_MODES))}"
        )

    result = _call_ollama_local(system, user, model=model, timeout=timeout)
    return result.strip()
