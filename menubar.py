"""Menueleisten-App (macOS) fuer das Diktier-Tool.

Zeigt den Status als Icon, listet die letzten Transkriptionen zum erneuten Kopieren,
erlaubt die Hotkey-Auswahl und kann sich beim Login selbst starten.
"""

import plistlib
import subprocess
import sys
import threading
from pathlib import Path

import pyperclip
import rumps
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

import dictate

APP_DIR = Path(__file__).resolve().parent
LABEL = "com.servicetechnik.diktat"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_PATH = Path.home() / "Library" / "Logs" / "diktat.log"

# (Anzeigename, Tastenname fuer config.toml)
HOTKEY_PRESETS = [
    ("Rechte Option", "right option"),
    ("Rechte Cmd", "right command"),
    ("Rechte Ctrl", "right ctrl"),
    ("F9", "f9"),
    ("F8", "f8"),
]

# Template-Icons (schwarz mit Transparenz): macOS faerbt sie passend zur Menueleiste um.
ICON_DIR = APP_DIR / "icons"
ICONS = {
    "loading": str(ICON_DIR / "mic-working.png"),
    "idle": str(ICON_DIR / "mic.png"),
    "recording": str(ICON_DIR / "mic-recording.png"),
    "transcribing": str(ICON_DIR / "mic-working.png"),
    "error": str(ICON_DIR / "mic-error.png"),
}


def shorten(text, limit=60):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class DiktatApp(rumps.App):
    def __init__(self):
        super().__init__("Diktat", icon=ICONS["loading"], template=True, quit_button=None)
        self.shown_state = "loading"
        self.cfg = dictate.load_config()
        self.dictation = None
        self.listener = None
        self.error = None
        self.shown_history = None

        self.status_item = rumps.MenuItem("Lade Modell …")
        self.history_menu = rumps.MenuItem("Letzte Transkriptionen")
        self.history_menu.add(rumps.MenuItem("(noch nichts)"))
        self.hotkey_menu = rumps.MenuItem("Hotkey")
        self.hotkey_items = {}
        for label, key in HOTKEY_PRESETS:
            item = rumps.MenuItem(label, callback=lambda _s, k=key: self.set_hotkey(k))
            self.hotkey_items[key] = item
            self.hotkey_menu.add(item)
        self.autostart_item = rumps.MenuItem("Beim Login starten", callback=self.toggle_autostart)
        self.autostart_item.state = int(PLIST_PATH.exists())

        self.menu = [
            self.status_item,
            None,
            self.history_menu,
            self.hotkey_menu,
            self.autostart_item,
            rumps.MenuItem("config.toml öffnen", callback=lambda _s: self.open_config()),
            None,
            rumps.MenuItem("Beenden", callback=lambda _s: self.quit()),
        ]
        self.refresh_hotkey_checks()

        threading.Thread(target=self.load_backend, daemon=True).start()
        self.timer = rumps.Timer(self.refresh, 0.5)
        self.timer.start()

    # --- Start ---------------------------------------------------------------

    def load_backend(self):
        try:
            backend = dictate.create_backend(self.cfg)
            self.dictation = dictate.Dictation(self.cfg, backend)
            self.listener = dictate.register_hotkey(
                self.cfg["hotkey"]["key"], self.dictation.toggle
            )
        except Exception as exc:
            self.error = str(exc)
            print(f"Start fehlgeschlagen: {exc}")

    # --- Anzeige (laeuft im Hauptthread per Timer) -----------------------------

    def refresh(self, _timer):
        if self.error:
            state = "error"
            self.status_item.title = f"Fehler: {shorten(self.error, 50)}"
        elif self.dictation is None:
            state = "loading"
        else:
            state = self.dictation.state
            hotkey = self.cfg["hotkey"]["key"]
            texts = {
                "idle": f"Bereit (Hotkey: {hotkey})",
                "recording": "Aufnahme läuft …",
                "transcribing": "Transkribiere …",
            }
            self.status_item.title = texts[state]
        if state != self.shown_state:
            self.shown_state = state
            self.icon = ICONS[state]

        if self.dictation is not None:
            history = list(self.dictation.history)
            if history != self.shown_history:
                self.shown_history = history
                self.rebuild_history(history)

    def rebuild_history(self, history):
        self.history_menu.clear()
        if not history:
            self.history_menu.add(rumps.MenuItem("(noch nichts)"))
            return
        # Neueste zuerst. Zaehler im Titel, weil rumps gleiche Titel zusammenfasst.
        for number, (clock, text) in zip(range(len(history), 0, -1), reversed(history)):
            label = f"{number}. {clock}  {shorten(text)}"
            self.history_menu.add(
                rumps.MenuItem(label, callback=lambda _s, t=text: pyperclip.copy(t))
            )

    # --- Aktionen --------------------------------------------------------------

    def refresh_hotkey_checks(self):
        current = self.cfg["hotkey"]["key"]
        for key, item in self.hotkey_items.items():
            item.state = int(key == current)

    def set_hotkey(self, key):
        dictate.save_hotkey(key)
        self.cfg["hotkey"]["key"] = key
        if self.dictation is not None:
            if self.listener is not None:
                self.listener.stop()
            self.listener = dictate.register_hotkey(key, self.dictation.toggle)
        self.refresh_hotkey_checks()

    def toggle_autostart(self, sender):
        if PLIST_PATH.exists():
            PLIST_PATH.unlink()
            sender.state = 0
            return
        plist = {
            "Label": LABEL,
            "ProgramArguments": [sys.executable, str(APP_DIR / "menubar.py")],
            "WorkingDirectory": str(APP_DIR),
            "RunAtLoad": True,
            "StandardOutPath": str(LOG_PATH),
            "StandardErrorPath": str(LOG_PATH),
        }
        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(PLIST_PATH, "wb") as file:
            plistlib.dump(plist, file)
        sender.state = 1

    def open_config(self):
        subprocess.run(["open", "-t", str(dictate.CONFIG_PATH)])

    def quit(self):
        if self.listener is not None:
            self.listener.stop()
        rumps.quit_application()


if __name__ == "__main__":
    # Nur Menueleisten-Icon, kein Dock-Symbol.
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    DiktatApp().run()
