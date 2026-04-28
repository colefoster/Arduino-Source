"""ColePC Job Runner — persistent task executor for remote GPU training.

Runs in the user's desktop session (so CUDA works). Accepts jobs via
HTTP over Tailscale. Designed to start at Windows login and stay alive.

Usage:
    python scripts/job_runner.py

Endpoints:
    POST /run     — submit a job (command string or bat file path)
    GET  /status  — current job status + recent history
    GET  /log     — tail the current job's output
    POST /kill    — kill the current job

Only listens on 0.0.0.0:8422 — use Tailscale IP from other machines.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

WORK_DIR = Path(r"C:\Dev\pokemon-champions")
LOG_DIR = WORK_DIR / "data" / "job_logs"
PORT = 8422

# State
_lock = threading.Lock()
_current: dict = {"running": False, "command": None, "pid": None, "start_time": None, "log_file": None}
_history: deque = deque(maxlen=20)
_process: subprocess.Popen | None = None


class JobHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress default logging

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        if self.path == "/status":
            self._handle_status()
        elif self.path.startswith("/log"):
            self._handle_log()
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/run":
            self._handle_run()
        elif self.path == "/kill":
            self._handle_kill()
        else:
            self._send_json({"error": "not found"}, 404)

    def _handle_status(self):
        with _lock:
            # Check if process is still alive
            if _current["running"] and _process is not None:
                ret = _process.poll()
                if ret is not None:
                    _finish_job(ret)

            self._send_json({
                "current": dict(_current),
                "history": list(_history),
            })

    def _handle_log(self):
        lines = 50
        # Parse ?lines=N
        if "?" in self.path:
            qs = self.path.split("?", 1)[1]
            for part in qs.split("&"):
                if part.startswith("lines="):
                    try:
                        lines = int(part.split("=")[1])
                    except ValueError:
                        pass

        with _lock:
            log_file = _current.get("log_file")

        if not log_file or not Path(log_file).exists():
            self._send_json({"lines": [], "log_file": log_file})
            return

        try:
            with open(log_file, "r", errors="replace") as f:
                all_lines = f.readlines()
            tail = all_lines[-lines:]
            self._send_json({"lines": [l.rstrip() for l in tail], "total_lines": len(all_lines)})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_run(self):
        body = self._read_body()
        command = body.get("command", "")

        if not command:
            self._send_json({"error": "no command provided"}, 400)
            return

        with _lock:
            if _current["running"]:
                self._send_json({"error": "job already running", "current": dict(_current)}, 409)
                return

        # Start the job
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
            )

            global _process
            with _lock:
                _process = proc
                _current.update({
                    "running": True,
                    "job_id": job_id,
                    "command": command,
                    "pid": proc.pid,
                    "start_time": time.time(),
                    "log_file": log_file,
                })

            # Monitor in background thread
            t = threading.Thread(target=_monitor_job, args=(proc, log_fh, job_id), daemon=True)
            t.start()

            self._send_json({"ok": True, "job_id": job_id, "pid": proc.pid, "log_file": log_file})

        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_kill(self):
        global _process
        with _lock:
            if not _current["running"] or _process is None:
                self._send_json({"error": "no job running"}, 404)
                return
            try:
                _process.kill()
                self._send_json({"ok": True, "killed": _current.get("job_id")})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)


def _monitor_job(proc: subprocess.Popen, log_fh, job_id: str):
    """Wait for process to finish and update state."""
    ret = proc.wait()
    log_fh.close()
    with _lock:
        _finish_job(ret)


def _finish_job(return_code: int):
    """Mark current job as finished (caller must hold _lock)."""
    global _process
    _history.appendleft({
        "job_id": _current.get("job_id"),
        "command": _current.get("command"),
        "start_time": _current.get("start_time"),
        "end_time": time.time(),
        "return_code": return_code,
        "log_file": _current.get("log_file"),
    })
    _current.update({
        "running": False,
        "command": None,
        "pid": None,
        "start_time": None,
        "log_file": _current.get("log_file"),  # keep for /log access
    })
    _process = None


def main():
    print(f"ColePC Job Runner starting on port {PORT}...")
    print(f"Work directory: {WORK_DIR}")
    print(f"Log directory: {LOG_DIR}")

    server = HTTPServer(("0.0.0.0", PORT), JobHandler)
    print(f"Listening on http://0.0.0.0:{PORT}")
    print(f"  POST /run    — submit a job")
    print(f"  GET  /status — check status")
    print(f"  GET  /log    — tail output")
    print(f"  POST /kill   — kill current job")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
