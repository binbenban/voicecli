#!/bin/bash
# voicecli hotkey handler — called by a herdr [[keys.command]] binding.
# herdr's key-command env exposes HERDR_ACTIVE_PANE_ID (not $1); interactive
# shells use HERDR_PANE_ID. First press records; second press stops + injects.
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="${DIR}/.venv/bin/python"
MAIN="${DIR}/main.py"

PANE="${HERDR_ACTIVE_PANE_ID:-$HERDR_PANE_ID}"
SAFE=$(echo "$PANE" | tr ':.' '_')
PIDFILE="${DIR}/.voicecli-rec-${SAFE}.pid"

if [ -f "$PIDFILE" ]; then
    # Debounce: don't stop if recording started less than 2 seconds ago.
    # Prevents an accidental double-press from cutting off speech.
    START=$(stat -c %Y "$PIDFILE" 2>/dev/null || echo 0)
    NOW=$(date +%s)
    if [ "$((NOW - START))" -lt 2 ]; then
        exit 0
    fi
    $PY $MAIN --stop --pane-id "$PANE"
else
    $PY $MAIN --herdr-target "$PANE"
fi
