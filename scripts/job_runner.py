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
BUILD_DIR = WORK_DIR / "build" / "Release"
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
        elif self.path == "/ocr-suggest":
            self._handle_ocr_suggest()
        elif self.path == "/detector-debug":
            self._handle_detector_debug()
        elif self.path == "/detector-debug-batch":
            self._handle_detector_debug_batch()
        elif self.path == "/ocr-crop":
            self._handle_ocr_crop()
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

    def _handle_ocr_suggest(self):
        """Run C++ OCR reader on a single image, return suggested labels.

        Synchronous — runs the reader and returns immediately.
        Does NOT queue as a job (fast, sub-second operation).

        Body: { "image_base64": "<base64 png>", "reader": "MoveNameReader", "screen": "move_select_singles" }
        Response: { "ok": true, "reader": "...", "result": { ... } }
        """
        import base64
        import tempfile

        body = self._read_body()
        image_b64 = body.get("image_base64", "")
        reader = body.get("reader", "")
        screen = body.get("screen", "")

        if not image_b64 or not reader:
            self._send_json({"error": "image_base64 and reader required"}, 400)
            return

        # Decode image to temp file
        try:
            img_data = base64.b64decode(image_b64)
        except Exception as e:
            self._send_json({"error": f"invalid base64: {e}"}, 400)
            return

        # Write to temp file
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir=str(WORK_DIR / "data"))
        try:
            tmp.write(img_data)
            tmp.close()

            # Run C++ OCR in --ocr-suggest mode
            exe = BUILD_DIR / "SerialProgramsCommandLine.exe"
            if not exe.exists():
                # Try without .exe (for non-Windows)
                exe = BUILD_DIR / "SerialProgramsCommandLine"
            if not exe.exists():
                self._send_json({"error": f"executable not found: {exe}"}, 500)
                return

            result = subprocess.run(
                [str(exe), "--ocr-suggest", reader, tmp.name],
                capture_output=True, text=True, timeout=30,
                cwd=str(BUILD_DIR),
            )

            if result.returncode != 0:
                self._send_json({
                    "error": "OCR failed",
                    "stderr": result.stderr[-500:] if result.stderr else "",
                    "stdout": result.stdout[-500:] if result.stdout else "",
                }, 500)
                return

            # Parse JSON output from C++ (may have log lines before the JSON)
            ocr_result = None
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        ocr_result = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue
            if ocr_result is None:
                ocr_result = {"raw": result.stdout.strip()}

            self._send_json({"ok": True, "reader": reader, "screen": screen, "result": ocr_result})

        except subprocess.TimeoutExpired:
            self._send_json({"error": "OCR timed out"}, 500)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass


    def _handle_ocr_crop(self):
        """Run number-tuned OCR on an arbitrary box of one image.

        Body: { "image_base64": "<base64>", "x": float, "y": float, "w": float, "h": float }
        Response: { "ok": true, "result": {"raw": "...", "current": int, "max": int} }
        """
        import base64
        import tempfile

        body = self._read_body()
        image_b64 = body.get("image_base64", "")
        try:
            x = float(body.get("x", 0))
            y = float(body.get("y", 0))
            w = float(body.get("w", 0))
            h = float(body.get("h", 0))
        except (TypeError, ValueError):
            self._send_json({"error": "x,y,w,h must be numbers"}, 400)
            return

        if not image_b64 or w <= 0 or h <= 0:
            self._send_json({"error": "image_base64 and positive w,h required"}, 400)
            return

        try:
            img_data = base64.b64decode(image_b64)
        except Exception as e:
            self._send_json({"error": f"invalid base64: {e}"}, 400)
            return

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir=str(WORK_DIR / "data"))
        try:
            tmp.write(img_data); tmp.close()

            exe = BUILD_DIR / "SerialProgramsCommandLine.exe"
            if not exe.exists():
                exe = BUILD_DIR / "SerialProgramsCommandLine"
            if not exe.exists():
                self._send_json({"error": f"executable not found: {exe}"}, 500)
                return

            result = subprocess.run(
                [str(exe), "--ocr-crop", tmp.name, str(x), str(y), str(w), str(h)],
                capture_output=True, text=True, timeout=15,
                cwd=str(BUILD_DIR),
            )
            if result.returncode != 0:
                self._send_json({"error": "OCR failed", "stderr": result.stderr[-500:]}, 500)
                return

            ocr_result = None
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        ocr_result = json.loads(line); break
                    except json.JSONDecodeError:
                        continue
            if ocr_result is None:
                ocr_result = {"raw": result.stdout.strip()}
            self._send_json({"ok": True, "result": ocr_result})
        except subprocess.TimeoutExpired:
            self._send_json({"error": "OCR timed out"}, 500)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)
        finally:
            try: os.unlink(tmp.name)
            except OSError: pass


    def _handle_detector_debug(self):
        """Run all detectors on a single image with verbose debug output.

        Body: { "image_base64": "<base64 png>" }
        Response: { "ok": true, "result": { detectors: [...], regions: [...] } }
        """
        import base64
        import tempfile

        body = self._read_body()
        image_b64 = body.get("image_base64", "")

        if not image_b64:
            self._send_json({"error": "image_base64 required"}, 400)
            return

        try:
            img_data = base64.b64decode(image_b64)
        except Exception as e:
            self._send_json({"error": f"invalid base64: {e}"}, 400)
            return

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir=str(WORK_DIR / "data"))
        try:
            tmp.write(img_data)
            tmp.close()

            exe = BUILD_DIR / "SerialProgramsCommandLine.exe"
            if not exe.exists():
                exe = BUILD_DIR / "SerialProgramsCommandLine"
            if not exe.exists():
                self._send_json({"error": f"executable not found: {exe}"}, 500)
                return

            result = subprocess.run(
                [str(exe), "--detector-debug", tmp.name],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=30, cwd=str(BUILD_DIR),
            )
            result.stdout = result.stdout.decode("utf-8", errors="replace")
            result.stderr = result.stderr.decode("utf-8", errors="replace")

            if result.returncode != 0:
                self._send_json({"error": "debug failed", "stderr": result.stderr[-500:]}, 500)
                return

            # Parse JSON from stdout (skip log lines)
            # Note: C++ may output unescaped Windows paths (C:\Dev\...)
            # so we fix backslashes before parsing
            debug_result = None
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line.startswith("{"):
                    # Escape unescaped backslashes in the JSON string
                    # (replace single \ not followed by valid escape chars)
                    import re
                    fixed = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', line)
                    try:
                        debug_result = json.loads(fixed)
                        break
                    except json.JSONDecodeError:
                        continue

            if debug_result is None:
                debug_result = {"raw": result.stdout.strip()}

            self._send_json({"ok": True, "result": debug_result})

        except subprocess.TimeoutExpired:
            self._send_json({"error": "timed out"}, 500)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass


    def _handle_detector_debug_batch(self):
        """Run detectors on all images in a screen directory at once.

        Body: { "screen_dir": "C:\\Dev\\pokemon-champions\\test_images\\post_match" }
              OR { "screen": "post_match" }  (resolved relative to test_images/)
        Response: { "ok": true, "results": { "filename.png": { detectors: [...] } } }

        Runs one C++ invocation per image but in a tight loop without HTTP overhead.
        """
        import re

        body = self._read_body()
        screen = body.get("screen", "")
        screen_dir = body.get("screen_dir", "")

        if not screen_dir and screen:
            screen_dir = str(WORK_DIR / "test_images" / screen)

        if not screen_dir:
            self._send_json({"error": "screen or screen_dir required"}, 400)
            return

        screen_path = Path(screen_dir)
        if not screen_path.exists():
            self._send_json({"error": f"directory not found: {screen_dir}"}, 404)
            return

        exe = BUILD_DIR / "SerialProgramsCommandLine.exe"
        if not exe.exists():
            exe = BUILD_DIR / "SerialProgramsCommandLine"
        if not exe.exists():
            self._send_json({"error": f"executable not found: {exe}"}, 500)
            return

        images = sorted(f for f in screen_path.iterdir() if f.suffix.lower() == ".png" and not f.name.startswith("_"))
        results = {}

        for img_path in images:
            try:
                result = subprocess.run(
                    [str(exe), "--detector-debug", str(img_path)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=15, cwd=str(BUILD_DIR),
                )
                stdout = result.stdout.decode("utf-8", errors="replace")

                parsed = None
                for line in stdout.strip().split("\n"):
                    line = line.strip()
                    if line.startswith("{"):
                        fixed = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', line)
                        try:
                            parsed = json.loads(fixed)
                            break
                        except json.JSONDecodeError:
                            continue

                if parsed and "detectors" in parsed:
                    results[img_path.name] = {
                        "detectors": parsed["detectors"],
                    }
                else:
                    results[img_path.name] = {"error": "parse failed"}

            except subprocess.TimeoutExpired:
                results[img_path.name] = {"error": "timeout"}
            except Exception as e:
                results[img_path.name] = {"error": str(e)}

        self._send_json({"ok": True, "count": len(results), "results": results})


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
