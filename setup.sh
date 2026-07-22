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
# Download weights directly (HF's xet CDN 403s on these blobs). Skip if present.DEST="models/$MOD"
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

echo "==> Done. Next:"
echo "    tmux                                   # start tmux"
echo "    .venv/bin/python main.py --install-hotkey"
echo "    # then press Ctrl-b v in any pane to dictate"
