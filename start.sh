#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  echo "Erstelle virtuelle Umgebung und installiere Abhaengigkeiten ..."
  python3 -m venv .venv
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
