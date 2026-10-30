"""Lokales Diktier-Tool fuer Windows und macOS.

Hotkey einmal druecken: Aufnahme startet.
Hotkey nochmal druecken: Aufnahme endet, Whisper wandelt das Audio in Text um,
und der Text wird an der aktuellen Cursorposition eingefuegt.
"""

import io
import os
import platform
import re
import subprocess
import sys
import threading
import time
import tomllib
import urllib.parse
import wave
from collections import deque
from pathlib import Path

# Der Xet-Transfer von Hugging Face haengt bei manchen Setups ohne Ausgabe bei 0 Bytes.
# Normaler HTTP-Download ist robust und zeigt echten Fortschritt. Muss gesetzt sein,
# bevor huggingface_hub importiert wird.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

import numpy as np
import pyperclip
import requests
import sounddevice as sd

# Auf macOS braucht "keyboard" Root-Rechte, daher dort Quartz (Event-Tap, nur Rechte-Freigabe).
# pynput scheidet aus: es ruft Tastatur-Layout-Funktionen ausserhalb des Hauptthreads auf und
# stuerzt damit in einer Menueleisten-App ab.
if sys.platform == "darwin":
    import Quartz
else:
    import keyboard

# Whisper erwartet 16 kHz, daher ist die Rate fest und nicht in der Config.
SAMPLE_RATE = 16000
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"
PASTE_HOTKEY = "ctrl+v"  # nur Windows; auf macOS wird Cmd+V ueber Quartz gesendet


def beep(freq, duration_ms):
    """Kurzer Signalton. Laeuft im Hintergrund, damit nichts blockiert."""

    def _play():
        try:
            if IS_MAC:
                # Eigener Prozess statt PortAudio, damit der Ton nie mit dem Mikrofon-Stream kollidiert.
                sound = "Tink" if freq >= 800 else "Pop" if freq >= 500 else "Basso"
                subprocess.run(["afplay", f"/System/Library/Sounds/{sound}.aiff"], timeout=5)
                return
            if IS_WINDOWS:
                import winsound

                winsound.Beep(freq, duration_ms)
                return

            # macOS/Linux: kurzen Sinuston ueber PortAudio spielen.
            duration = max(duration_ms, 1) / 1000.0
            t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
            tone = (0.2 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
            sd.play(tone, SAMPLE_RATE, blocking=True)
        except Exception:
            pass

    threading.Thread(target=_play, daemon=True).start()


def to_wav_bytes(samples):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)  # int16
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(samples.tobytes())
    return buffer.getvalue()


def download_model_with_progress(name):
    """Modell von Hugging Face holen, mit sichtbarem Fortschrittsbalken im Terminal.

    faster-whisper unterdrueckt die Balken selbst, daher rufen wir snapshot_download
    direkt mit denselben Dateimustern auf. Bereits geladene Dateien werden wiederverwendet,
    abgebrochene Downloads setzen fort.
    """
    from faster_whisper.utils import _MODELS
    from huggingface_hub import snapshot_download

    repo_id = name if "/" in name else _MODELS.get(name)
    if repo_id is None:
        raise ValueError(f"Unbekanntes Modell in config.toml: {name}")

    print(f"Pruefe Modell '{name}' ({repo_id}) ...")
    return snapshot_download(
        repo_id,
        allow_patterns=[
            "config.json",
            "preprocessor_config.json",
            "model.bin",
            "tokenizer.json",
            "vocabulary.*",
        ],
    )


