# Blitztext – Build & Release

Vom Quellcode zum verteilbaren Ordner. Drei Schritte: Sidecar bündeln,
App bauen, portables Paket zusammenstellen.

> Der alte Weg (PyInstaller über `main.py` + Inno Setup) ist mit dem PyQt-Tray
> am 2026-07-23 entfallen. Wer ihn braucht: Branch `main`, Datei `BUILD.md`.

## Warum portabel und kein Installer

Der Sidecar bringt torch mit CUDA mit — **~4,7 GB**, auch nach Abzug allen
Ballasts. Daran scheitern die üblichen Installer-Formate:

- **MSI ist chancenlos.** Das CAB-Format kann keine 2 GB pro Paket;
  `light.exe` bricht ab (verifiziert am 2026-08-05).
- **NSIS könnte, will man aber nicht.** Eine halbe Stunde LZMA-Kompression
  für ein Ergebnis, das sich schlechter verteilen lässt als ein Ordner.

Ein portabler Ordner umgeht beides, lässt sich über den NAS verteilen und
hinterlässt keine Registry-Spuren. `tauri.conf.json` behält `nsis` als Ziel
für den Tag, an dem der Sidecar klein genug ist.

---

## Voraussetzungen

- **Python 3.11** mit eingerichteter `.venv-sidecar` (siehe `README.md`)
- **Rust + MSVC Build Tools**, **Node 20+**

---

## Schritt 1 — Sidecar bündeln

```powershell
.\.venv-sidecar\Scripts\python.exe -m PyInstaller build-sidecar.spec --noconfirm
```

Ergebnis: `dist\blitztext-sidecar\` (~4,7 GB — torch, CUDA-DLLs, pyannote,
faster-whisper, onnx-asr). Onedir statt onefile: onefile startet mit diesem
Stack zu langsam und triggert Antiviren-Heuristiken.

Die Spec wirft am Ende alles raus, was nur zum **Kompilieren** gegen torch
gebraucht wird — statische Bibliotheken, C++-Header, Typ-Stubs. Das sind
2,7 GB, allein `dnnl.lib` ist 2,2 GB groß. Zur Laufzeit lädt davon niemand
etwas.

> **Nur function-local importierte Module müssen in `hiddenimports`.**
> PyInstaller sieht sie beim Bytecode-Scan nicht. Pakete mit Datendateien
> brauchen zusätzlich `collect_all` — bei `onnx_asr` sind das die
> NeMo-Preprocessor-Gewichte, ohne die Parakeet erst auf der Zielmaschine
> abbricht.

## Schritt 2 — App bauen

```powershell
cd app
npx tauri build --no-bundle
```

Baut das Frontend (`npm run build` läuft als `beforeBuildCommand` mit) und
kompiliert die Rust-Shell im Release-Profil zu
`app\src-tauri\target\release\blitztext.exe`. `--no-bundle` überspringt den
Installer-Schritt, der an der Größe scheitern würde.

> `app\src-tauri\binaries\sidecar\` darf **nie leer** sein. Fehlt der Ordner,
> bricht schon `cargo check` am Resource-Glob aus `tauri.conf.json` — mit einer
> Meldung, die nach einem Config-Fehler aussieht. Deshalb liegt dort
> `PLATZHALTER.txt` im Repo; für die Entwicklung genügt der, weil `sidecar.rs`
> im Debug-Build `python -m sidecar` aus der venv startet.

## Schritt 3 — Portables Paket

```powershell
.\make-portable.ps1
```

Legt `release\Blitztext-<version>-portable\` an: `Blitztext.exe`, daneben
`binaries\sidecar\` und eine `LIESMICH.txt` für die Empfänger. Genau dort
sucht `sidecar.rs` den Sidecar über `resource_dir()`.

Zum Verteilen den ganzen Ordner auf den NAS legen.

---

## Version anheben

Die Version steht an **vier** Stellen und muss überall gleich sein:

- `app/src-tauri/tauri.conf.json` → `version`
- `app/src-tauri/Cargo.toml` → `package.version`
- `app/package.json` → `version`
- `sidecar/rpc.py` → `__version__` — das ist die Zahl, die die **Statusleiste
  der App** anzeigt

`tests/test_rpc.py::test_versionen_stimmen_ueberein` vergleicht alle vier und
schlägt bei Drift fehl. Der Test entstand, weil die Statusleiste noch
`0.1.0-alpha` zeigte, als 0.2.0 längst ausgeliefert war.

---

## Vor dem Ausliefern prüfen

1. **Den portablen Ordner auf eine Maschine ohne `.venv-sidecar` kopieren**
   und dort `Blitztext.exe` starten — nur so fällt auf, wenn ein Modul nur
   dank der Dev-venv importierbar war. (Ersatzweise auf demselben Rechner:
   Ordner an einen anderen Ort kopieren und von dort starten.)
2. App starten → Statusleiste muss `sidecar v…` plus `GPU ✓` zeigen. Die
   Versionsnummer dort muss die des Releases sein.
3. Eine kurze MP3 mit **Whisper** importieren und bis zum fertigen Transkript
   durchlaufen lassen.
4. Dieselbe Datei mit **Parakeet** importieren. Eigener Prüfpunkt, weil
   Parakeet über einen zweiten Runtime-Pfad läuft (ONNX statt CTranslate2)
   und seine Preprocessor-Gewichte als Datendateien mitkommen müssen —
   fehlt dort etwas, bricht es erst auf der Zielmaschine ab.
5. **Sprechertrennung prüfen:** Das fertige Transkript muss mehr als einen
   Sprecher zeigen, und im Meeting darf **kein** Hinweis „Ohne
   Sprechertrennung transkribiert" stehen. Dieser Punkt fehlte bis
   2026-08-05 — deshalb ging ein Paket raus, in dem pyannote gar nicht lud
   und jedes Transkript stillschweigend einen einzigen Sprecher hatte.
   Gegenprobe im Log: `%APPDATA%\Blitztext\sidecar.log` muss
   `preload complete (device=…)` enthalten, nicht `preload failed`.
6. Einen Ordner mit mehreren Dateien ziehen → Warteschlange arbeitet sie
   nacheinander ab, Abbrechen funktioniert.
7. **Sachprotokoll erzeugen** (Ollama muss laufen). Eigener Prüfpunkt, weil
   `sidecar.protocol` und `sidecar.protokoll_vorlage` **function-local**
   importiert werden — PyInstaller sieht solche Importe beim Bytecode-Scan
   nicht, und ein fehlender Eintrag in `hiddenimports` fällt erst hier auf,
   nie im Dev-Modus. Im Ergebnis muss der Kopf (Titel, Datum, Teilnehmer)
   stehen **und** der Zahlen-Anhang gefüllt sein.
8. **Einstellungen → „Bau-Vokabular einfügen"** drücken: Das Feld muss sich
   füllen (`sidecar.vokabular_bau`, ebenfalls function-local). Speichern ist
   für die Abnahme nicht nötig.

Ohne Code-Signing zeigt Windows SmartScreen eine Warnung
(„Weitere Informationen" → „Trotzdem ausführen").

---

## Auto-Update

Nicht eingerichtet. Es gibt weder einen Update-Server noch ein Release-Repo für
diesen Branch — verteilt wird der portable Ordner von Hand (NAS, USB).
