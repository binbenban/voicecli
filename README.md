# voicecli

Terminal-native voice input for WSL. Press a key, speak, press again — cleaned
text lands on your current terminal prompt. No GUI, no always-listening
assistant. Works inside Claude Code, Aider, shells, REPLs — anything running in
a tmux pane.

```
> █
        Ctrl-b v, speak, Ctrl-b v
> Explain why this SQL query is slow.█
```

## Setup

One script does everything (system deps, venv, model download, config):

```bash
./setup.sh              # default model: small
# ./setup.sh base       # faster, less accurate
# ./setup.sh medium     # more accurate, slower on CPU
```

Then install the hotkey in a running tmux server:

```bash
tmux                                        # start / attach tmux
.venv/bin/python main.py --install-hotkey
```

Press **`Ctrl-b v`** in any pane to dictate. That's it.

Make the hotkey permanent — add the line `--install-hotkey` prints to
`~/.tmux.conf`.

## Use

- **`Ctrl-b v`** — start recording. Status line shows 🎤 listening.
- Speak. Take your time (up to `max_duration`, default 120s).
- **`Ctrl-b v`** again — stop. Shows ✍️ transcribing, then ✅ inserted.
- Text appears at your prompt. Review it, press Enter yourself.

The same key toggles start/stop. No pause-detection — you decide when done.

### From the shell (`$(voice)`)

For launching a CLI *with* dictated text (no tmux needed):

```bash
codex "$(voice)"
git commit -m "$(voice)"
```

`voice` records, transcribes, prints to stdout. Add it to PATH:
`ln -s "$PWD/voice" ~/.local/bin/voice`.

## How it works

```
Ctrl-b v ─► SoX record ─► WAV ─► Whisper transcribe ─► clean ─► tmux inject ─► prompt
                                        │
                                  warm-model daemon (holds model in RAM, ~1s/press)
```

| File | Job |
|------|-----|
| `main.py` | CLI, wires the pipeline |
| `recorder.py` | Mic → WAV via SoX; press-to-stop |
| `transcriber.py` | Faster-Whisper speech-to-text |
| `daemon.py` | Keeps the model loaded so each press skips the multi-second load |
| `cleaner.py` | Fillers, punctuation, casing, spoken aliases |
| `injector.py` | Types text into the tmux pane (`send-keys`) |
| `hotkey.py` | Installs the tmux toggle binding |
| `voice` | `$(voice)` launcher |
| `config.py` / `config.yaml` | All settings |

The daemon starts automatically on first dictation and holds the model resident.
It reloads when you change `model:` in `config.yaml` and idles out after 15 min.

## Config

Everything lives in `config.yaml`. Common knobs:

| Key | Default | What |
|-----|---------|------|
| `model` | `models/small` | Model dir (local) or name. `small` is the CPU sweet spot. |
| `hotkey` / `hotkey_prefix` | `v` / `true` | Key, and whether it's a prefix key (`Ctrl-b v`). |
| `use_daemon` | `true` | Keep model warm for fast repeat presses. |
| `stop_on_silence` | `false` | `true` = auto-stop on pause instead of press-to-stop. |
| `mic_warmup` | `0.5` | Seconds before "listening" shows, so first words aren't clipped. |
| `max_duration` | `120` | Max recording length (seconds). |

## Requirements

- WSL (or Linux) with a working mic (WSLg exposes it via PulseAudio)
- `sox`, `tmux` — installed by `setup.sh`
- Python 3.10+

## Notes

- **Why tmux?** Inside WSL there's no evdev / TIOCSTI, so a global hotkey or
  fake keystrokes can't work. tmux sees every keypress in its panes and
  `send-keys` types into the prompt without OS-level injection.
- **Model downloads use `wget`, not the HF library** — HF's xet CDN returns 403
  on these blobs. `setup.sh` fetches weights directly.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Ctrl-b v` does nothing | Re-run `--install-hotkey` (bindings are per tmux server). |
| First words cut off | Raise `mic_warmup` in config. |
| Slow per press | Use `small`; the daemon skips reload but medium inference is slow on CPU. |
| No mic | Check `pactl list short sources`; set `sox_input_device` |
