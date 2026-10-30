#!/usr/bin/env bash
cd "$(dirname "$0")"

# Unabhaengig vom Terminal starten, damit dessen Fenster geschlossen werden kann.
nohup ./start.sh --menubar > diktat.log 2>&1 < /dev/null &
echo "Diktat wurde im Hintergrund gestartet. Dieses Fenster kann geschlossen werden."
