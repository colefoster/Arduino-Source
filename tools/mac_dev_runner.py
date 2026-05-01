#!/usr/bin/env python3
"""Mac-local dev runner for the dashboard Inspector "Retest" button.

Runs as a tiny HTTP server on localhost:9876. The browser-side dashboard
(opened on this Mac) makes CORS requests directly to localhost, so no
backend proxy is needed — ash never sees the traffic.

Endpoints:
    POST /retest  body {"reader": "OpponentHPReader_Doubles" or null}
        Rebuilds build_mac/SerialProgramsCommandLine, then runs
        --manifest-regression on test_images/. Returns parsed pass/fail
        per detector + the failing-image list.

Run once in a terminal during dev:

    python3 tools/mac_dev_runner.py

Stop with Ctrl+C. Lives outside the dashboard so changes don't affect
the deployed copy on ash.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(REPO, "build_mac")
EXE = os.path.join(BUILD, "SerialProgramsCommandLine")
TEST_IMAGES = os.path.join(REPO, "test_images")
PORT = 9876


def _build():
    proc = subprocess.run(
        ["cmake", "--build", BUILD, "--target", "SerialProgramsCommandLine", "-j", "10"],
        capture_output=True, text=True, cwd=REPO,
    )
    return proc.returncode == 0, proc.stdout + proc.stderr


def _regress():
    if not os.path.exists(EXE):
        return False, "executable not found at " + EXE, []
    proc = subprocess.run(
        [EXE, "--manifest-regression", TEST_IMAGES],
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

    def do_OPTIONS(self):
        self._send({})

    def do_GET(self):
        if self.path == "/health":
            self._send({"ok": True, "exe_exists": os.path.exists(EXE)})
            return
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/retest":
            self._send({"error": "not found"}, 404)
            return

        ok, build_log = _build()
        if not ok:
            self._send({"ok": False, "stage": "build", "log": build_log[-4000:]}, 200)
            return

        ran, stdout, stderr = _regress()
        if not ran:
            self._send({"ok": False, "stage": "regress", "log": stdout}, 200)
            return

        parsed = _parse_regression(stdout)
        self._send({
            "ok": True,
            "stage": "done",
            "result": parsed,
            "raw_tail": stdout[-2000:],
        })


def main():
    print(f"mac_dev_runner listening on http://localhost:{PORT}")
    print(f"  /retest  -> rebuild + run manifest-regression")
    print(f"  /health  -> sanity check")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