class CpuBackend:
    """faster-whisper, laeuft auf dem Prozessor."""

    def __init__(self, cfg):
        from faster_whisper import WhisperModel

        self.language = cfg["transcription"]["language"] or None
        model_path = download_model_with_progress(cfg["cpu"]["model"])
        print("Modell geladen, initialisiere ...")
        self.model = WhisperModel(
            model_path,
            device="cpu",
            compute_type=cfg["cpu"]["compute_type"],
        )

    def transcribe(self, samples):
        audio = samples.astype(np.float32) / 32768.0
        segments, _ = self.model.transcribe(
            audio, language=self.language, beam_size=1, vad_filter=True
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


class WhisperCppBackend:
    """whisper.cpp als HTTP-Server (z.B. Vulkan unter Windows, Metal unter macOS)."""

    def __init__(self, cfg):
        wcfg = cfg["whisper_cpp"]
        self.language = cfg["transcription"]["language"]
        self.base_url = wcfg["url"].rstrip("/")
        self.server = None

        if wcfg.get("exe"):
            self.server = self._start_server(wcfg)
            self._wait_until_ready()
        else:
            print(f"Erwarte einen laufenden whisper.cpp-Server unter {self.base_url}")

    def _start_server(self, wcfg):
        port = urllib.parse.urlparse(self.base_url).port or 8080
        command = [
            wcfg["exe"],
            "-m",
            wcfg["model"],
            "-l",
            self.language or "auto",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ]
        print("Starte whisper.cpp-Server ...")
        return subprocess.Popen(command)

    def _wait_until_ready(self):
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                requests.get(self.base_url, timeout=2)
                print("whisper.cpp-Server ist bereit.")
                return
            except requests.ConnectionError:
                time.sleep(1)
        raise RuntimeError(f"whisper.cpp-Server unter {self.base_url} antwortet nicht.")

    def transcribe(self, samples):
        files = {"file": ("audio.wav", to_wav_bytes(samples), "audio/wav")}
        data = {"language": self.language, "response_format": "json"}
        response = requests.post(
            f"{self.base_url}/inference", files=files, data=data, timeout=120
        )
        response.raise_for_status()
        return response.json().get("text", "").strip()


def create_backend(cfg):
    kind = cfg["transcription"]["backend"]
    if kind == "cpu":
        return CpuBackend(cfg)
    if kind == "whisper_cpp":
        return WhisperCppBackend(cfg)
    raise ValueError(f"Unbekanntes Backend in config.toml: {kind}")


def resolve_input_device(device_cfg):
    """Leer = Standardgeraet. Sonst Teil des Geraetenamens (case-insensitive)."""
    if not device_cfg:
        return None
    needle = str(device_cfg).lower()
    try:
        devices = sd.query_devices()
    except Exception as exc:
        print(f"Audiogeraete konnten nicht gelesen werden: {exc}")
        return None
    for index, info in enumerate(devices):
        if info.get("max_input_channels", 0) <= 0:
            continue
        if needle in str(info.get("name", "")).lower():
            print(f"Mikrofon: {info['name']} (Index {index})")
            return index
    print(f"Kein Mikrofon mit '{device_cfg}' gefunden, nutze Standardgeraet.")
    return None


def paste_text(text):
    """Text per Zwischenablage einfuegen und die alte Zwischenablage wiederherstellen."""
    try:
        previous = pyperclip.paste()
    except pyperclip.PyperclipException:
        previous = None

    pyperclip.copy(text)
    time.sleep(0.05)
    if IS_MAC:
        for key_down in (True, False):
            event = Quartz.CGEventCreateKeyboardEvent(None, MAC_KEYCODE_V, key_down)
            Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
    else:
        keyboard.send(PASTE_HOTKEY)
    time.sleep(0.5)  # Dem Zielprogramm Zeit geben, bevor die alte Zwischenablage zurueckkommt.

    if previous is not None:
        pyperclip.copy(previous)


CONFIG_PATH = Path(__file__).with_name("config.toml")


def load_config():
    with open(CONFIG_PATH, "rb") as file:
        return tomllib.load(file)


def save_hotkey(key):
    """Hotkey in config.toml schreiben, Kommentare und Rest der Datei bleiben erhalten."""
    text = CONFIG_PATH.read_text(encoding="utf-8")
    text = re.sub(r'(?m)^key\s*=\s*".*"', f'key = "{key}"', text, count=1)
    CONFIG_PATH.write_text(text, encoding="utf-8")


MAC_KEYCODE_V = 9
# macOS-Tastencodes (physische Tasten, unabhaengig vom Layout).
MAC_KEYCODES = {
    "right option": 61, "left option": 58, "option": 58,
    "right command": 54, "left command": 55, "command": 55,
    "right ctrl": 62, "left ctrl": 59, "ctrl": 59,
    "right shift": 60, "left shift": 56, "shift": 56,
    "caps lock": 57, "fn": 63,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98,
    "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
    "f13": 105, "f14": 107, "f15": 113,
}


def parse_mac_hotkey(name):
    """Config-Name (z.B. "right option", "f9") in einen macOS-Tastencode umwandeln."""
    key = name.lower().strip().replace("alt", "option").replace("control", "ctrl")
    key = key.replace("cmd", "command").replace("windows", "command")
    if key not in MAC_KEYCODES:
        raise ValueError(f"Unbekannte Taste in config.toml: {name}")
    return MAC_KEYCODES[key]


class MacHotkeyListener:
    """Globaler Hotkey ueber einen Quartz-Event-Tap (nur lauschen, kein Eingriff).

    Ausgeloest wird beim Loslassen. Modifier-Tasten (z.B. rechte Option) zaehlen nur, wenn
    dazwischen keine andere Taste gedrueckt wurde, sonst wuerde Tippen von Sonderzeichen
    (Option+Taste) die Aufnahme umschalten.
    """

    def __init__(self, keycode, callback):
        masks = {
            58: Quartz.kCGEventFlagMaskAlternate, 61: Quartz.kCGEventFlagMaskAlternate,
            55: Quartz.kCGEventFlagMaskCommand, 54: Quartz.kCGEventFlagMaskCommand,
            59: Quartz.kCGEventFlagMaskControl, 62: Quartz.kCGEventFlagMaskControl,
            56: Quartz.kCGEventFlagMaskShift, 60: Quartz.kCGEventFlagMaskShift,
            57: Quartz.kCGEventFlagMaskAlphaShift, 63: Quartz.kCGEventFlagMaskSecondaryFn,
        }
        self.keycode = keycode
        self.callback = callback
        self.mask = masks.get(keycode)  # None = normale Taste (z.B. F9)
        self.other_key_used = False
        self.tap = None
        self.runloop = None
        self.ready = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()
        self.ready.wait(5)

    def _run(self):
        events = (
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
            | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
            | Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)
        )
        self.tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            events,
            self._on_event,
            None,
        )
        if self.tap is None:
            print(
                "Hotkey-Listener konnte nicht starten. Bitte unter Systemeinstellungen → "
                "Datenschutz & Sicherheit → Eingabeueberwachung (und Bedienungshilfen) "
                "freigeben und neu starten."
            )
            self.ready.set()
            return
        source = Quartz.CFMachPortCreateRunLoopSource(None, self.tap, 0)
        self.runloop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(self.runloop, source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self.tap, True)
        self.ready.set()
        Quartz.CFRunLoopRun()

    def _on_event(self, proxy, event_type, event, refcon):
        try:
            if event_type in (
                Quartz.kCGEventTapDisabledByTimeout,
                Quartz.kCGEventTapDisabledByUserInput,
            ):
                Quartz.CGEventTapEnable(self.tap, True)
                return event
            code = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
            if self.mask is None:
                if event_type == Quartz.kCGEventKeyUp and code == self.keycode:
                    self._fire()
            elif event_type == Quartz.kCGEventFlagsChanged and code == self.keycode:
                if Quartz.CGEventGetFlags(event) & self.mask:
                    self.other_key_used = False  # Taste gedrueckt
                elif not self.other_key_used:
                    self._fire()  # allein losgelassen
            elif event_type in (Quartz.kCGEventKeyDown, Quartz.kCGEventFlagsChanged):
                self.other_key_used = True
        except Exception as exc:
            print(f"Fehler im Hotkey-Listener: {exc}")
        return event

    def _fire(self):
        # Eigener Thread, damit der Event-Tap nie blockiert (sonst schaltet macOS ihn ab).
        threading.Thread(target=self._safe_callback, daemon=True).start()

    def _safe_callback(self):
        try:
            self.callback()
        except Exception as exc:
            print(f"Fehler im Hotkey-Handler: {exc}")

    def stop(self):
        if self.runloop is not None:
            Quartz.CFRunLoopStop(self.runloop)


