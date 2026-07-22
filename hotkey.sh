#!/bin/bash
# voicecli hotkey handler — called by a multiplexer keybinding.
#   tmux:  bind-key run-shell '.../hotkey.sh #{pane_id}'  → pane id in $1
#   herdr: [[keys.command]] type="shell"                  → no arg; uses $HERDR_PANE_ID
# All paths derived from this script's location.
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="${DIR}/.venv/bin/python"
MAIN="${DIR}/main.py"

if [ -n "${HERDR_ENV:-}" ]; then
    PANE="${1:-$HERDR_PANE_ID}"
    TARGET_FLAG="--herdr-target"
else
    PANE="$1"
    TARGET_FLAG="--target"
fi

SAFE=$(echo "$PANE" | tr ':.' '_')
PIDFILE="${DIR}/.voicecli-rec-${SAFE}.pid"

if [ -f "$PIDFILE" ]; then
    # Debounce: don't stop if recording started less than 2 seconds ago.
    # Prevents accidental double-press from cutting off speech.
    START=$(stat -c %Y "$PIDFILE" 2>/dev/null || echo 0)
    NOW=$(date +%s)
    ELAPSED=$((NOW - START))
    if [ "$ELAPSED" -lt 2 ]; then
        exit 0
    fi
    $PY $MAIN --stop --pane-id "$PANE"
else
    $PY $MAIN "$TARGET_FLAG" "$PANE"
fi
