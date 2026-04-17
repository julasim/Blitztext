# VoiceType – Build & Release

Dieses Dokument beschreibt, wie du aus dem Source-Code einen Windows-Installer baust
und als neues Release auf GitHub veröffentlichst.

---

## Einmalige Einrichtung

### 1. GitHub-Repository anlegen

```bash
cd voicetype
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/DEIN-NAME/voicetype.git
git push -u origin main
```

### 2. Repository-Name in `core/updater.py` eintragen

```python
GITHUB_REPO = "DEIN-NAME/voicetype"
```

### 3. Werkzeuge installieren

- **Python 3.11+** mit allen Requirements: `pip install -r requirements.txt`
- **PyInstaller**: `pip install pyinstaller`
- **Inno Setup 6** (Windows-Installer-Builder): <https://jrsoftware.org/isdl.php>
  - Nach der Installation liegt `iscc.exe` in `C:\Program Files (x86)\Inno Setup 6\`
  - Optional in die PATH aufnehmen

---

## Release-Prozess (jedes Mal bei einer neuen Version)

### 1. Version-Bump

In beiden Dateien dieselbe neue Version eintragen:

- `core/updater.py`: `CURRENT_VERSION = "1.1.0"`
- `installer/voicetype.iss`: `#define MyAppVersion "1.1.0"`

### 2. Installer bauen

```bash
# Schritt 1: Python-Code bündeln → dist/VoiceType/
pyinstaller build.spec

# Schritt 2: Installer bauen → dist-installer/VoiceType-Setup-1.1.0.exe
iscc installer/voicetype.iss
```

Ergebnis: `dist-installer/VoiceType-Setup-1.1.0.exe` (~200–300 MB inkl. aller
Python-Dependencies und PyQt6).

> Das Whisper-Modell ist **nicht** im Installer — es wird beim ersten Start der App
> heruntergeladen und in `%APPDATA%\VoiceType\models\` abgelegt. Dadurch bleibt der
> Installer schlank und Modell-Updates sind unabhängig von App-Updates.

### 3. Lokal testen

1. Alte Version deinstallieren (falls vorhanden)
2. Neuen Installer doppelklicken → Installation durchlaufen
3. App startet → Tray-Icon erscheint → kurze Funktionskontrolle
4. Deinstallieren testen → User-Daten-Frage sollte auftauchen

### 4. Code committen & taggen

```bash
git add -A
git commit -m "Release v1.1.0"
git tag v1.1.0
git push origin main --tags
```

### 5. GitHub-Release erstellen

Option A — über die Web-UI:

1. GitHub-Repo → "Releases" → "Draft a new release"
2. Tag: `v1.1.0` auswählen
3. Release-Titel: `v1.1.0`
4. **Beschreibung** = die "Was ist neu"-Liste, die in der App im Update-Fenster erscheint.
   Markdown wird unterstützt. Beispiel:

   ```markdown
   ## Neue Features
   - Unterstützung für Anthropic und Gemini als LLM-Provider
   - Deutlich schnelleres Whisper-Modell (`large-v3-turbo`)
   - Neues minimalistisches Design

   ## Bugfixes
   - API-Key-Verlust nach Provider-Wechsel behoben
   - Clipboard-Race-Condition gefixt
   ```

5. "Attach binaries" → `VoiceType-Setup-1.1.0.exe` hochladen
6. "Publish release"

Option B — per CLI (`gh` GitHub CLI):

```bash
gh release create v1.1.0 \
  dist-installer/VoiceType-Setup-1.1.0.exe \
  --title "v1.1.0" \
  --notes-file RELEASE_NOTES.md
```

### 6. Fertig

Beim nächsten Start von VoiceType bei deinen Usern:

1. Die App fragt die GitHub-Releases-API ab
2. Sie erkennt `1.1.0 > 1.0.0`
3. Ein Update-Dialog erscheint mit Titel, Version, Release Notes
4. Klick auf "Jetzt updaten":
   - Der Installer wird nach `%TEMP%` geladen (Progress-Balken im Dialog)
   - Installer startet im Silent-Modus
   - VoiceType beendet sich selbst
   - Installer ersetzt die Dateien in `Program Files\VoiceType\`
   - Der neue Installer startet die neue VoiceType-Version automatisch

---

## Was die Deinstallation entfernt

**Immer:**
- Alle Programmdateien unter `C:\Program Files\VoiceType\`
- Start-Menü-Eintrag und Desktop-Verknüpfung (falls erstellt)
- Autostart-Registry-Eintrag

**Optional (User wird gefragt):**
- Benutzerdaten unter `%APPDATA%\VoiceType\` (Config + Whisper-Modell ~1,5 GB)
- Alle gespeicherten API-Keys im Windows-Anmeldeinformationsmanager

---

## Troubleshooting

| Problem | Lösung |
|---|---|
| `iscc` nicht gefunden | Inno Setup 6 installieren und `C:\Program Files (x86)\Inno Setup 6\` zur PATH hinzufügen |
| SmartScreen-Warnung beim Installer | Normal, solange der Installer nicht mit Code-Signing-Zertifikat signiert ist. User muss "Weitere Informationen" → "Trotzdem ausführen" klicken |
| Update-Dialog erscheint nicht | Prüfen: `GITHUB_REPO` richtig gesetzt? Release als "Published" (nicht "Draft")? `.exe` als Asset hochgeladen? |
| Installer startet VoiceType nicht automatisch nach Update | Stellen sicher, dass in `voicetype.iss` unter `[Run]` kein `skipifsilent`-Flag gesetzt ist |
