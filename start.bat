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
    python -c "import PIL, pystray, sounddevice, pyperclip, requests" 2>nul || (
        echo Aktualisiere Abhaengigkeiten ...
        python -m pip install -r requirements.txt
    )
)

if "%1"=="--cli" (
    python dictate.py
    pause
) else (
    start "" .venv\Scripts\pythonw.exe app.py
)
