#!/usr/bin/env bash
# One-shot setup for voicecli. Idempotent — safe to re-run.
#   ./setup.sh            # default model: small
#   ./setup.sh base       # or base / medium / etc.
set -euo pipefail
cd "$(dirname "$0")"
MODEL="${1:-small}"

echo "==> System deps (sox, tmux)"
if ! command -v rec >/dev/null || ! command -v tmux >/dev/null; then
  sudo apt update && sudo apt install -y sox tmux
fi

echo "==> Python venv + packages"
[ -d .venv ] || uv venv .venv
uv pip install -r requirements.txt

echo "==> Whisper model: $MODEL"
# Download weights directly (HF's xet CDN 403s on these blobs). Skip if present.
DEST="models/$MODEL"
if [ ! -s "$DEST/model.bin" ]; then
  mkdir -p "$DEST"
  BASE="https://huggingface.co/Systran/faster-whisper-$MODEL/resolve/main"
  for f in model.bin config.json tokenizer.json vocabulary.txt; do
    echo "    fetching $f"
    wget -q -O "$DEST/$f" "$BASE/$f"
  done
fi
# Point config at the local model dir.
sed -i "s#^model:.*#model: models/$MODEL#" config.yaml

echo "==> Installing tmux hotkey"
chmod +x hotkey.sh
if [ -n "${TMUX:-}" ]; then
  .venv/bin/python main.py --install-hotkey
  echo "    Persist across sessions by adding this to ~/.tmux.conf:"
  echo "    $ (.venv/bin/python -c 'from config import load_config; from hotkey import HotkeyInstaller; print(HotkeyInstaller(load_config()).config_line())')"
else
  echo "    Run inside tmux, then: .venv/bin/python main.py --install-hotkey"
fi

echo "==> Done. Press Ctrl-b v in any pane to dictate."
