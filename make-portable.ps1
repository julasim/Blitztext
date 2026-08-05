# Stellt den portablen Blitztext-Ordner zusammen.
#
# Warum portabel und kein Installer: der Sidecar bringt torch mit CUDA mit
# (~4,7 GB nach Ballast-Abzug). MSI scheitert daran hart — das CAB-Format
# kann keine 2 GB pro Paket —, und NSIS bräuchte eine halbe Stunde
# Kompression für ein Ergebnis, das sich schlechter verteilen lässt als ein
# Ordner auf dem NAS.
#
# Voraussetzung: `python -m PyInstaller build-sidecar.spec --noconfirm` und
# `cd app; npx tauri build --no-bundle` sind gelaufen.
#
# Aufruf:  .\make-portable.ps1

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$version = (Get-Content "$root\app\src-tauri\tauri.conf.json" | ConvertFrom-Json).version
$out = "$root\release\Blitztext-$version-portable"

$appExe = "$root\app\src-tauri\target\release\blitztext.exe"
$sidecar = "$root\dist\blitztext-sidecar"

foreach ($p in @($appExe, $sidecar)) {
    if (-not (Test-Path $p)) { throw "Fehlt: $p — erst bauen (siehe BUILD.md)" }
}

if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force $out | Out-Null

Write-Host "Kopiere Anwendung …"
Copy-Item $appExe "$out\Blitztext.exe"

# Der Sidecar muss unter binaries/sidecar/ neben der EXE liegen — genau
# dort sucht ihn sidecar.rs über resource_dir() im Release-Build.
Write-Host "Kopiere Sidecar (das dauert, mehrere GB) …"
$target = "$out\binaries\sidecar"
New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item "$sidecar\*" $target -Recurse -Force

@"
Blitztext $version — portabel
=============================

Starten: Blitztext.exe doppelklicken.

Beim ersten Start lädt die App die Sprachmodelle herunter (Whisper
~3 GB, pyannote ~30 MB) nach %APPDATA%\Blitztext\models. Danach
arbeitet sie offline. Rechne beim ersten Lauf mit ein paar Minuten.

Voraussetzung für die Sprecher-Trennung: ein HuggingFace-Token mit
akzeptierten Bedingungen für
  pyannote/speaker-diarization-community-1
Einzutragen in der App unter Einstellungen.

Der Ordner darf verschoben und kopiert werden — es gibt keine
Registry-Einträge und keine Installation. Zum Entfernen genügt es,
den Ordner zu löschen; Daten liegen unter %APPDATA%\Blitztext.
"@ | Set-Content "$out\LIESMICH.txt" -Encoding UTF8

$size = (Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
Write-Host ""
Write-Host ("Fertig: $out  ({0:N1} GB)" -f $size)
Write-Host "Zum Verteilen den ganzen Ordner auf den NAS legen."
