#!/usr/bin/env python3
"""Minimal HTTP job runner for the unraid pokemon-champions-gpu container.

Mirrors the ColePC ``scripts/job_runner.py`` API for training jobs only —
no OCR, no detector debug, no Windows-isms.

API
    POST /run            — {"command": "python -m ..."}; spawns subprocess
    GET  /status         — current job + history (last 20)
    GET  /log?lines=200  — tail current/most-recent job log
    POST /kill           — kill the current job (SIGTERM, then SIGKILL)
    GET  /health         — {"ok": true}

The runner stores job logs in /workspace/data/job_logs/<job_id>.log and runs
training jobs in /workspace as cwd. PYTHONUNBUFFERED=1 is set so prints flush.

Designed to be the container's ENTRYPOINT. If the container restarts (OOM,
crash), the runner comes back up; in-flight training subprocesses do not
auto-resume — callers should re-submit with --resume.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("JOB_RUNNER_PORT", 8422))
WORK_DIR = Path(os.environ.get("WORK_DIR", "/workspace"))
LOG_DIR = WORK_DIR / "data" / "job_logs"
HISTORY_LIMIT = 20

_lock = threading.Lock()
_current: dict = {
    "running": False,
    "command": None,
    "pid": None,
    "start_time": None,
    "log_file": None,
    "job_id": None,
}
_history: deque[dict] = deque(maxlen=HISTORY_LIMIT)
_process: subprocess.Popen | None = None


def _send_json(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _read_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", 0) or 0)
    if length == 0:
        return {}
    return json.loads(handler.rfile.read(length))


def _monitor(proc: subprocess.Popen, log_fh, job_id: str):
    """Wait for the subprocess and clean up state when it exits."""
    rc = proc.wait()
    log_fh.flush()
    log_fh.close()
    with _lock:
        global _process
        if _current.get("job_id") == job_id:
            _history.appendleft({
                "job_id": job_id,
                "command": _current["command"],
                "start_time": _current["start_time"],
                "end_time": time.time(),
                "return_code": rc,
                "log_file": _current["log_file"],
            })
            _current.update({
                "running": False,
                "command": None,
                "pid": None,
                "start_time": None,
            })
            _process = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Suppress default logging — keep stderr clean for the container.
        pass

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/health":
            return _send_json(self, {"ok": True})

        if url.path == "/status":
            with _lock:
                return _send_json(self, {
                    "current": dict(_current),
                    "history": list(_history),
                })

        if url.path == "/log":
            qs = parse_qs(url.query)
            lines = int(qs.get("lines", ["200"])[0])
            with _lock:
                log_file = _current.get("log_file")
                if not log_file and _history:
                    log_file = _history[0].get("log_file")
            if not log_file or not Path(log_file).exists():
                return _send_json(self, {"lines": [], "log_file": log_file})
            try:
                with open(log_file, "r", errors="replace") as f:
                    all_lines = f.readlines()
                tail = all_lines[-lines:]
                return _send_json(self, {
                    "lines": [l.rstrip() for l in tail],
                    "total_lines": len(all_lines),
                    "log_file": log_file,
                })
            except Exception as e:
                return _send_json(self, {"error": str(e)}, 500)

        return _send_json(self, {"error": "not found"}, 404)

    def do_POST(self):
        url = urlparse(self.path)
        if url.path == "/run":
            return self._handle_run()
        if url.path == "/kill":
            return self._handle_kill()
        return _send_json(self, {"error": "not found"}, 404)

    def _handle_run(self):
        body = _read_body(self)
        command = body.get("command", "")
        if not command:
            return _send_json(self, {"error": "no command provided"}, 400)

        with _lock:
            if _current["running"]:
                return _send_json(self, {
                    "error": "job already running",
                    "current": dict(_current),
                }, 409)

        global _process
        job_id = f"job_{int(time.time())}"
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = str(LOG_DIR / f"{job_id}.log")

        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            log_fh = open(log_file, "w")
            proc = subprocess.Popen(
                command,
                shell=True,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                cwd=str(WORK_DIR),
                env=env,
                preexec_fn=os.setsid,  # process group so kill takes children too
            )
            with _lock:
                _process = proc
                _current.update({
                    "running": True,
                    "command": command,
                    "pid": proc.pid,
                    "start_time": time.time(),
                    "log_file": log_file,
                    "job_id": job_id,
                })
            threading.Thread(
                target=_monitor, args=(proc, log_fh, job_id), daemon=True,
            ).start()
            return _send_json(self, {
                "ok": True, "job_id": job_id, "pid": proc.pid, "log_file": log_file,
            })
        except Exception as e:
            try:
                log_fh.close()
            except Exception:
                pass
            return _send_json(self, {"error": str(e)}, 500)

    def _handle_kill(self):
        global _process
        with _lock:
            if not _current["running"] or _process is None:
                return _send_json(self, {"error": "no job running"}, 400)
            proc = _process
            job_id = _current["job_id"]
            pgid = os.getpgid(proc.pid)

        try:
            os.killpg(pgid, signal.SIGTERM)
            time.sleep(2)
            if proc.poll() is None:
                os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass

        return _send_json(self, {"ok": True, "killed": job_id})


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Container Job Runner listening on http://0.0.0.0:{PORT}", flush=True)
    print(f"  WORK_DIR: {WORK_DIR}", flush=True)
    print(f"  LOG_DIR : {LOG_DIR}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", flush=True)


if __name__ == "__main__":
    main()
