#!/bin/bash
# voicecli hotkey handler — called by tmux bind-key run-shell
# Receives pane_id as $1
PANE="$1"
SAFE=$(echo "$PANE" | tr ':.' '_')
PIDFILE="/home/bwang/projects/voicecli/.voicecli-rec-${SAFE}.pid"
PY="/home/bwang/projects/voicecli/.venv/bin/python"
MAIN="/home/bwang/projects/voicecli/main.py"
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
    $PY $MAIN --target "$PANE"
fi
