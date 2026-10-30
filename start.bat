@echo off
cd /d "%~dp0"

if not exist .venv (
    echo Erstelle virtuelle Umgebung und installiere Abhaengigkeiten ...
    py -3 -m venv .venv
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

python dictate.py
pause
