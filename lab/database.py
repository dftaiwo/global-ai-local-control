"""Synthetic enterprise records stored in SQLite on the machine running the app.

For production: deploy the database/service on approved infrastructure physically in
Nigeria if the specific residency requirement calls for it. A workshop laptop's
location is NOT a proof of residency.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "workshop.sqlite"

# Fictional values. Do not replace them with actual customer records in the workshop.
SYNTHETIC_PAYMENTS = [
    ("PAY-001", "Example Vendor Alpha", "alpha@example.invalid", "0000000101", 12_400_000, 43, "CLEARED"),
    ("PAY-002", "Example Vendor Beta", "beta@example.invalid", "0000000102", 8_300_000, 32, "PENDING"),
    ("PAY-003", "Example Vendor Gamma", "gamma@example.invalid", "0000000103", 2_100_000, 55, "CLEARED"),
    ("PAY-004", "Example Vendor Delta", "delta@example.invalid", "0000000104", 21_000_000, 14, "CLEARED"),
    ("PAY-005", "Example Vendor Epsilon", "epsilon@example.invalid", "0000000105", 6_250_000, 17, "BLOCKED"),
    ("PAY-006", "Example Vendor Zeta", "zeta@example.invalid", "0000000106", 7_700_000, 0, "CLEARED"),
    ("PAY-007", "Example Vendor Eta", "eta@example.invalid", "0000000107", 5_500_000, 24, "CLEARED"),
    ("PAY-008", "Example Vendor Theta", "theta@example.invalid", "0000000108", 17_250_000, 58, "CLEARED"),
    ("PAY-009", "Example Vendor Iota", "iota@example.invalid", "0000000109", 11_800_000, 8, "CLEARED"),
    ("PAY-010", "Example Vendor Kappa", "kappa@example.invalid", "0000000110", 9_000_000, 13, "CLEARED"),
]


def connection() -> sqlite3.Connection:
    override = os.getenv("LOCAL_DB_PATH", "").strip()
    path = Path(override).expanduser() if override else DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db(reset: bool = False) -> None:
    with connection() as db:
        if reset:
            db.executescript("DROP TABLE IF EXISTS approvals; DROP TABLE IF EXISTS audit_events; DROP TABLE IF EXISTS payments;")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS payments (
                payment_id TEXT PRIMARY KEY,
                vendor_name TEXT NOT NULL,
                vendor_email TEXT NOT NULL,
                bank_account TEXT NOT NULL,
                amount_ngn INTEGER NOT NULL,
                overdue_days INTEGER NOT NULL,
                compliance_status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS approvals (
                request_id TEXT PRIMARY KEY,
                payment_id TEXT UNIQUE NOT NULL REFERENCES payments(payment_id),
                prepared_by TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('PENDING_HUMAN', 'APPROVED')),
                approved_by TEXT,
                created_at TEXT NOT NULL,
                approved_at TEXT
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                actor TEXT NOT NULL,
                event TEXT NOT NULL,
                decision TEXT NOT NULL,
                details TEXT NOT NULL
            );
        """)
        db.executemany("INSERT OR IGNORE INTO payments VALUES (?,?,?,?,?,?,?)", SYNTHETIC_PAYMENTS)


def audit(actor: str, event: str, decision: str, details: dict) -> None:
    # Never write vendor identity, bank account, full prompts or raw model payloads.
    safe_details = json.dumps(details, sort_keys=True)
    with connection() as db:
        db.execute("INSERT INTO audit_events(timestamp, actor, event, decision, details) VALUES (?,?,?,?,?)",
                   (datetime.now(timezone.utc).isoformat(), actor, event, decision, safe_details))


def payment_rows(min_amount_ngn: int):
    with connection() as db:
        rows = db.execute("""SELECT * FROM payments WHERE overdue_days > 0
                             AND amount_ngn >= ? ORDER BY amount_ngn DESC""", (min_amount_ngn,)).fetchall()
        return [dict(row) for row in rows]


def payment_by_id(payment_id: str):
    with connection() as db:
        row = db.execute("SELECT * FROM payments WHERE payment_id = ?", (payment_id,)).fetchone()
        return dict(row) if row else None


def list_approvals() -> list[dict]:
    with connection() as db:
        return [dict(r) for r in db.execute("SELECT request_id, payment_id, prepared_by, status, approved_by FROM approvals ORDER BY request_id").fetchall()]


def audit_rows() -> list[dict]:
    with connection() as db:
        return [dict(r) for r in db.execute("SELECT event_id, timestamp, actor, event, decision, details FROM audit_events ORDER BY event_id").fetchall()]
