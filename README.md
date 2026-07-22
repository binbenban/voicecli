# voicecli

Terminal-native voice input for WSL. Press a key, speak, press again — cleaned
text lands on your current terminal prompt. No GUI, no always-listening
assistant. Works inside Claude Code, Aider, shells, REPLs — anything running in
a herdr pane.

```
> █
        Ctrl-b t, speak, Ctrl-b t
> Explain why this SQL query is slow.█
```

## Setup

One script does everything (system deps, venv, model download, config):

```bash
./setup.sh              # default model: small
# ./setup.sh base       # faster, less accurate
# ./setup.sh medium     # more accurate, slower on CPU
```

Then install the hotkey from inside herdr:

```bash
.venv/bin/python main.py --install-hotkey
```

This writes a `[[keys.command]]` block to `~/.config/herdr/config.toml` and
reloads the server, so it persists across sessions. Press **`Ctrl-b t`** in any
pane to dictate. That's it.

## Use

- **`Ctrl-b t`** — start recording. A toast shows 🎤 listening.
- Speak. Take your time (up to `max_duration`, default 120s).
- **`Ctrl-b t`** again — stop. Shows ✍️ transcribing, then ✅ inserted.
- Text appears at your prompt. Review it, press Enter yourself.

The same key toggles start/stop. No pause-detection — you decide when done.

### From the shell (`$(voice)`)

For launching a CLI *with* dictated text:

```bash
codex "$(voice)"
git commit -m "$(voice)"
```

`voice` records, transcribes, prints to stdout. Add it to PATH:
`ln -s "$PWD/voice" ~/.local/bin/voice`.

## How it works

```
Ctrl-b t ─► SoX record ─► WAV ─► Whisper transcribe ─► clean ─► herdr inject ─► prompt
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
| `injector.py` | Types text into the herdr pane (`herdr pane send-text`) |
| `hotkey.py` | Installs the herdr `[[keys.command]]` binding |
| `voice` | `$(voice)` launcher |
| `config.py` / `config.yaml` | All settings |

The daemon starts automatically on first dictation and holds the model resident.
It reloads when you change `model:` in `config.yaml` and idles out after 15 min.

## Config

Everything lives in `config.yaml`. Common knobs:

| Key | Default | What |
|-----|---------|------|
| `model` | `models/small` | Model dir (local) or name. `small` is the CPU sweet spot. |
| `hotkey` / `hotkey_prefix` | `t` / `true` | Key, and whether it's a prefix key (`Ctrl-b t`). |
| `use_daemon` | `true` | Keep model warm for fast repeat presses. |
| `stop_on_silence` | `false` | `true` = auto-stop on pause instead of press-to-stop. |
| `mic_warmup` | `0.5` | Seconds before "listening" shows, so first words aren't clipped. |
| `max_duration` | `120` | Max recording length (seconds). |

The 🎤/✍️/✅ toasts need herdr notifications on: set `delivery = "herdr"` under
`[ui.toast]` in `config.toml`. They auto-dismiss on `ui.toast.delay_seconds`
(default 1s) — bump it to a few seconds so "listening" lingers.

## Requirements

- WSL (or Linux) with a working mic (WSLg exposes it via PulseAudio)
- `herdr`, and `sox` (installed by `setup.sh`)
- Python 3.10+

## Notes

- **Why herdr, not a global hotkey?** Inside WSL there's no evdev / TIOCSTI, so a
  global hotkey or fake keystrokes can't work. herdr sees every keypress in its
  panes and `pane send-text` types into the prompt without OS-level injection.
  Auto-detected via `$HERDR_ENV`. Note herdr's default keys — `v` (split),
  `h/j/k/l` (focus) are taken; `t` is free.
- **Model downloads use `wget`, not the HF library** — HF's xet CDN returns 403
  on these blobs. `setup.sh` fetches weights directly.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Ctrl-b t` does nothing | Re-run `--install-hotkey`, or `herdr server reload-config`. |
| No status toasts | Enable herdr notifications: `delivery = "herdr"` under `[ui.toast]`. |
| First words cut off | Raise `mic_warmup` in config. |
| Slow per press | Use `small`; the daemon skips reload but medium inference is slow on CPU. |
| No mic | Check `pactl list short sources`; set `sox_input_device` |
