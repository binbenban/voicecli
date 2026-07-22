"""Warm-model transcription daemon (Phase 9).

Every hotkey press spawns a fresh `main.py`, and loading the Whisper model from
disk costs several seconds — 10s+ for `medium`. That cold load dominates each
dictation. This daemon pays it once: it holds the model resident in a
long-lived process and answers transcription requests over a unix socket, so
each press only pays for inference (~1-2s).

Protocol (newline-delimited JSON, one request per connection):
    -> {"audio": "/abs/path.wav"}
    <- {"text": "..."}  or  {"error": "..."}

The daemon reloads the model when config's ``model`` changes, so switching
models in config.yaml just works without manually restarting it. It idles out
after ``daemon_idle_timeout`` seconds with no requests, so it doesn't hold
gigabytes of RAM forever.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path

from config import DAEMON_SOCKET, Config, load_config
from transcriber import Transcriber

logger = logging.getLogger(__name__)


def _serve(config: Config) -> None:
    """Run the accept loop until the idle timeout elapses."""
    # Load the model once up front so the first client is already warm.
    tr = Transcriber(config)
    loaded_model = config.model
    tr._ensure_model()  # warm now, not on first request
    logger.info("Daemon ready with model %r on %s", loaded_model, DAEMON_SOCKET)

    DAEMON_SOCKET.unlink(missing_ok=True)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(DAEMON_SOCKET))
    srv.listen(5)  # buffer multiple clients; serialize inference with lock
    srv.settimeout(config.daemon_idle_timeout)

    infer_lock = threading.Lock()  # serialize CPU-bound Whisper inference

    try:
        while True:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                logger.info("Idle for %ss, shutting down", config.daemon_idle_timeout)
                return
            with conn:
                try:
                    raw = _recv_line(conn)
                    if not raw:
                        _send(conn, {"error": "empty request"})
                        continue
                    req = json.loads(raw)
                    audio = Path(req["audio"])
                    # Reload if config's model changed since we loaded.
                    fresh = load_config()
                    if fresh.model != loaded_model:
                        logger.info("Model changed %r -> %r, reloading",
                                    loaded_model, fresh.model)
                        tr = Transcriber(fresh)
                        tr._ensure_model()
                        loaded_model = fresh.model
                    with infer_lock:
                        text = tr.transcribe(audio)
                    _send(conn, {"text": text})
                except json.JSONDecodeError as exc:
                    logger.error("Malformed JSON from client: %s", exc)
                    _send(conn, {"error": f"malformed JSON: {exc}"})
                except Exception as exc:  # never let one bad request kill the daemon
                    logger.error("Request failed: %s", exc)
                    _send(conn, {"error": str(exc)})
    finally:
        srv.close()
        DAEMON_SOCKET.unlink(missing_ok=True)


def _recv_line(conn: socket.socket) -> str:
    """Read one newline-terminated message."""
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = conn.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf.decode("utf-8").strip()


def _send(conn: socket.socket, obj: dict) -> None:
    conn.sendall((json.dumps(obj) + "\n").encode("utf-8"))


def transcribe_via_daemon(config: Config, audio: Path, timeout: float = 120.0) -> str | None:
    """Ask a running daemon to transcribe ``audio``.

    Returns the text, or None if no daemon is reachable (caller should then
    transcribe locally and/or start the daemon). Raises RuntimeError if the
    daemon answered with an error.
    """
    if not DAEMON_SOCKET.exists():
        return None
    try:
        cli = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        cli.settimeout(timeout)
        cli.connect(str(DAEMON_SOCKET))
    except OSError:
        # Stale socket file (daemon died). Clean it up so a fresh one can bind.
        DAEMON_SOCKET.unlink(missing_ok=True)
        return None
    with cli:
        _send(cli, {"audio": str(audio)})
        resp = json.loads(_recv_line(cli))
    if "error" in resp:
        raise RuntimeError(resp["error"])
    return resp["text"]


def spawn_daemon() -> None:
    """Start the daemon detached, if not already running. Cheap no-op if the
    socket already exists (a live daemon is listening on it)."""
    if DAEMON_SOCKET.exists():
        return
    import subprocess

    py = sys.executable
    subprocess.Popen(
        [py, str(Path(__file__).resolve())],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,  # detach: survives the spawning process exit
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s daemon: %(message)s")
    for noisy in ("httpx", "httpcore", "filelock", "urllib3", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _serve(load_config())
    return 0


if __name__ == "__main__":
    sys.exit(main())
