# Lokales Diktier-Tool (Whisper, Windows)

Hotkey drücken, sprechen, Hotkey nochmal drücken. Der erkannte Text wird an der
Cursorposition eingefügt, egal in welchem Programm. Alles läuft lokal, es wird
nichts ins Internet geschickt (außer beim allerersten Download des Modells).

## Installation

1. **Python 3.11 oder neuer** installieren von python.org. Beim Installer
   „Add python.exe to PATH“ anhaken.
2. Ordner dieses Projekts öffnen und **`start.bat`** doppelklicken.
   Beim ersten Start wird alles automatisch installiert, das dauert ein paar Minuten.
3. Danach läuft das Tool in einem Konsolenfenster. Mit **Strg+C** beendet man es.

Das Whisper-Modell wird beim ersten Start heruntergeladen (`small` ≈ 500 MB).

## Benutzung

- **Rechte Strg-Taste** einmal drücken: Aufnahme startet (hoher Piepton).
- Sprechen.
- **Rechte Strg-Taste** nochmal drücken: Aufnahme endet (tiefer Piepton), der Text
  wird transkribiert und eingefügt.

Taste und andere Einstellungen stehen in **`config.toml`**.

## Backends

### 1. CPU (Standard)

`backend = "cpu"` in `config.toml`. Nutzt `faster-whisper` auf dem Prozessor.
Funktioniert ohne Zusatzaufwand, dauert bei `small` etwa 1 bis 3 Sekunden.
Für bessere Qualität `model = "medium"` setzen, das ist langsamer.

### 2. AMD-Grafikkarte über whisper.cpp und Vulkan (schneller)

Die RX 7900 XT unterstützt kein CUDA, aber whisper.cpp kann sie über **Vulkan** nutzen.

1. Aktuellen AMD-Treiber installieren.
2. whisper.cpp mit Vulkan-Unterstützung besorgen. Entweder ein fertiges Release
   mit Vulkan verwenden oder selbst bauen (Vulkan SDK nötig, CMake mit
   `-DGGML_VULKAN=ON`). Die aktuelle Anleitung steht im Repository
   `github.com/ggml-org/whisper.cpp`.
3. Ein Modell herunterladen, z.B. `ggml-large-v3-turbo.bin`, aus dem Ordner `models` des Repos.
4. In `config.toml`:
   ```toml
   [transcription]
   backend = "whisper_cpp"
   [whisper_cpp]
   exe = "C:\\pfad\\zu\\whisper-server.exe"
   model = "C:\\pfad\\zu\\ggml-large-v3-turbo.bin"
   ```
   Ohne `exe` startet man `whisper-server` selbst und das Tool verbindet sich mit `url`.

Ohne Setup bleibt das CPU-Backend die Fallback-Lösung.

## Häufige Probleme

- **Hotkey reagiert nicht in manchen Programmen:** Das Tool unter Windows als
  Administrator starten. Die Bibliothek `keyboard` braucht dafür manchmal Rechte.
- **Mikrofon wird nicht gefunden:** `device` in `config.toml` auf einen Teil des
  Gerätenamens setzen, z.B. `"Headset"`.
- **Kein Text erscheint:** Im Konsolenfenster nachsehen, ob „Kein Text erkannt“
  oder eine Fehlermeldung steht.

## Dateien

- `dictate.py` – Hauptprogramm
- `config.toml` – Einstellungen
- `requirements.txt` – Python-Abhängigkeiten
- `start.bat` – Startet das Tool, richtet beim ersten Mal die Umgebung ein
