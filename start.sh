#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN="python3"
if [[ "${1:-}" != "--cli" && "${1:-}" != "--menubar" ]]; then
  # Das GUI benoetigt Tkinter. Manche pyenv-Installationen wurden ohne Tk gebaut.
  if ! "$PYTHON_BIN" -c 'import sys, tkinter; assert sys.version_info >= (3, 11)' 2>/dev/null; then
    for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
      if [[ -x "$candidate" ]] && "$candidate" -c 'import sys, tkinter; assert sys.version_info >= (3, 11)' 2>/dev/null; then
        PYTHON_BIN="$candidate"
        break
      fi
    done
  fi

  if ! "$PYTHON_BIN" -c 'import sys, tkinter; assert sys.version_info >= (3, 11)' 2>/dev/null; then
    echo "Fehler: Python 3.11+ mit Tkinter wurde nicht gefunden." >&2
    echo "Bitte Python von python.org installieren und erneut starten." >&2
    exit 1
  fi

  if [[ -d .venv ]] && ! .venv/bin/python -c 'import tkinter' 2>/dev/null; then
    echo "Die vorhandene virtuelle Umgebung hat kein Tkinter und wird neu erstellt ..."
    rm -rf .venv
  fi
fi

if [[ ! -d .venv ]]; then
  echo "Erstelle virtuelle Umgebung und installiere Abhaengigkeiten ..."
  "$PYTHON_BIN" -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -c "import PIL, sounddevice, pyperclip, requests" 2>/dev/null || {
    echo "Aktualisiere Abhaengigkeiten ..."
    python -m pip install -r requirements.txt
  }
fi

echo
echo "Hinweis macOS: Bedienungshilfen (+ ggf. Eingabeueberwachung und Mikrofon)"
echo "fuer Terminal/iTerm/Cursor freigeben, sonst reagiert der Hotkey nicht."
echo

if [[ "${1:-}" == "--cli" ]]; then
  exec python dictate.py
elif [[ "${1:-}" == "--menubar" ]]; then
  exec python menubar.py
else
  exec python app.py
fi
