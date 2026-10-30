"""Desktop-Frontend & System-Tray App fuer das lokale Diktier-Tool (Windows & macOS).

Funktionen:
- Live-Status (Bereit / Aufnahme mit Mikrofon-Pegel / Transkription / Download-Fortschritt)
- Hotkey per Klick aufnehmen ("Taste druecken...") oder aus Presets waehlen
- Umschalten zwischen Toggle-Modus und Push-to-Talk (Gedrueckt halten)
- Mikrofon-Auswahl, Signalton & Autostart-Einstellung
- Liste der letzten Transkriptionen (persistent in history.json) mit 1-Klick-Kopieren & Suche
- System-Tray-Icon im Hintergrund (Windows via pystray)
"""

import ctypes
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

import pyperclip
from PIL import Image, ImageDraw

import dictate
import iconography

if dictate.IS_WINDOWS:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        import pystray
    except ImportError:
        pystray = None
else:
    pystray = None


# Farbpalette (Modern Dark Slate)
BG_MAIN = "#0F1117"
BG_CARD = "#181B24"
BG_INPUT = "#12151E"
BORDER_COLOR = "#262B38"
TEXT_PRIMARY = "#F3F4F6"
TEXT_SECONDARY = "#9CA3AF"
TEXT_MUTED = "#6B7280"
ACCENT = "#6366F1"
ACCENT_HOVER = "#4F46E5"
SUCCESS = "#10B981"
DANGER = "#EF4444"
WARNING = "#F59E0B"

HOTKEY_PRESETS_WIN = [
    ("Rechte Strg (right ctrl)", "right ctrl"),
    ("Rechte Alt / AltGr (right alt)", "right alt"),
    ("F9", "f9"),
    ("F8", "f8"),
    ("F10", "f10"),
    ("Feststelltaste (caps lock)", "caps lock"),
    ("Rollen (scroll lock)", "scroll lock"),
    ("Pause", "pause"),
]

HOTKEY_PRESETS_MAC = [
    ("Rechte Option (right option)", "right option"),
    ("Rechte Cmd (right command)", "right command"),
    ("Rechte Ctrl (right ctrl)", "right ctrl"),
    ("Fn-Taste (fn)", "fn"),
    ("F9", "f9"),
    ("F8", "f8"),
    ("F10", "f10"),
    ("Feststelltaste (caps lock)", "caps lock"),
]

LLM_MODEL_PRESETS = [
    "google/gemma-4-26b-a4b-it",
    "google/gemini-3.1-flash-lite-preview",
    "google/gemini-3.5-flash-lite",
    "openai/gpt-5.4-nano",
    "openai/gpt-5.4-mini",
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-5.5",
    "mistralai/mistral-small-2603",
    "deepseek/deepseek-v4.1-flash-1017",
    "google/gemma-4-26b-a4b-it:free",
]


def create_tray_image(state="idle"):
    """Erzeugt ein gestochen scharfes 64x64 Tray-Icon mit farbigem Status-Punkt."""
    try:
        return iconography.tray_icon(state=state, size=64)
    except Exception:
        pass
    colors = {
        "loading": (99, 102, 241, 255),      # Indigo
        "idle": (16, 185, 129, 255),         # Gruen
        "recording": (239, 68, 68, 255),     # Rot
        "transcribing": (245, 158, 11, 255), # Gelb/Orange
        "error": (244, 63, 94, 255),         # Rot
    }
    badge_color = colors.get(state, colors["idle"])

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.ellipse((4, 4, 60, 60), fill=(24, 27, 36, 255), outline=(55, 65, 81, 255), width=2)
    draw.rounded_rectangle((25, 14, 39, 34), radius=7, fill=(243, 244, 246, 255))
    draw.arc((20, 20, 44, 41), start=0, end=180, fill=(243, 244, 246, 255), width=3)
    draw.line((32, 41, 32, 48), fill=(243, 244, 246, 255), width=3)
    draw.line((25, 48, 39, 48), fill=(243, 244, 246, 255), width=3)
    draw.ellipse((42, 42, 60, 60), fill=badge_color, outline=(15, 17, 23, 255), width=3)
    return img


