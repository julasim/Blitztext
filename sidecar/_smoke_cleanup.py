"""Smoke-Test für cleanup_turn gegen ein lokales Ollama.
Einmalig von Hand laufen lassen: python -m sidecar._smoke_cleanup
"""

from __future__ import annotations

import sys
import time

# Projekt-Root in sys.path damit 'core.llm' gefunden wird.
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.llm import cleanup_turn  # noqa: E402


CASES = [
    {
        "name": "Klassischer Ähm-Turn mit Stotter-Wiederholung",
        "prev": "Ich würde sagen, wir fangen mit den Brandschutz-Themen an.",
        "turn": (
            "Ja also ähm, ich ich dachte, wir könnten, ähm, den Fluchtweg halt "
            "über den Ost-Innenhof führen, weil das ist halt ne, der kürzeste "
            "Weg zum Treppenhaus und äh entspricht auch der OIB Richtlinie 2."
        ),
        "next": "Das sehe ich auch so.",
    },
    {
        "name": "False-Start, dann ausformuliert",
        "prev": None,
        "turn": (
            "Also die Statik, die Statik wurde, ähm, also Herr Müller hat "
            "die Vorbemessung schon eingereicht, aber wir warten noch auf "
            "die Nachberechnung für den Dachträger."
        ),
        "next": "Wann kommt die?",
    },
    {
        "name": "Saubere Aussage - sollte unverändert bleiben",
        "prev": "Was ist mit der Baueingabe?",
        "turn": "Die ist am Freitag rausgegangen. Antwort erwarte ich in zwei Wochen.",
        "next": "Gut.",
    },
    {
        "name": "Fachbegriffe und Zahlen müssen exakt bleiben",
        "prev": None,
        "turn": (
            "Also ähm der U-Wert der Fassade liegt bei 0,18 Watt pro "
            "Quadratmeter Kelvin, halt nach ÖNORM B 8110-1 Tabelle 4, "
            "und eh das ist unter dem Zielwert."
        ),
        "next": None,
    },
]


def main() -> int:
    print(f"Testing cleanup_turn against local Ollama...\n")
    for i, c in enumerate(CASES, 1):
        print(f"=== CASE {i}: {c['name']} ===")
        print(f"  ORIGINAL ({len(c['turn'])} chars):")
        print(f"    {c['turn']}")
        t0 = time.time()
        try:
            cleaned = cleanup_turn(c["turn"], c["prev"], c["next"])
        except Exception as e:
            print(f"  ERROR: {e}")
            return 1
        dt = time.time() - t0
        print(f"  CLEANED ({len(cleaned)} chars, {dt:.1f}s):")
        print(f"    {cleaned}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
