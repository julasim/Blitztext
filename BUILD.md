# Blitztext – Build & Release

Vom Quellcode zum Windows-Installer. Zwei Schritte: erst den Python-Sidecar
bündeln, dann die Tauri-App drumherum bauen.

> Der alte Weg (PyInstaller über `main.py` + Inno Setup) ist mit dem PyQt-Tray
> am 2026-07-23 entfallen. Wer ihn braucht: Branch `main`, Datei `BUILD.md`.

---

## Voraussetzungen

- **Python 3.11** mit eingerichteter `.venv-sidecar` (siehe `README.md`)
- **Rust + MSVC Build Tools**, **Node 20+**
- **WiX Toolset** — holt sich die Tauri-CLI beim ersten `tauri build` selbst

---

## Schritt 1 — Sidecar bündeln

```powershell
.\.venv-sidecar\Scripts\python.exe -m PyInstaller build-sidecar.spec --noconfirm
```

Ergebnis: `dist\blitztext-sidecar\` (~4,8 GB — torch, CUDA-DLLs, pyannote,
faster-whisper). Onedir statt onefile: onefile startet mit diesem Stack zu
langsam und triggert Antiviren-Heuristiken.

Den fertigen Ordner an die Stelle kopieren, an der ihn die Tauri-Config als
Resource erwartet:

```powershell
Copy-Item -Recurse -Force dist\blitztext-sidecar\* app\src-tauri\binaries\sidecar\
```

> `app\src-tauri\binaries\sidecar\` darf **nie leer** sein. Fehlt der Ordner,
> bricht schon `cargo check` am Resource-Glob aus `tauri.conf.json` — mit einer
> Meldung, die nach einem Config-Fehler aussieht. Deshalb liegt dort
> `PLATZHALTER.txt` im Repo; für die Entwicklung genügt der, weil `sidecar.rs`
> im Debug-Build `python -m sidecar` aus der venv startet.

## Schritt 2 — App bauen

```powershell
cd app
npx tauri build
```

Baut das Frontend (`npm run build` läuft als `beforeBuildCommand` mit),
kompiliert die Rust-Shell im Release-Profil und packt alles zu einem
**MSI**-Installer unter `app\src-tauri\target\release\bundle\msi\`.

Sprachen des Installers: `en-US`, `de-DE` (`tauri.conf.json` → `bundle.windows.wix`).

---

## Version anheben

Die Version steht an zwei Stellen und muss gleich sein:

- `app/src-tauri/tauri.conf.json` → `version`
- `app/src-tauri/Cargo.toml` → `package.version`

---

## Vor dem Ausliefern prüfen

1. Installer auf einer Maschine **ohne** `.venv-sidecar` installieren — nur so
   fällt auf, wenn ein Modul nur dank der Dev-venv importierbar war.
2. App starten → Statusleiste muss `sidecar v…` plus `GPU ✓` zeigen.
3. Eine kurze MP3 importieren und bis zum fertigen Transkript durchlaufen lassen.
4. Diktat testen: Strg+Alt+1, sprechen, erneut Strg+Alt+1 → Text landet im
   aktiven Fenster.

Ohne Code-Signing zeigt Windows SmartScreen eine Warnung
(„Weitere Informationen" → „Trotzdem ausführen").

---

## Auto-Update

Nicht eingerichtet. Es gibt weder einen Update-Server noch ein Release-Repo für
diesen Branch — Verteilung läuft manuell über den Installer.