class DiktatFrontend:
    def __init__(self, start_minimized=False):
        self.cfg = dictate.load_config()
        self.backend = None
        self.dictation = None
        self.listener = None
        self.status_message = "Initialisiere Whisper-Engine …"
        self.error_message = None
        self.recording_hotkey = False
        self.shown_state = "loading"
        self.last_history_signature = None
        self.tray_icon = None
        self.quitting = False

        # Thread-sichere Queue fuer Befehle aus Hintergrund-Threads (Tray / Hotkey-Capture)
        self.ui_queue = queue.Queue()

        # Caches, damit Widgets nur bei echten Aenderungen neu konfiguriert werden
        self._last_status_text = None
        self._last_dot_color = None
        self._last_btn_signature = None
        self._last_backend_text = None

        self.root = tk.Tk()
        self.root.title("Whisper Flow Local")
        self.root.geometry("580x760")
        self.root.minsize(500, 620)
        self.root.configure(bg=BG_MAIN)

        try:
            app_png = dictate.APP_DIR / "icons" / "app.png"
            icon_path = app_png if app_png.exists() else (dictate.APP_DIR / "icons" / "mic@2x.png")
            self._tk_icon = tk.PhotoImage(file=str(icon_path))
            self.root.iconphoto(True, self._tk_icon)
        except Exception:
            pass

        self.root.protocol("WM_DELETE_WINDOW", self.on_window_close)

        self._setup_styles()
        self._build_ui()

        if dictate.IS_WINDOWS and pystray is not None:
            self._start_tray()

        if start_minimized:
            if dictate.IS_WINDOWS and pystray is not None:
                self.root.withdraw()
            else:
                self.root.iconify()

        threading.Thread(target=self._init_backend, daemon=True).start()
        self._schedule_refresh()

    def _setup_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Dark.TCombobox",
            fieldbackground=BG_INPUT,
            background=BG_CARD,
            foreground=TEXT_PRIMARY,
            bordercolor=BORDER_COLOR,
            arrowcolor=TEXT_PRIMARY,
            padding=5,
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", BG_INPUT), ("!disabled", BG_INPUT)],
            selectbackground=[("readonly", BG_INPUT), ("!disabled", BG_INPUT)],
            selectforeground=[("readonly", TEXT_PRIMARY), ("!disabled", TEXT_PRIMARY)],
        )

    def _build_ui(self):
        # --- 1. TOP STATUS CARD ---
        status_card = tk.Frame(
            self.root,
            bg=BG_CARD,
            highlightbackground=BORDER_COLOR,
            highlightthickness=1,
            padx=16,
            pady=14,
        )
        status_card.pack(fill="x", padx=16, pady=(16, 10))

        top_row = tk.Frame(status_card, bg=BG_CARD)
        top_row.pack(fill="x")

        self.status_dot = tk.Canvas(
            top_row, width=14, height=14, bg=BG_CARD, highlightthickness=0
        )
        self.status_dot.pack(side="left", padx=(0, 8), pady=2)
        self.dot_id = self.status_dot.create_oval(2, 2, 12, 12, fill=ACCENT, outline="")

        self.status_label = tk.Label(
            top_row,
            text="Lade Whisper-Modell …",
            font=("Segoe UI", 11, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_CARD,
            anchor="w",
        )
        self.status_label.pack(side="left", fill="x", expand=True)

        self.action_btn = tk.Button(
            top_row,
            text="🎙 Aufnahme starten",
            font=("Segoe UI", 9, "bold"),
            fg=TEXT_PRIMARY,
            bg=ACCENT,
            activebackground=ACCENT_HOVER,
            activeforeground=TEXT_PRIMARY,
            bd=0,
            padx=12,
            pady=5,
            cursor="hand2",
            state="disabled",
            command=self.manual_toggle_recording,
        )
        self.action_btn.pack(side="right")

        sub_row = tk.Frame(status_card, bg=BG_CARD)
        sub_row.pack(fill="x", pady=(8, 0))

        self.backend_label = tk.Label(
            sub_row,
            text="Hardware-Beschleunigung wird geprüft …",
            font=("Segoe UI", 9),
            fg=TEXT_SECONDARY,
            bg=BG_CARD,
            anchor="w",
        )
        self.backend_label.pack(side="left")

        self.level_canvas = tk.Canvas(
            status_card, height=6, bg=BG_INPUT, highlightthickness=0
        )
        self.level_canvas.pack(fill="x", pady=(10, 0))
        self.level_bar = self.level_canvas.create_rectangle(0, 0, 0, 6, fill=SUCCESS, width=0)

        # --- 2. SETTINGS CARD (Hotkey, Modus, Mikrofon) ---
        settings_card = tk.Frame(
            self.root,
            bg=BG_CARD,
            highlightbackground=BORDER_COLOR,
            highlightthickness=1,
            padx=16,
            pady=12,
        )
        settings_card.pack(fill="x", padx=16, pady=(0, 10))

        hk_row = tk.Frame(settings_card, bg=BG_CARD)
        hk_row.pack(fill="x", pady=(0, 8))

        tk.Label(
            hk_row,
            text="Hotkey:",
            font=("Segoe UI", 10, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_CARD,
            width=11,
            anchor="w",
        ).pack(side="left")

        presets = HOTKEY_PRESETS_MAC if dictate.IS_MAC else HOTKEY_PRESETS_WIN
        self.preset_map = {label: key for label, key in presets}
        self.key_to_label = {key: label for label, key in presets}

        current_key = self.cfg["hotkey"]["key"]
        self.hotkey_var = tk.StringVar(
            value=self.key_to_label.get(current_key, f"Taste: {current_key}")
        )
        self.hotkey_combo = ttk.Combobox(
            hk_row,
            textvariable=self.hotkey_var,
            values=list(self.preset_map.keys()),
            state="readonly",
            style="Dark.TCombobox",
            width=26,
        )
        self.hotkey_combo.pack(side="left", padx=(0, 8))
        self.hotkey_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)

        self.record_hk_btn = tk.Button(
            hk_row,
            text="⌨ Taste aufnehmen …",
            font=("Segoe UI", 9),
            fg=TEXT_PRIMARY,
            bg=BG_INPUT,
            activebackground=BORDER_COLOR,
            activeforeground=TEXT_PRIMARY,
            bd=0,
            padx=10,
            pady=4,
            cursor="hand2",
            command=self.start_hotkey_capture,
        )
        self.record_hk_btn.pack(side="left")

        mode_row = tk.Frame(settings_card, bg=BG_CARD)
        mode_row.pack(fill="x", pady=(0, 8))

        tk.Label(
            mode_row,
            text="Modus:",
            font=("Segoe UI", 10, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_CARD,
            width=11,
            anchor="w",
        ).pack(side="left")

        self.mode_var = tk.StringVar(value=self.cfg["hotkey"].get("mode", "toggle"))

        self.btn_mode_toggle = tk.Button(
            mode_row,
            text="Toggle (1x Start / 1x Stopp)",
            font=("Segoe UI", 9),
            bd=0,
            padx=10,
            pady=4,
            cursor="hand2",
            command=lambda: self.set_mode("toggle"),
        )
        self.btn_mode_toggle.pack(side="left", padx=(0, 6))

        self.btn_mode_hold = tk.Button(
            mode_row,
            text="Push-to-Talk (Gedrückt halten)",
            font=("Segoe UI", 9),
            bd=0,
            padx=10,
            pady=4,
            cursor="hand2",
            command=lambda: self.set_mode("hold"),
        )
        self.btn_mode_hold.pack(side="left")
        self._update_mode_buttons()

        mic_row = tk.Frame(settings_card, bg=BG_CARD)
        mic_row.pack(fill="x")

        tk.Label(
            mic_row,
            text="Mikrofon:",
            font=("Segoe UI", 10, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_CARD,
            width=11,
            anchor="w",
        ).pack(side="left")

        devices = dictate.list_input_devices()
        self.device_names = ["Standard-Mikrofon"] + [name for _, name in devices]
        current_dev = self.cfg["audio"].get("device", "")
        selected_dev = "Standard-Mikrofon"
        if current_dev:
            for _, name in devices:
                if current_dev.lower() in name.lower():
                    selected_dev = name
                    break

        self.mic_var = tk.StringVar(value=selected_dev)
        self.mic_combo = ttk.Combobox(
            mic_row,
            textvariable=self.mic_var,
            values=self.device_names,
            state="readonly",
            style="Dark.TCombobox",
            width=22,
        )
        self.mic_combo.pack(side="left", padx=(0, 8))
        self.mic_combo.bind("<<ComboboxSelected>>", self._on_mic_selected)

        self.sound_var = tk.BooleanVar(value=bool(self.cfg["audio"].get("sound", True)))
        self.sound_cb = tk.Checkbutton(
            mic_row,
            text="Töne",
            variable=self.sound_var,
            font=("Segoe UI", 9),
            fg=TEXT_SECONDARY,
            bg=BG_CARD,
            selectcolor=BG_INPUT,
            activebackground=BG_CARD,
            activeforeground=TEXT_PRIMARY,
            command=self._on_sound_toggled,
        )
        self.sound_cb.pack(side="left", padx=(0, 6))

        self.autostart_var = tk.BooleanVar(value=dictate.is_autostart_enabled())
        self.autostart_cb = tk.Checkbutton(
            mic_row,
            text="Autostart",
            variable=self.autostart_var,
            font=("Segoe UI", 9),
            fg=TEXT_SECONDARY,
            bg=BG_CARD,
            selectcolor=BG_INPUT,
            activebackground=BG_CARD,
            activeforeground=TEXT_PRIMARY,
            command=self._on_autostart_toggled,
        )
        self.autostart_cb.pack(side="left")

        # --- 2b. LLM POST-PROCESSING CARD (OpenRouter) ---
        llm_card = tk.Frame(
            self.root,
            bg=BG_CARD,
            highlightbackground=BORDER_COLOR,
            highlightthickness=1,
            padx=16,
            pady=10,
        )
        llm_card.pack(fill="x", padx=16, pady=(0, 10))

        llm_cfg = self.cfg.get("llm", {})
        llm_top = tk.Frame(llm_card, bg=BG_CARD)
        llm_top.pack(fill="x", pady=(0, 6))

        self.llm_enabled_var = tk.BooleanVar(value=bool(llm_cfg.get("enabled", False)))
        self.llm_cb = tk.Checkbutton(
            llm_top,
            text="✨ KI-Nachbearbeitung (Füllwörter, Grammatik & Rechtschreibung)",
            variable=self.llm_enabled_var,
            font=("Segoe UI", 9, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_CARD,
            selectcolor=BG_INPUT,
            activebackground=BG_CARD,
            activeforeground=TEXT_PRIMARY,
            command=self._on_llm_toggled,
        )
        self.llm_cb.pack(side="left")

        self.llm_status_lbl = tk.Label(
            llm_top,
            text="",
            font=("Segoe UI", 8, "bold"),
            fg=TEXT_MUTED,
            bg=BG_CARD,
        )
        self.llm_status_lbl.pack(side="right")

        llm_mid = tk.Frame(llm_card, bg=BG_CARD)
        llm_mid.pack(fill="x", pady=(0, 6))

        tk.Label(
            llm_mid,
            text="KI-Modell:",
            font=("Segoe UI", 9),
            fg=TEXT_SECONDARY,
            bg=BG_CARD,
            width=12,
            anchor="w",
        ).pack(side="left")

        current_model = llm_cfg.get("model") or "google/gemma-4-26b-a4b-it"
        model_values = list(LLM_MODEL_PRESETS)
        if current_model not in model_values:
            model_values.insert(0, current_model)

        self.llm_model_var = tk.StringVar(value=current_model)
        self.llm_model_combo = ttk.Combobox(
            llm_mid,
            textvariable=self.llm_model_var,
            values=model_values,
            state="normal",
            style="Dark.TCombobox",
            width=32,
        )
        self.llm_model_combo.pack(side="left", padx=(0, 8), fill="x", expand=True)
        self.llm_model_combo.bind("<<ComboboxSelected>>", self._on_llm_model_changed)
        self.llm_model_combo.bind("<FocusOut>", self._on_llm_model_changed)
        self.llm_model_combo.bind("<Return>", self._on_llm_model_changed)

        self.llm_test_btn = tk.Button(
            llm_mid,
            text="⚡ Test",
            font=("Segoe UI", 8, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_INPUT,
            activebackground=ACCENT,
            activeforeground=TEXT_PRIMARY,
            bd=0,
            padx=10,
            pady=4,
            cursor="hand2",
            command=self.test_llm_api,
        )
        self.llm_test_btn.pack(side="right")

        llm_bot = tk.Frame(llm_card, bg=BG_CARD)
        llm_bot.pack(fill="x")

        tk.Label(
            llm_bot,
            text="OpenRouter Key:",
            font=("Segoe UI", 9),
            fg=TEXT_SECONDARY,
            bg=BG_CARD,
            width=12,
            anchor="w",
        ).pack(side="left")

        self.llm_key_var = tk.StringVar(value=llm_cfg.get("api_key", ""))
        self.show_key = False
        self.llm_key_entry = tk.Entry(
            llm_bot,
            textvariable=self.llm_key_var,
            show="•",
            font=("Consolas", 9),
            fg=TEXT_PRIMARY,
            bg=BG_INPUT,
            insertbackground=TEXT_PRIMARY,
            highlightbackground=BORDER_COLOR,
            highlightthickness=1,
            bd=0,
        )
        self.llm_key_entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 6))
        self.llm_key_entry.bind("<Return>", self.save_llm_key_action)
        self.llm_key_entry.bind("<KeyRelease>", self._on_llm_key_edited)

        # Rechtsklick-Kontextmenü für das API-Key-Feld (Einfügen / Kopieren / Leeren)
        self._key_menu = tk.Menu(
            self.root,
            tearoff=0,
            bg=BG_CARD,
            fg=TEXT_PRIMARY,
            activebackground=ACCENT,
            activeforeground=TEXT_PRIMARY,
        )
        self._key_menu.add_command(label="Einfügen", command=self._paste_into_key_entry)
        self._key_menu.add_command(label="Leeren", command=self._clear_key_entry)
        self.llm_key_entry.bind(
            "<Button-3>",
            lambda e: self._key_menu.tk_popup(e.x_root, e.y_root),
        )

        self.save_key_btn = tk.Button(
            llm_bot,
            text="💾 Speichern",
            font=("Segoe UI", 8, "bold"),
            fg=TEXT_PRIMARY,
            bg=ACCENT,
            activebackground=ACCENT_HOVER,
            activeforeground=TEXT_PRIMARY,
            bd=0,
            padx=10,
            pady=4,
            cursor="hand2",
            command=self.save_llm_key_action,
        )
        self.save_key_btn.pack(side="right")

        self.toggle_key_btn = tk.Button(
            llm_bot,
            text="👁",
            font=("Segoe UI", 8),
            fg=TEXT_SECONDARY,
            bg=BG_INPUT,
            activebackground=BORDER_COLOR,
            activeforeground=TEXT_PRIMARY,
            bd=0,
            padx=7,
            pady=4,
            cursor="hand2",
            command=self._toggle_key_visibility,
        )
        self.toggle_key_btn.pack(side="right", padx=(0, 6))

        self._update_llm_badge()

        # --- 3. TRANSCRIPT HISTORY SECTION ---
        hist_header = tk.Frame(self.root, bg=BG_MAIN)
        hist_header.pack(fill="x", padx=16, pady=(4, 6))

        tk.Label(
            hist_header,
            text="Letzte Transkriptionen",
            font=("Segoe UI", 11, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_MAIN,
        ).pack(side="left")

        self.clear_btn = tk.Button(
            hist_header,
            text="Verlauf leeren",
            font=("Segoe UI", 8),
            fg=TEXT_SECONDARY,
            bg=BG_CARD,
            activebackground=DANGER,
            activeforeground=TEXT_PRIMARY,
            bd=0,
            padx=8,
            pady=3,
            cursor="hand2",
            command=self.clear_history,
        )
        self.clear_btn.pack(side="right")

        search_frame = tk.Frame(
            self.root,
            bg=BG_CARD,
            highlightbackground=BORDER_COLOR,
            highlightthickness=1,
            padx=10,
            pady=5,
        )
        search_frame.pack(fill="x", padx=16, pady=(0, 8))

        tk.Label(
            search_frame, text="🔍", font=("Segoe UI", 9), fg=TEXT_MUTED, bg=BG_CARD
        ).pack(side="left", padx=(0, 6))

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.rebuild_history_list(force=True))
        self.search_entry = tk.Entry(
            search_frame,
            textvariable=self.search_var,
            font=("Segoe UI", 9),
            fg=TEXT_PRIMARY,
            bg=BG_CARD,
            insertbackground=TEXT_PRIMARY,
            bd=0,
        )
        self.search_entry.pack(side="left", fill="x", expand=True)

        list_container = tk.Frame(self.root, bg=BG_MAIN)
        list_container.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        self.hist_canvas = tk.Canvas(
            list_container, bg=BG_MAIN, highlightthickness=0, bd=0
        )
        self.scrollbar = ttk.Scrollbar(
            list_container, orient="vertical", command=self.hist_canvas.yview
        )
        self.hist_inner = tk.Frame(self.hist_canvas, bg=BG_MAIN)

        self.hist_inner.bind(
            "<Configure>",
            lambda _e: self.hist_canvas.configure(scrollregion=self.hist_canvas.bbox("all")),
        )
        self.canvas_window = self.hist_canvas.create_window(
            (0, 0), window=self.hist_inner, anchor="nw"
        )
        self.hist_canvas.bind(
            "<Configure>",
            lambda e: self.hist_canvas.itemconfig(self.canvas_window, width=e.width),
        )
        self.hist_canvas.configure(yscrollcommand=self.scrollbar.set)

        self.hist_canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.hist_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # --- 4. FOOTER ---
        footer = tk.Frame(self.root, bg=BG_MAIN, padx=16, pady=8)
        footer.pack(fill="x", side="bottom")

        hint_text = (
            "Schließen (X) minimiert in den System-Tray"
            if (dictate.IS_WINDOWS and pystray is not None)
            else "Klick auf ein Transkript kopiert es sofort in die Zwischenablage"
        )
        tk.Label(
            footer,
            text=hint_text,
            font=("Segoe UI", 8),
            fg=TEXT_MUTED,
            bg=BG_MAIN,
        ).pack(side="left")

        tk.Button(
            footer,
            text="Komplett beenden",
            font=("Segoe UI", 8, "bold"),
            fg=TEXT_SECONDARY,
            bg=BG_CARD,
            activebackground=DANGER,
            activeforeground=TEXT_PRIMARY,
            bd=0,
            padx=10,
            pady=3,
            cursor="hand2",
            command=self.quit_app,
        ).pack(side="right")

        tk.Button(
            footer,
            text="config.toml",
            font=("Segoe UI", 8),
            fg=TEXT_SECONDARY,
            bg=BG_CARD,
            activebackground=BORDER_COLOR,
            activeforeground=TEXT_PRIMARY,
            bd=0,
            padx=8,
            pady=3,
            cursor="hand2",
            command=self.open_config_file,
        ).pack(side="right", padx=(0, 8))

    def _on_mousewheel(self, event):
        try:
            if dictate.IS_MAC:
                self.hist_canvas.yview_scroll(int(-1 * event.delta), "units")
            else:
                self.hist_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    # --- Backend & Hotkey Steuerung -------------------------------------------

    def _init_backend(self):
        try:
            self.backend = dictate.create_backend(
                self.cfg, status_callback=self._set_loading_status
            )
            self.dictation = dictate.Dictation(self.cfg, self.backend)
            self.listener = dictate.register_hotkey(
                self.cfg["hotkey"]["key"],
                self.dictation,
                mode=self.cfg["hotkey"].get("mode", "toggle"),
            )
        except Exception as exc:
            self.error_message = str(exc)
            print(f"Fehler beim Starten: {exc}")

    def _set_loading_status(self, msg):
        self.status_message = msg

    def manual_toggle_recording(self):
        if self.dictation is not None:
            threading.Thread(target=self.dictation.toggle, daemon=True).start()

    def _on_preset_selected(self, _event=None):
        label = self.hotkey_var.get()
        key = self.preset_map.get(label)
        if key:
            self.apply_new_hotkey(key)

    def start_hotkey_capture(self):
        if self.recording_hotkey:
            return
        self.recording_hotkey = True
        self.record_hk_btn.configure(text="Drücke eine Taste …", bg=ACCENT)

        if self.listener is not None:
            self.listener.stop()
            self.listener = None

        if dictate.IS_WINDOWS:
            threading.Thread(target=self._capture_key_win, daemon=True).start()
        else:
            self.root.bind("<KeyRelease>", self._capture_key_tk)

    def _capture_key_win(self):
        try:
            key_name = dictate.capture_next_key_windows(timeout=8.0)
            self.ui_queue.put(lambda: self._finish_hotkey_capture(key_name))
        except Exception:
            self.ui_queue.put(lambda: self._finish_hotkey_capture(None))

    def _capture_key_tk(self, event):
        self.root.unbind("<KeyRelease>")
        keysym = (event.keysym or "").lower()
        tk_map = {
            "alt_r": "right option",
            "alt_l": "left option",
            "meta_r": "right command",
            "meta_l": "left command",
            "super_r": "right command",
            "super_l": "left command",
            "control_r": "right ctrl",
            "control_l": "left ctrl",
            "shift_r": "right shift",
            "shift_l": "left shift",
            "caps_lock": "caps lock",
        }
        chosen = tk_map.get(keysym, keysym)
        if chosen == "escape":
            chosen = None
        self._finish_hotkey_capture(chosen)

    def _finish_hotkey_capture(self, key_name):
        self.recording_hotkey = False
        self.record_hk_btn.configure(text="⌨ Taste aufnehmen …", bg=BG_INPUT)
        if key_name:
            self.apply_new_hotkey(key_name)
        else:
            self._rebind_hotkey()

    def apply_new_hotkey(self, key):
        key = dictate.normalize_hotkey_for_platform(key)
        self.cfg["hotkey"]["key"] = key
        dictate.save_hotkey(key)
        self.hotkey_var.set(self.key_to_label.get(key, f"Taste: {key}"))
        self.error_message = None
        self._rebind_hotkey()

    def set_mode(self, mode):
        self.cfg["hotkey"]["mode"] = mode
        self.mode_var.set(mode)
        dictate.save_mode(mode)
        self._update_mode_buttons()
        self._rebind_hotkey()

    def _update_mode_buttons(self):
        mode = self.mode_var.get()
        if mode == "hold":
            self.btn_mode_toggle.configure(bg=BG_INPUT, fg=TEXT_SECONDARY)
            self.btn_mode_hold.configure(bg=ACCENT, fg=TEXT_PRIMARY)
        else:
            self.btn_mode_toggle.configure(bg=ACCENT, fg=TEXT_PRIMARY)
            self.btn_mode_hold.configure(bg=BG_INPUT, fg=TEXT_SECONDARY)

    def _rebind_hotkey(self):
        if self.listener is not None:
            self.listener.stop()
            self.listener = None
        if self.dictation is not None:
            try:
                self.listener = dictate.register_hotkey(
                    self.cfg["hotkey"]["key"],
                    self.dictation,
                    mode=self.cfg["hotkey"].get("mode", "toggle"),
                )
            except Exception as exc:
                self.error_message = f"Ungültiger Hotkey '{self.cfg['hotkey']['key']}': {exc}"

    def _on_mic_selected(self, _event=None):
        val = self.mic_var.get()
        device_str = "" if val == "Standard-Mikrofon" else val
        if self.dictation is not None:
            self.dictation.set_device(device_str)
        else:
            self.cfg["audio"]["device"] = device_str
            dictate.save_device(device_str)

    def _on_sound_toggled(self):
        enabled = bool(self.sound_var.get())
        self.cfg["audio"]["sound"] = enabled
        dictate.save_sound(enabled)
        if self.dictation is not None:
            self.dictation.sound_enabled = enabled

    def _on_autostart_toggled(self):
        enabled = bool(self.autostart_var.get())
        try:
            actual = dictate.set_autostart(enabled, mac_script="app.py")
            self.autostart_var.set(actual)
        except Exception as exc:
            self.error_message = f"Autostart-Fehler: {exc}"
            self.autostart_var.set(dictate.is_autostart_enabled())

    def _on_llm_toggled(self):
        enabled = bool(self.llm_enabled_var.get())
        self.cfg.setdefault("llm", {})["enabled"] = enabled
        dictate.save_llm_enabled(enabled)
        self._update_llm_badge()
        if enabled and self.dictation is not None:
            self.dictation.llm.warmup_async()

    def _on_llm_model_changed(self, _event=None):
        model = self.llm_model_var.get().strip()
        if not model:
            return
        if model != self.cfg.get("llm", {}).get("model"):
            self.cfg.setdefault("llm", {})["model"] = model
            dictate.save_llm_model(model)
            self._update_llm_badge()

    def _on_llm_key_edited(self, _event=None):
        current = self.llm_key_var.get().strip()
        saved = (self.cfg.get("llm", {}).get("api_key") or "").strip()
        if current != saved:
            self.save_key_btn.configure(text="💾 Speichern *", bg=ACCENT, fg=TEXT_PRIMARY)

    def _paste_into_key_entry(self):
        try:
            clip = pyperclip.paste().strip()
            if clip:
                self.llm_key_var.set(clip)
                self._on_llm_key_edited()
        except Exception:
            pass

    def _clear_key_entry(self):
        self.llm_key_var.set("")
        self._on_llm_key_edited()

    def save_llm_key_action(self, _event=None):
        key = self.llm_key_var.get().strip()
        self.cfg.setdefault("llm", {})["api_key"] = key
        dictate.save_llm_api_key(key)
        self._update_llm_badge()
        if hasattr(self, "save_key_btn") and self.save_key_btn.winfo_exists():
            self.save_key_btn.configure(text="✓ Gespeichert!", bg=SUCCESS, fg=TEXT_PRIMARY)
            self.root.after(
                1500,
                lambda: self.save_key_btn.configure(
                    text="💾 Speichern", bg=BG_INPUT, fg=TEXT_SECONDARY
                )
                if self.save_key_btn.winfo_exists()
                else None,
            )
        if self.dictation is not None and self.cfg.get("llm", {}).get("enabled"):
            self.dictation.llm.warmup_async()

    def _toggle_key_visibility(self):
        self.show_key = not self.show_key
        self.llm_key_entry.configure(show="" if self.show_key else "•")

    def _update_llm_badge(self, custom_text=None, custom_color=None):
        if custom_text is not None:
            self.llm_status_lbl.configure(text=custom_text, fg=custom_color or TEXT_MUTED)
            return
        enabled = bool(self.cfg.get("llm", {}).get("enabled", False))
        has_key = bool(
            (self.cfg.get("llm", {}).get("api_key") or os.environ.get("OPENROUTER_API_KEY") or "").strip()
        )
        if not enabled:
            self.llm_status_lbl.configure(text="Aus (nur lokaler 0ms Filter)", fg=TEXT_MUTED)
        elif not has_key:
            self.llm_status_lbl.configure(text="⚠ API-Key fehlt", fg=WARNING)
        else:
            self.llm_status_lbl.configure(text="● Bereit", fg=SUCCESS)

    def test_llm_api(self):
        self.save_llm_key_action()
        self._on_llm_model_changed()
        self.llm_test_btn.configure(text="⏳ …", state="disabled")
        self._update_llm_badge("Teste OpenRouter …", WARNING)

        def _run_test():
            processor = self.dictation.llm if self.dictation else dictate.LlmPostProcessor(self.cfg)
            try:
                polished, ms = processor.test_connection()
                self.ui_queue.put(lambda: self._on_llm_test_done(True, f"✓ {ms} ms", polished))
            except Exception as exc:
                err_msg = str(exc)
                self.ui_queue.put(lambda: self._on_llm_test_done(False, err_msg, None))

        threading.Thread(target=_run_test, daemon=True).start()

    def _on_llm_test_done(self, ok, info, polished_sample):
        self.llm_test_btn.configure(text="⚡ Test", state="normal")
        if ok:
            self._update_llm_badge(f"{info}  •  OK", SUCCESS)
            print(f"OpenRouter Test erfolgreich ({info}): {polished_sample}")
        else:
            short_err = info[:36] + ("…" if len(info) > 36 else "")
            self._update_llm_badge(f"✕ {short_err}", DANGER)

    # --- Historie / Kopieren --------------------------------------------------

    def copy_transcript(self, text, btn=None):
        pyperclip.copy(text)
        if btn is not None and btn.winfo_exists():
            orig_text = btn.cget("text")
            btn.configure(text="✓ Kopiert!", bg=SUCCESS, fg=TEXT_PRIMARY)
            self.root.after(
                1400,
                lambda: btn.configure(text=orig_text, bg=ACCENT, fg=TEXT_PRIMARY)
                if btn.winfo_exists()
                else None,
            )

    def delete_entry(self, entry_id):
        if self.dictation is not None:
            self.dictation.delete_history_entry(entry_id)
            self.rebuild_history_list(force=True)

    def clear_history(self):
        if self.dictation is not None:
            self.dictation.clear_history()
            self.rebuild_history_list(force=True)

    def rebuild_history_list(self, force=False):
        if self.dictation is None:
            return
        entries = list(self.dictation.history_entries)
        sig = (len(entries), entries[-1]["id"] if entries else "")
        if not force and sig == self.last_history_signature:
            return
        self.last_history_signature = sig

        for child in self.hist_inner.winfo_children():
            child.destroy()

        query = self.search_var.get().strip().lower()
        filtered = [
            e for e in reversed(entries) if not query or query in e.get("text", "").lower()
        ]

        if not filtered:
            empty_msg = (
                "Keine Treffer für die Suche."
                if query
                else "Noch keine Transkriptionen vorhanden.\nDrücke deinen Hotkey und sprich los!"
            )
            tk.Label(
                self.hist_inner,
                text=empty_msg,
                font=("Segoe UI", 10),
                fg=TEXT_MUTED,
                bg=BG_MAIN,
                justify="center",
                pady=40,
            ).pack(fill="x")
            return

        for entry in filtered:
            self._create_history_card(entry)

    def _create_history_card(self, entry):
        card = tk.Frame(
            self.hist_inner,
            bg=BG_CARD,
            highlightbackground=BORDER_COLOR,
            highlightthickness=1,
            padx=12,
            pady=10,
        )
        card.pack(fill="x", pady=(0, 8))

        meta_row = tk.Frame(card, bg=BG_CARD)
        meta_row.pack(fill="x", pady=(0, 6))

        time_str = entry.get("time", "")
        date_str = entry.get("date", "")
        dur = entry.get("duration", 0)
        elap = entry.get("elapsed", 0)
        llm_used = entry.get("llm_used", False)
        llm_elap = entry.get("llm_elapsed", 0)
        meta_text = f"🕒 {time_str}"
        if date_str:
            meta_text += f" ({date_str})"
        if dur:
            meta_text += f"  •  🎙 {dur}s Audio  •  ⚡ {elap}s"
        if llm_used:
            meta_text += f"  •  ✨ KI ({llm_elap}s)"

        tk.Label(
            meta_row,
            text=meta_text,
            font=("Segoe UI", 8),
            fg=TEXT_MUTED,
            bg=BG_CARD,
        ).pack(side="left")

        text_val = entry.get("text", "")
        entry_id = entry.get("id", "")

        del_btn = tk.Button(
            meta_row,
            text="✕",
            font=("Segoe UI", 8),
            fg=TEXT_MUTED,
            bg=BG_CARD,
            activebackground=DANGER,
            activeforeground=TEXT_PRIMARY,
            bd=0,
            padx=6,
            pady=1,
            cursor="hand2",
            command=lambda eid=entry_id: self.delete_entry(eid),
        )
        del_btn.pack(side="right", padx=(6, 0))

        copy_btn = tk.Button(
            meta_row,
            text="📋 Kopieren",
            font=("Segoe UI", 8, "bold"),
            fg=TEXT_PRIMARY,
            bg=ACCENT,
            activebackground=ACCENT_HOVER,
            activeforeground=TEXT_PRIMARY,
            bd=0,
            padx=10,
            pady=2,
            cursor="hand2",
        )
        copy_btn.configure(command=lambda t=text_val, b=copy_btn: self.copy_transcript(t, b))
        copy_btn.pack(side="right")

        msg_lbl = tk.Label(
            card,
            text=text_val,
            font=("Segoe UI", 10),
            fg=TEXT_PRIMARY,
            bg=BG_CARD,
            justify="left",
            anchor="w",
            wraplength=500,
            cursor="hand2",
        )
        msg_lbl.pack(fill="x")
        msg_lbl.bind("<Button-1>", lambda _e, t=text_val, b=copy_btn: self.copy_transcript(t, b))

        raw_val = (entry.get("raw_text") or "").strip()
        if raw_val and raw_val != text_val:
            raw_lbl = tk.Label(
                card,
                text=f"Roh-Transkript: {raw_val}",
                font=("Segoe UI", 8, "italic"),
                fg=TEXT_MUTED,
                bg=BG_CARD,
                justify="left",
                anchor="w",
                wraplength=500,
            )
            raw_lbl.pack(fill="x", pady=(4, 0))

    # --- UI-Timer & Tray ------------------------------------------------------

    def _schedule_refresh(self):
        if self.quitting:
            return
        while True:
            try:
                fn = self.ui_queue.get_nowait()
                fn()
            except queue.Empty:
                break
            except Exception as exc:
                print(f"UI-Queue-Fehler: {exc}")

        self._refresh_ui()
        self.root.after(100, self._schedule_refresh)

    def _set_status_ui(self, dot_color, text, btn_text=None, btn_bg=None, btn_state=None):
        if dot_color != self._last_dot_color:
            self._last_dot_color = dot_color
            self.status_dot.itemconfig(self.dot_id, fill=dot_color)
        if text != self._last_status_text:
            self._last_status_text = text
            self.status_label.configure(text=text)
        if btn_text is not None:
            sig = (btn_text, btn_bg, btn_state)
            if sig != self._last_btn_signature:
                self._last_btn_signature = sig
                self.action_btn.configure(text=btn_text, bg=btn_bg, state=btn_state)

    def _refresh_ui(self):
        if self.error_message:
            state = "error"
            self._set_status_ui(DANGER, f"Fehler: {self.error_message[:55]}")
        elif self.dictation is None:
            state = "loading"
            self._set_status_ui(ACCENT, self.status_message)
        else:
            state = self.dictation.state
            if self.backend is not None and self.backend.name != self._last_backend_text:
                self._last_backend_text = self.backend.name
                self.backend_label.configure(text=self.backend.name)

            hotkey = self.cfg["hotkey"]["key"]
            mode = self.cfg["hotkey"].get("mode", "toggle")
            mode_short = "Gedrückt halten" if mode == "hold" else "1x drücken"

            if state == "idle":
                self._set_status_ui(
                    SUCCESS,
                    f"Bereit  •  Hotkey: [{hotkey}] ({mode_short})",
                    "🎙 Aufnahme starten",
                    ACCENT,
                    "normal",
                )
            elif state == "recording":
                secs = self.dictation.recording_seconds
                self._set_status_ui(
                    DANGER,
                    f"🔴 Aufnahme läuft … ({secs:.1f}s)",
                    "⏹ Stopp & Einfügen",
                    DANGER,
                    "normal",
                )
            elif state == "transcribing":
                if getattr(self.dictation, "polishing", 0) > 0:
                    self._set_status_ui(
                        ACCENT,
                        "✨ KI optimiert Text …",
                        "✨ KI optimiert …",
                        ACCENT,
                        "disabled",
                    )
                else:
                    self._set_status_ui(
                        WARNING,
                        "⏳ Transkribiere Audio …",
                        "⏳ Bitte warten …",
                        WARNING,
                        "disabled",
                    )

            width = max(1, self.level_canvas.winfo_width())
            lvl = self.dictation.current_level if state == "recording" else 0.0
            bar_w = int(width * min(1.0, lvl))
            bar_color = DANGER if lvl > 0.85 else SUCCESS
            self.level_canvas.coords(self.level_bar, 0, 0, bar_w, 6)
            self.level_canvas.itemconfig(self.level_bar, fill=bar_color)

            self.rebuild_history_list(force=False)

        if state != self.shown_state:
            self.shown_state = state
            if self.tray_icon is not None:
                try:
                    self.tray_icon.icon = create_tray_image(state)
                except Exception:
                    pass

    def _start_tray(self):
        def on_open(_icon, _item):
            self.ui_queue.put(self.show_window)

        def on_toggle(_icon, _item):
            self.manual_toggle_recording()

        def on_copy_last(_icon, _item):
            if self.dictation and self.dictation.history_entries:
                pyperclip.copy(self.dictation.history_entries[-1]["text"])

        def on_toggle_llm(_icon, _item):
            new_state = not bool(self.cfg.get("llm", {}).get("enabled", False))
            self.cfg.setdefault("llm", {})["enabled"] = new_state
            dictate.save_llm_enabled(new_state)
            self.ui_queue.put(
                lambda: (self.llm_enabled_var.set(new_state), self._update_llm_badge())
            )

        def on_toggle_autostart(_icon, _item):
            new_state = not dictate.is_autostart_enabled()
            dictate.set_autostart(new_state, mac_script="app.py")
            self.ui_queue.put(lambda: self.autostart_var.set(dictate.is_autostart_enabled()))

        def on_quit(_icon, _item):
            self.ui_queue.put(self.quit_app)

        menu = pystray.Menu(
            pystray.MenuItem("Dashboard öffnen", on_open, default=True),
            pystray.MenuItem("Aufnahme Start / Stopp", on_toggle),
            pystray.MenuItem("Letztes Transkript kopieren", on_copy_last),
            pystray.MenuItem(
                "✨ KI-Nachbearbeitung (OpenRouter)",
                on_toggle_llm,
                checked=lambda _item: bool(self.cfg.get("llm", {}).get("enabled", False)),
            ),
            pystray.MenuItem(
                "Beim Login starten (Autostart)",
                on_toggle_autostart,
                checked=lambda _item: dictate.is_autostart_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Beenden", on_quit),
        )
        self.tray_icon = pystray.Icon(
            "whisper_flow_local",
            create_tray_image("loading"),
            "Whisper Flow Local",
            menu,
        )
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def on_window_close(self):
        if dictate.IS_WINDOWS and self.tray_icon is not None:
            self.root.withdraw()
        elif dictate.IS_MAC:
            self.root.iconify()
        else:
            self.quit_app()

    def open_config_file(self):
        try:
            if dictate.IS_MAC:
                subprocess.run(["open", "-t", str(dictate.CONFIG_PATH)])
            elif dictate.IS_WINDOWS:
                os.startfile(str(dictate.CONFIG_PATH))
        except Exception:
            pass

    def quit_app(self):
        self.quitting = True
        if self.listener is not None:
            self.listener.stop()
            self.listener = None
        if self.backend is not None:
            self.backend.close()
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    minimized = "--minimized" in sys.argv
    app = DiktatFrontend(start_minimized=minimized)
    app.run()
