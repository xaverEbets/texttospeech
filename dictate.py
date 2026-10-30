"""Lokales Diktier-Tool fuer Windows.

Hotkey einmal druecken: Aufnahme startet.
Hotkey nochmal druecken: Aufnahme endet, Whisper wandelt das Audio in Text um,
und der Text wird an der aktuellen Cursorposition eingefuegt.
"""

import io
import subprocess
import threading
import time
import tomllib
import urllib.parse
import wave
from pathlib import Path

import keyboard
import numpy as np
import pyperclip
import requests
import sounddevice as sd

# Whisper erwartet 16 kHz, daher ist die Rate fest und nicht in der Config.
SAMPLE_RATE = 16000


def beep(freq, duration_ms):
    """Kurzer Signalton. Laeuft im Hintergrund, damit nichts blockiert."""
    def _play():
        try:
            import winsound
            winsound.Beep(freq, duration_ms)
        except ImportError:
            pass  # Nicht Windows, dann bleibt es still.

    threading.Thread(target=_play, daemon=True).start()


def to_wav_bytes(samples):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)  # int16
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(samples.tobytes())
    return buffer.getvalue()


class CpuBackend:
    """faster-whisper, laeuft auf der CPU."""

    def __init__(self, cfg):
        from faster_whisper import WhisperModel

        self.language = cfg["transcription"]["language"]
        self.model = WhisperModel(
            cfg["cpu"]["model"],
            device="cpu",
            compute_type=cfg["cpu"]["compute_type"],
        )

    def transcribe(self, samples):
        audio = samples.astype(np.float32) / 32768.0
        segments, _ = self.model.transcribe(
            audio, language=self.language, beam_size=5, vad_filter=True
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


class WhisperCppBackend:
    """whisper.cpp als HTTP-Server. Mit Vulkan laeuft das auch auf der AMD-Karte."""

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
            "-m", wcfg["model"],
            "-l", self.language,
            "--host", "127.0.0.1",
            "--port", str(port),
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


def paste_text(text):
    """Text per Zwischenablage einfuegen und die alte Zwischenablage wiederherstellen."""
    try:
        previous = pyperclip.paste()
    except pyperclip.PyperclipException:
        previous = None

    pyperclip.copy(text)
    time.sleep(0.05)
    keyboard.send("ctrl+v")
    time.sleep(0.5)  # Dem Zielprogramm Zeit geben, bevor die alte Zwischenablage zurueckkommt.

    if previous is not None:
        pyperclip.copy(previous)


class Dictation:
    def __init__(self, cfg, backend):
        audio = cfg["audio"]
        self.backend = backend
        self.device = audio["device"] or None
        self.min_samples = int(audio["min_seconds"] * SAMPLE_RATE)
        self.lock = threading.Lock()
        self.stream = None
        self.frames = []

    def toggle(self):
        """Wird vom Hotkey aufgerufen: startet oder stoppt die Aufnahme."""
        with self.lock:
            if self.stream is None:
                self._start()
            else:
                samples = self._stop()
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
        if len(samples) < self.min_samples:
            print("Aufnahme zu kurz, wird verworfen.")
            return

        print("Transkribiere ...")
        try:
            text = self.backend.transcribe(samples)
        except Exception as exc:
            print(f"Fehler bei der Transkription: {exc}")
            return

        if not text:
            print("Kein Text erkannt.")
            return

        print(f"> {text}")
        paste_text(text)
        beep(600, 120)


def main():
    config_path = Path(__file__).with_name("config.toml")
    with open(config_path, "rb") as file:
        cfg = tomllib.load(file)

    backend = create_backend(cfg)
    dictation = Dictation(cfg, backend)

    hotkey = cfg["hotkey"]["key"]
    # trigger_on_release verhindert, dass Autorepeat beim Halten die Aufnahme mehrfach umschaltet.
    keyboard.add_hotkey(hotkey, dictation.toggle, trigger_on_release=True)

    print(f"Bereit. Hotkey '{hotkey}': einmal starten, nochmal stoppen. Strg+C beendet.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Beendet.")


if __name__ == "__main__":
    main()
