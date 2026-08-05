# Messaufbau

Beantwortet eine Frage: **wird es auf unserem Material besser?**

Modellvergleiche im Netz messen überwiegend englische Benchmarks. Für eine
österreichische Bauberatung mit Dialekt, Fachbegriffen und Kreuzreden sagen
sie wenig. Hier läuft dieselbe Aufnahme durch den echten Produktpfad und
wird gegen ein von Hand korrigiertes Transkript gerechnet.

## Einmal einrichten

1. **Aufnahmen nach `data/` legen.** 3–5 Stück reichen. Wichtiger als Länge
   ist Vielfalt: eine mit klarem Wechselgespräch, eine mit Kreuzreden, eine
   mit starkem Dialekt, eine mit vielen Fachbegriffen. 5–10 Minuten je
   Aufnahme genügen.

2. **Referenz-Gerüst erzeugen** — die Pipeline läuft einmal und schreibt
   ihr Ergebnis als Vorlage:

   ```powershell
   .\.venv-sidecar\Scripts\python.exe benchmark\run.py --prepare benchmark\data\besprechung.mp3
   ```

3. **`besprechung.reference.md` im Editor korrigieren.** Falsche Wörter
   richtigstellen, Sprechernamen vergeben, falsch zugeordnete Absätze
   verschieben. Der Kopfbereich (Titel, Datum, Sprecherliste) wird beim
   Messen ignoriert und darf stehenbleiben.

   Korrigieren statt abtippen — das ist der ganze Trick an diesem Format.

## Messen

```powershell
.\.venv-sidecar\Scripts\python.exe benchmark\run.py --label baseline-large-v3
.\.venv-sidecar\Scripts\python.exe benchmark\run.py --label turbo --model large-v3-turbo
.\.venv-sidecar\Scripts\python.exe benchmark\run.py --label ohne-diarization --no-diarize
```

Jeder Lauf schreibt nach `results/` eine JSON (alle Details) und eine
Markdown-Zusammenfassung (zum Überfliegen). In beiden stehen torch- und
pyannote-Version — sonst weiß in vier Wochen niemand mehr, ob eine Messung
vor oder nach einem Stack-Wechsel lief.

## Ohne eigenes Material prüfen

```powershell
.\.venv-sidecar\Scripts\python.exe benchmark\run.py --selftest
```

### Synthetischer Testsatz

`make_testset.py` erzeugt aus den deutschen Windows-Stimmen einen
Mehrsprecher-Testsatz mit **bekanntem** Wortlaut und bekannter
Sprecherzahl — er schreibt MP3 und Referenz selbst, aus dem Drehbuch:

```powershell
.\.venv-sidecar\Scripts\python.exe benchmark\make_testset.py
```

Landet in `data/synthetic/` (gitignored, jederzeit neu erzeugbar). Auf
diesem Satz beruhen alle Stack-Vergleiche dieser Codebasis.

**Nie `--prepare` auf `data/synthetic/` laufen lassen** — das würde die
Pipeline-Ausgabe zur Referenz machen und den Vergleich zum Zirkelschluss.

Wichtige Grenze: TTS-Stimmen klingen unnatürlich gleichmäßig, die
Sprechertrennung hat es damit leichter als in einem echten Raum. Der
Testsatz ist ein **Regressionsmelder** („ist etwas schlechter geworden?"),
kein Qualitätsurteil („ist es gut genug?"). Deshalb trägt jede
Ergebniszeile daraus das Flag `"synthetic": true`.

Lässt die Windows-Sprachausgabe einen Satz mit bekanntem Wortlaut sprechen,
kodiert ihn nach MP3 und schickt ihn durch die volle Kette. Beweist, dass
der Messaufbau funktioniert, bevor eine vertrauliche Aufnahme angefasst
wird. Erwartetes WER: nahe null.

## Was gemessen wird

| Kennzahl | Bedeutung |
|---|---|
| **WER** | Wortfehlerrate nach Normalisierung (klein, ohne Satzzeichen, Bindestrich = Leerzeichen). Die Hauptzahl. |
| **WER roh** | Ohne Normalisierung. Der Abstand zur normalisierten Zahl zeigt, wie viel reine Schreibweise ist. |
| **Schleifen** | Anteil der Wörter in unmittelbaren Wiederholungen („servus servus servus…"). **Braucht keine Referenz** — damit die einzige Zahl, die auch auf unkorrigiertem Material trägt. Whispers klassischer Halluzinationsfehler. |
| **S / D / I** | Ersetzungen, Löschungen, Einfügungen. Viele Einfügungen deuten auf Halluzinationen in Stille, viele Löschungen auf verschluckte Passagen. |
| **Sprecher** | Erkannte gegen echte Anzahl. |
| **RTF** | Realtime-Faktor: Audiosekunden je Rechensekunde. Höher ist schneller. |

**Zahlen werden bewusst nicht normalisiert.** „12" und „zwölf" gelten als
verschieden — bei Normnummern, Fristen und Kosten ist das ein echter Fehler
und kein Formatierungsdetail.

**Keine DER.** Eine saubere Diarization Error Rate braucht Referenzsegmente
mit exakten Ende-Zeitstempeln. Unsere Referenz hat nur Startzeiten; die
Enden aus dem nächsten Start zu schätzen ergäbe eine Zahl, die nach
Präzision aussieht und keine hat. `pyannote.metrics` liegt in der venv —
wenn es je echte RTTM-Referenzen gibt, lässt sich DER nachrüsten.

## Datenschutz

`data/`, `results/` und `.work/` sind gitignored. Die Messläufe fassen die
produktive Meeting-DB nicht an: `run.py` biegt `APPDATA` auf `.work/` um,
bevor irgendetwas aus `sidecar/` importiert wird.
