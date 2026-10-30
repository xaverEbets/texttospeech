# Lokales Diktier-Tool (Whisper)

Hotkey drücken, sprechen, Hotkey nochmal drücken. Der erkannte Text wird an der
Cursorposition eingefügt, egal in welchem Programm. Alles läuft lokal, es wird
nichts ins Internet geschickt (außer beim allerersten Download des Modells).

Unterstützt **Windows** und **macOS**.

## Installation

### macOS

1. **Python 3.11 oder neuer** (z.B. von python.org oder via pyenv).
2. Im Projektordner Terminal öffnen und starten:

   ```bash
   chmod +x start.sh
   ./start.sh
   ```

   Beim ersten Start wird die virtuelle Umgebung angelegt und alles installiert.
3. **Rechte freigeben** (sonst reagiert der Hotkey nicht):
   - Systemeinstellungen → Datenschutz & Sicherheit → **Bedienungshilfen**
   - ggf. **Eingabeüberwachung**
   - ggf. **Mikrofon**
   - Dort Terminal, iTerm oder Cursor erlauben.
4. Beenden mit **Ctrl+C**.

### Windows

1. **Python 3.11 oder neuer** installieren von python.org. Beim Installer
   „Add python.exe to PATH“ anhaken.
2. Ordner dieses Projekts öffnen und **`start.bat`** doppelklicken.
3. Danach läuft das Tool in einem Konsolenfenster. Mit **Strg+C** beendet man es.

Das Whisper-Modell wird beim ersten Start heruntergeladen (`small` ≈ 500 MB).

## Menüleisten-App (macOS)

Statt im Terminal läuft das Tool als kleines Icon in der Menüleiste:

```bash
.venv/bin/python menubar.py
```

- Icon: 🎙 bereit, 🔴 Aufnahme, ⏳ lädt/transkribiert, ⚠️ Fehler.
- **Letzte Transkriptionen:** Klick auf einen Eintrag kopiert den Text.
- **Hotkey:** Auswahl im Menü, wird in `config.toml` gespeichert.
- **Beim Login starten:** legt einen LaunchAgent an (`~/Library/LaunchAgents`).
  Log: `~/Library/Logs/diktat.log`.

Die Rechte (Bedienungshilfen, Eingabeüberwachung, Mikrofon) gelten bei Autostart für
die Python-Datei aus `.venv`, nicht für das Terminal. Beim ersten Autostart fragt macOS
ggf. neu danach.

## Benutzung

Standard-Hotkey (siehe `config.toml`):

- **F9** einmal: Aufnahme startet (hoher Piepton).
- Sprechen.
- **F9** nochmal: Aufnahme endet (tiefer Piepton), Text wird transkribiert und
  eingefügt (**Cmd+V** auf dem Mac, **Strg+V** unter Windows).

Unter Windows kannst du in `config.toml` z.B. wieder `key = "right ctrl"` setzen.

## Backends

### 1. CPU (Standard)

`backend = "cpu"` in `config.toml`. Nutzt `faster-whisper` auf dem Prozessor.
Funktioniert ohne Zusatzaufwand, dauert bei `small` etwa 1 bis 3 Sekunden
(auf einem MacBook Air etwas länger bei längeren Aufnahmen).
Für bessere Qualität `model = "medium"` setzen, das ist langsamer.

### 2. whisper.cpp-Server (optional, schneller mit GPU)

Unter Windows z.B. Vulkan (AMD), unter macOS optional Metal.

1. whisper.cpp bauen bzw. Release holen (`github.com/ggml-org/whisper.cpp`).
2. Modell laden, z.B. `ggml-large-v3-turbo.bin`.
3. In `config.toml`:

   ```toml
   [transcription]
   backend = "whisper_cpp"
   [whisper_cpp]
   exe = "/pfad/zu/whisper-server"   # Windows: ...\whisper-server.exe
   model = "/pfad/zu/ggml-large-v3-turbo.bin"
   ```

   Ohne `exe` startet man den Server selbst und das Tool verbindet sich mit `url`.

Ohne Setup bleibt das CPU-Backend die Fallback-Lösung.

## Häufige Probleme

- **Hotkey reagiert nicht (macOS):** Bedienungshilfen / Eingabeüberwachung für
  Terminal oder Cursor freigeben, App neu starten.
- **Hotkey reagiert nicht (Windows):** Tool als Administrator starten.
- **Mikrofon wird nicht gefunden:** `device` in `config.toml` auf einen Teil des
  Gerätenamens setzen, z.B. `"MacBook"` oder `"Headset"`.
- **Kein Text erscheint:** Im Konsolenfenster nachsehen, ob „Kein Text erkannt“
  oder eine Fehlermeldung steht.

## Dateien

- `dictate.py` – Hauptprogramm (Windows + macOS)
- `config.toml` – Einstellungen
- `requirements.txt` – Python-Abhängigkeiten
- `start.sh` – Start unter macOS / Linux
- `start.bat` – Start unter Windows
