# Lokales Diktier-Tool (Whisper Flow Local)

Hotkey drücken (oder gedrückt halten), sprechen, loslassen – der erkannte Text wird
sofort an der aktuellen Cursorposition eingefügt, egal in welchem Programm.
**100 % lokal, 100 % kostenlos, keine Cloud.**

Optimiert für **Windows (inkl. AMD Radeon RX 7900 XT via Vulkan-GPU)** und **macOS (inkl. Apple Silicon M1/M2/M3/M4 via MLX Metal-GPU)**.

---

## Features

- **⚡ Volle lokale GPU-Beschleunigung (`backend = "auto"`):**
  - **Windows (AMD / NVIDIA / Intel GPU):** Lädt und startet automatisch `whisper.cpp` mit **Vulkan-GPU** und `large-v3-turbo-q8_0` (~0,1 Sekunden Transkriptionszeit auf einer RX 7900 XT).
  - **macOS (MacBook M1/M2/M3/M4):** Nutzt automatisch **`mlx-whisper`** auf der Apple Metal GPU (`whisper-large-v3-turbo-q4`, 4-bit – ~460 MB Download, läuft auch auf 8-GB-MacBooks).
  - **Fallback:** `faster-whisper` (`int8`) auf der CPU, falls keine GPU verfügbar ist.
- **🖥 Desktop-Frontend & System-Tray (`app.py`):**
  - Live-Statusanzeige mit Mikrofon-Pegel & Aufnahme-Timer.
  - **Hotkey frei wählbar:** Per Preset-Dropdown oder per Klick auf **„⌨ Taste aufnehmen …“**.
  - **2 Aufnahme-Modi:**
    - **Toggle:** 1× drücken = Start, nochmal drücken = Stopp & Einfügen.
    - **Push-to-Talk (wie Wispr Flow):** Gedrückt halten zum Sprechen, loslassen zum Einfügen.
  - **Transkript-Verlauf (`history.json`):** Speichert die letzten Transkriptionen dauerhaft – mit Suchfeld und **1-Klick-Kopieren**, falls ein Zielfenster das Einfügen blockiert hat.
  - **Zwischenablage-Sicherheit:** Das letzte Transkript bleibt auch nach dem Einfügen in der Zwischenablage (`Strg+V` / `Cmd+V` jederzeit möglich).
  - **✨ Optionale KI-Nachbearbeitung via OpenRouter (wie Wispr Flow):**
    - Zweistufige Text-Bereinigung:
      1. **Lokaler 0-ms Sofort-Filter:** Entfernt einfache Fülllaute (*„äh“*, *„ähm“*, *„hm“*) und Wortstotterer sofort lokal ohne Internet.
      2. **Optionaler OpenRouter LLM-Layer (per Klick ein-/ausschaltbar):** Bereinigt Füllwörter, Selbstkorrekturen (*„am Dienstag, äh nein, am Donnerstag“*), Rechtschreibung, Groß-/Kleinschreibung und Satzbau in ~0,2–0,3 s (mit TLS-Connection-Warmup bereits während des Sprechens und sofortigem Offline-Fallback auf das lokale Whisper-Transkript).
  - **Autostart im Hintergrund (Windows & macOS):** Direkt per Checkbox **„Autostart (Hintergrund)“** im Frontend (oder im System-Tray-Menü) aktivierbar – startet beim Login unsichtbar im System-Tray bzw. minimiert im Hintergrund, genau wie Wispr Flow.

---

## Schnellstart

### Windows

1. **Python 3.11 oder neuer** installieren (von python.org, „Add python.exe to PATH“ anhaken).
2. **`start.bat`** doppelklicken.
   - Beim ersten Start wird automatisch `.venv` angelegt, die Vulkan-GPU-Engine sowie das `large-v3-turbo`-Modell nach `.cache/whisper_cpp/` geladen und das **Desktop-Frontend + System-Tray-Icon** geöffnet.
   - Schließt man das Fenster über `X`, läuft das Tool leise im Windows-System-Tray weiter.

### macOS (MacBook M2)

1. **Python 3.11 oder neuer** installieren.
2. Im Projektordner starten (oder **`Diktat starten.command`** doppelklicken):

   ```bash
   chmod +x start.sh
   ./start.sh
   ```

   - **`Diktat starten.command`** startet die reine Menüleisten-App unabhängig vom Terminal; das Terminalfenster kann daher geschlossen werden. Startmeldungen und Fehler stehen in `diktat.log`.
   - Alternativ mit dem großen Einstellungsfenster im Terminal starten:
     ```bash
     ./start.sh
     ```
     Die Menüleisten-App lässt sich auch direkt über `./start.sh --menubar` starten.
3. **Rechte freigeben** (einmalig nötig, damit Hotkey & Auto-Paste funktionieren):
   - Systemeinstellungen → Datenschutz & Sicherheit → **Bedienungshilfen**
   - **Eingabeüberwachung**
   - **Mikrofon**

---

## Konfiguration (`config.toml`)

Alle wichtigen Einstellungen (Hotkey, Modus, Mikrofon, Signaltöne) lassen sich direkt im **Desktop-Frontend** ändern und werden automatisch in `config.toml` gespeichert:

```toml
[hotkey]
key = "right ctrl"   # Auf macOS automatisch "right option"
mode = "toggle"      # "toggle" oder "hold" (Push-to-Talk)

[audio]
device = ""
min_seconds = 0.35
sound = true
keep_in_clipboard = true

[transcription]
backend = "auto"     # "auto", "whisper_cpp", "mlx" oder "cpu"
language = "de"
```

---

## Dateien

- `app.py` – Desktop-Frontend (GUI) + System-Tray für Windows & macOS
- `dictate.py` – Kern-Engine (Audio, Hotkeys, Backends, Auto-GPU-Setup, CLI-Modus)
- `menubar.py` – Native macOS-Menüleisten-App (`rumps`)
- `iconography.py` – Icon-Zeichnung (Tray-Status, Fenster-Icon) auf Basis der Menüleisten-SVGs
- `config.toml` – Einstellungen
- `requirements.txt` – Python-Abhängigkeiten
- `start.bat` – Starter für Windows (startet standardmäßig `app.py`, mit `--cli` nur Konsole)
- `start.sh` / `Diktat starten.command` – Starter für macOS
