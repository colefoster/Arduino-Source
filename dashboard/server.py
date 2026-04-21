"""Dashboard API server. Receives metrics from ColePC, serves dashboard.

Deploy on ash:
    pip install fastapi uvicorn
    uvicorn dashboard.server:app --host 0.0.0.0 --port 8420
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

DB_PATH = Path(__file__).parent / "dashboard.db"
STATIC_DIR = Path(__file__).parent / "static"
TOKEN = os.environ.get("DASHBOARD_TOKEN", "dev")

app = FastAPI(title="Pokemon Champions Dashboard")

# Serve static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS training_epochs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            epoch INTEGER NOT NULL,
            timestamp REAL NOT NULL,
            train_loss REAL,
            val_loss REAL,
            train_top1 REAL,
            val_top1 REAL,
            train_top3 REAL,
            val_top3 REAL,
            team_acc REAL,
            lead_acc REAL,
            lr REAL,
            best_val_loss REAL,
            UNIQUE(run_id, epoch)
        );
        CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(timestamp);
        CREATE INDEX IF NOT EXISTS idx_epochs_run ON training_epochs(run_id, epoch);
    """)
    conn.close()


init_db()


@app.post("/api/ingest")
async def ingest(request: Request):
    """Receive metrics from ColePC reporter."""
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {TOKEN}":
        raise HTTPException(401, "bad token")

    payload = await request.json()

    conn = get_db()

    # Store snapshot
    conn.execute(
        "INSERT INTO snapshots (timestamp, payload) VALUES (?, ?)",
        (payload.get("timestamp", time.time()), json.dumps(payload)),
    )

    # Store training epochs
    for entry in payload.get("training_history", []):
        try:
            conn.execute("""
                INSERT OR IGNORE INTO training_epochs
                (run_id, epoch, timestamp, train_loss, val_loss, train_top1, val_top1,
                 train_top3, val_top3, team_acc, lead_acc, lr, best_val_loss)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.get("run_id", ""),
                entry.get("epoch", 0),
                entry.get("timestamp", 0),
                entry.get("train_loss"),
                entry.get("val_loss"),
                entry.get("train_top1"),
                entry.get("val_top1"),
                entry.get("train_top3"),
                entry.get("val_top3"),
                entry.get("team_acc"),
                entry.get("lead_acc"),
                entry.get("lr"),
                entry.get("best_val_loss"),
            ))
        except Exception:
            pass

    conn.commit()
    conn.close()

    # Write latest snapshot for fast reads
    latest_path = Path(__file__).parent / "latest.json"
    latest_path.write_text(json.dumps(payload, indent=2))

    return {"status": "ok"}


@app.get("/api/latest")
async def latest():
    """Return the most recent status snapshot."""
    latest_path = Path(__file__).parent / "latest.json"
    if latest_path.exists():
        return JSONResponse(json.loads(latest_path.read_text()))

    # Fallback to DB
    conn = get_db()
    row = conn.execute(
        "SELECT payload FROM snapshots ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    conn.close()

    if row:
        return JSONResponse(json.loads(row["payload"]))
    return JSONResponse({"error": "no data"})


@app.get("/api/training")
async def training_history(run_id: str = "", hours: float = 0):
    """Return training epoch data. If run_id empty, return all runs."""
    conn = get_db()

    if run_id:
        rows = conn.execute(
            "SELECT * FROM training_epochs WHERE run_id = ? ORDER BY epoch",
            (run_id,),
        ).fetchall()
    elif hours > 0:
        cutoff = time.time() - hours * 3600
        rows = conn.execute(
            "SELECT * FROM training_epochs WHERE timestamp > ? ORDER BY run_id, epoch",
            (cutoff,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM training_epochs ORDER BY run_id, epoch"
        ).fetchall()

    conn.close()
    return JSONResponse([dict(r) for r in rows])


@app.get("/api/runs")
async def list_runs():
    """Return summary of all training runs."""
    conn = get_db()
    rows = conn.execute("""
        SELECT run_id,
               COUNT(*) as epochs,
               MIN(timestamp) as started,
               MAX(timestamp) as last_update,
               MIN(val_loss) as best_val_loss,
               MAX(val_top1) as best_top1,
               MAX(val_top3) as best_top3,
               MAX(team_acc) as best_team_acc,
               MAX(lead_acc) as best_lead_acc
        FROM training_epochs
        GROUP BY run_id
        ORDER BY started DESC
    """).fetchall()
    conn.close()
    return JSONResponse([dict(r) for r in rows])


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the dashboard."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text())
    return HTMLResponse("<h1>Dashboard not deployed yet</h1>")


# Prune old snapshots (keep 7 days)
@app.on_event("startup")
async def prune_old():
    conn = get_db()
    cutoff = time.time() - 7 * 86400
    conn.execute("DELETE FROM snapshots WHERE timestamp < ?", (cutoff,))
    conn.commit()
    conn.close()
