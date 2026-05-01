#!/usr/bin/env python3
"""Mac-local dev runner for the dashboard Inspector.

Tiny synchronous HTTP server on localhost:9876 (binds 0.0.0.0 so the
dashboard on ash can also reach it via Tailscale). All endpoints just
shell out to build_mac/SerialProgramsCommandLine and parse the first
JSON line of stdout. No queueing, no job state.

Endpoints:
    POST /retest                 — rebuild + run --manifest-regression
    POST /ocr-suggest            — run one reader on one image
    POST /ocr-crop               — run number-tuned OCR on a box
    POST /detector-debug         — run all detectors on one image
    POST /detector-debug-batch   — run all detectors on every image in a screen dir
    GET  /health

Run once in a terminal:

    python3 tools/mac_dev_runner.py
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUILD = REPO / "build_mac"
EXE = BUILD / "SerialProgramsCommandLine"
TEST_IMAGES = REPO / "test_images"
TMP_DIR = REPO / "data"
PORT = 9876


def _build():
    proc = subprocess.run(
        ["cmake", "--build", str(BUILD), "--target", "SerialProgramsCommandLine", "-j", "10"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    return proc.returncode == 0, proc.stdout + proc.stderr


def _regress():
    if not EXE.exists():
        return False, f"executable not found at {EXE}", ""
    proc = subprocess.run(
        [str(EXE), "--manifest-regression", str(TEST_IMAGES)],
        capture_output=True, text=True,
    )
    return True, proc.stdout, proc.stderr


_TABLE_ROW = re.compile(r"║\s*([A-Za-z_][A-Za-z0-9_]*)\s*║\s*(\d+)/(\d+)\s*║\s*\d+\s*║\s*([\d.]+)%\s*║")
_FAIL_ROW = re.compile(r"FAIL\s+(\S+)\s+←\s+(\S+)")


def _parse_regression(stdout: str):
    detectors = []
    for m in _TABLE_ROW.finditer(stdout):
        if m.group(1) == "OVERALL":
            continue
        detectors.append({
            "name": m.group(1),
            "passed": int(m.group(2)),
            "total": int(m.group(3)),
            "pct": float(m.group(4)),
        })
    failures = [{"detector": m.group(1), "image": m.group(2)} for m in _FAIL_ROW.finditer(stdout)]
    overall_match = re.search(r"║\s*OVERALL\s*║\s*(\d+)/(\d+)", stdout)
    overall = None
    if overall_match:
        overall = {"passed": int(overall_match.group(1)), "total": int(overall_match.group(2))}
    return {"detectors": detectors, "failures": failures, "overall": overall}


def _parse_first_json_line(stdout: str):
    """Find the first {...} JSON line in stdout. Tolerates leading log lines
    and unescaped backslashes (harmless on Mac, kept for parity)."""
    for line in stdout.strip().split("\n"):
        line = line.strip()
        if line.startswith("{"):
            fixed = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', line)
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                continue
    return None


def _decode_to_tempfile(image_b64: str):
    img_data = base64.b64decode(image_b64)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir=str(TMP_DIR))
    tmp.write(img_data)
    tmp.close()
    return tmp.name


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def do_OPTIONS(self):
        self._send({})

    def do_GET(self):
        if self.path == "/health":
            self._send({"ok": True, "exe_exists": EXE.exists()})
            return
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path
        if path == "/retest":
            self._handle_retest()
        elif path == "/ocr-suggest":
            self._handle_ocr_suggest()
        elif path == "/ocr-crop":
            self._handle_ocr_crop()
        elif path == "/detector-debug":
            self._handle_detector_debug()
        elif path == "/detector-debug-batch":
            self._handle_detector_debug_batch()
        else:
            self._send({"error": "not found"}, 404)

    def _handle_retest(self):
        ok, build_log = _build()
        if not ok:
            self._send({"ok": False, "stage": "build", "log": build_log[-4000:]})
            return
        ran, stdout, stderr = _regress()
        if not ran:
            self._send({"ok": False, "stage": "regress", "log": stdout})
            return
        parsed = _parse_regression(stdout)
        self._send({"ok": True, "stage": "done", "result": parsed, "raw_tail": stdout[-2000:]})

    def _handle_ocr_suggest(self):
        body = self._read_body()
        image_b64 = body.get("image_base64", "")
        reader = body.get("reader", "")
        screen = body.get("screen", "")
        if not image_b64 or not reader:
            self._send({"error": "image_base64 and reader required"}, 400)
            return
        if not EXE.exists():
            self._send({"error": f"executable not found: {EXE}"}, 500)
            return

        tmp_path = None
        try:
            tmp_path = _decode_to_tempfile(image_b64)
            result = subprocess.run(
                [str(EXE), "--ocr-suggest", reader, tmp_path],
                capture_output=True, text=True, timeout=30, cwd=str(BUILD),
            )
            if result.returncode != 0:
                self._send({
                    "error": "OCR failed",
                    "stderr": (result.stderr or "")[-500:],
                    "stdout": (result.stdout or "")[-500:],
                }, 500)
                return
            ocr_result = _parse_first_json_line(result.stdout) or {"raw": result.stdout.strip()}
            self._send({"ok": True, "reader": reader, "screen": screen, "result": ocr_result})
        except subprocess.TimeoutExpired:
            self._send({"error": "OCR timed out"}, 500)
        except Exception as e:
            self._send({"error": str(e)}, 500)
        finally:
            if tmp_path:
                try: os.unlink(tmp_path)
                except OSError: pass

    def _handle_ocr_crop(self):
        body = self._read_body()
        image_b64 = body.get("image_base64", "")
        try:
            x = float(body.get("x", 0)); y = float(body.get("y", 0))
            w = float(body.get("w", 0)); h = float(body.get("h", 0))
        except (TypeError, ValueError):
            self._send({"error": "x,y,w,h must be numbers"}, 400)
            return
        if not image_b64 or w <= 0 or h <= 0:
            self._send({"error": "image_base64 and positive w,h required"}, 400)
            return
        if not EXE.exists():
            self._send({"error": f"executable not found: {EXE}"}, 500)
            return

        tmp_path = None
        try:
            tmp_path = _decode_to_tempfile(image_b64)
            result = subprocess.run(
                [str(EXE), "--ocr-crop", tmp_path, str(x), str(y), str(w), str(h)],
                capture_output=True, text=True, timeout=15, cwd=str(BUILD),
            )
            if result.returncode != 0:
                self._send({"error": "OCR failed", "stderr": (result.stderr or "")[-500:]}, 500)
                return
            ocr_result = _parse_first_json_line(result.stdout) or {"raw": result.stdout.strip()}
            self._send({"ok": True, "result": ocr_result})
        except subprocess.TimeoutExpired:
            self._send({"error": "OCR timed out"}, 500)
        except Exception as e:
            self._send({"error": str(e)}, 500)
        finally:
            if tmp_path:
                try: os.unlink(tmp_path)
                except OSError: pass

    def _handle_detector_debug(self):
        body = self._read_body()
        image_b64 = body.get("image_base64", "")
        if not image_b64:
            self._send({"error": "image_base64 required"}, 400)
            return
        if not EXE.exists():
            self._send({"error": f"executable not found: {EXE}"}, 500)
            return

        tmp_path = None
        try:
            tmp_path = _decode_to_tempfile(image_b64)
            result = subprocess.run(
                [str(EXE), "--detector-debug", tmp_path],
                capture_output=True, text=True, timeout=30, cwd=str(BUILD),
            )
            if result.returncode != 0:
                self._send({"error": "debug failed", "stderr": (result.stderr or "")[-500:]}, 500)
                return
            debug_result = _parse_first_json_line(result.stdout) or {"raw": result.stdout.strip()}
            self._send({"ok": True, "result": debug_result})
        except subprocess.TimeoutExpired:
            self._send({"error": "timed out"}, 500)
        except Exception as e:
            self._send({"error": str(e)}, 500)
        finally:
            if tmp_path:
                try: os.unlink(tmp_path)
                except OSError: pass

    def _handle_detector_debug_batch(self):
        body = self._read_body()
        screen = body.get("screen", "")
        screen_dir = body.get("screen_dir", "")
        if not screen_dir and screen:
            screen_dir = str(TEST_IMAGES / screen)
        if not screen_dir:
            self._send({"error": "screen or screen_dir required"}, 400)
            return
        screen_path = Path(screen_dir)
        if not screen_path.exists():
            self._send({"error": f"directory not found: {screen_dir}"}, 404)
            return
        if not EXE.exists():
            self._send({"error": f"executable not found: {EXE}"}, 500)
            return

        images = sorted(f for f in screen_path.iterdir() if f.suffix.lower() == ".png" and not f.name.startswith("_"))
        results = {}
        for img_path in images:
            try:
                result = subprocess.run(
                    [str(EXE), "--detector-debug", str(img_path)],
                    capture_output=True, text=True, timeout=15, cwd=str(BUILD),
                )
                parsed = _parse_first_json_line(result.stdout)
                if parsed and "detectors" in parsed:
                    results[img_path.name] = {"detectors": parsed["detectors"]}
                else:
                    results[img_path.name] = {"error": "parse failed"}
            except subprocess.TimeoutExpired:
                results[img_path.name] = {"error": "timeout"}
            except Exception as e:
                results[img_path.name] = {"error": str(e)}
        self._send({"ok": True, "count": len(results), "results": results})


def main():
    print(f"mac_dev_runner listening on http://0.0.0.0:{PORT}")
    print("  /retest                 -> rebuild + run manifest-regression")
    print("  /ocr-suggest            -> run one reader on one image")
    print("  /ocr-crop               -> run number-tuned OCR on a box")
    print("  /detector-debug         -> run all detectors on one image")
    print("  /detector-debug-batch   -> run all detectors on every image in a screen")
    print("  /health                 -> sanity check")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