def register_hotkey(hotkey, callback):
    """Hotkey registrieren. Ausgeloest wird beim Loslassen, damit Autorepeat nicht mehrfach schaltet."""
    if IS_MAC:
        return MacHotkeyListener(parse_mac_hotkey(hotkey), callback)
    keyboard.add_hotkey(hotkey, callback, trigger_on_release=True)
    return None


def print_mac_permissions_hint():
    print(
        "macOS: Falls der Hotkey nicht reagiert, unter\n"
        "  Systemeinstellungen → Datenschutz & Sicherheit → Bedienungshilfen\n"
        "  und ggf. „Eingabeueberwachung“ Terminal (oder iTerm/Cursor) erlauben.\n"
        "  Mikrofon-Zugriff ggf. ebenfalls freigeben."
    )


class Dictation:
    def __init__(self, cfg, backend):
        audio = cfg["audio"]
        self.backend = backend
        self.device = resolve_input_device(audio["device"])
        self.min_samples = int(audio["min_seconds"] * SAMPLE_RATE)
        self.lock = threading.Lock()
        self.stream = None
        self.frames = []
        self.pending = 0  # laufende Transkriptionen
        self.history = deque(maxlen=20)  # (Uhrzeit, Text), neueste zuletzt

    @property
    def state(self):
        if self.stream is not None:
            return "recording"
        return "transcribing" if self.pending else "idle"

    def toggle(self):
        """Wird vom Hotkey aufgerufen: startet oder stoppt die Aufnahme."""
        with self.lock:
            if self.stream is None:
                self._start()
            else:
                samples = self._stop()
                self.pending += 1
                threading.Thread(target=self._process, args=(samples,), daemon=True).start()

    def _start(self):
        self.frames = []
        try:
            self.stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                device=self.device,
                callback=self._on_audio,
            )
            self.stream.start()
        except sd.PortAudioError as exc:
            self.stream = None
            print(f"Mikrofon konnte nicht geoeffnet werden: {exc}")
            return
        print("Aufnahme laeuft ... (Hotkey nochmal druecken zum Stoppen)")
        beep(1000, 120)

    def _on_audio(self, indata, frames, time_info, status):
        self.frames.append(indata.copy())

    def _stop(self):
        self.stream.stop()
        self.stream.close()
        self.stream = None
        if not self.frames:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(self.frames).reshape(-1)

    def _process(self, samples):
        try:
            self._transcribe_and_paste(samples)
        finally:
            self.pending -= 1

    def _transcribe_and_paste(self, samples):
        if len(samples) < self.min_samples:
            print("Aufnahme zu kurz, wird verworfen.")
            return

        seconds = len(samples) / SAMPLE_RATE
        print(f"Transkribiere {seconds:.1f}s Audio ...")
        started = time.time()
        try:
            text = self.backend.transcribe(samples)
        except Exception as exc:
            print(f"Fehler bei der Transkription: {exc}")
            return

        if not text:
            print("Kein Text erkannt.")
            return

        print(f"> {text}  ({time.time() - started:.1f}s)")
        self.history.append((time.strftime("%H:%M"), text))
        paste_text(text)
        beep(600, 120)


def main():
    cfg = load_config()

    print(f"System: {platform.system()} {platform.machine()}")
    if IS_MAC:
        print_mac_permissions_hint()

    print("Lade Whisper-Modell (beim ersten Mal Download) ...")
    backend = create_backend(cfg)
    dictation = Dictation(cfg, backend)

    hotkey = cfg["hotkey"]["key"]
    register_hotkey(hotkey, dictation.toggle)

    paste_hint = "Cmd+V" if IS_MAC else "Strg+V"
    print(
        f"Bereit. Hotkey '{hotkey}': einmal starten, nochmal stoppen. "
        f"Einfuegen per {paste_hint}. Strg+C beendet."
    )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Beendet.")


if __name__ == "__main__":
    main()
