"""Immutable local execution archives. No device commands are issued here."""
import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    task_id: str = Field(min_length=1, max_length=200)
    source_text: str = Field(max_length=50000)
    kind: Literal["linear", "conditional"]
    record_source: Literal["plan_draft", "simulation"]
    plan: dict
    execution_run: dict
    execution_records: list[dict] = Field(max_length=5000)
    structured_result: dict

    @model_validator(mode="after")
    def validate_records(self):
        seen = set()
        completed = self.execution_run.get("status") == "simulation_completed"
        if completed != (self.record_source == "simulation"):
            raise ValueError("record_source must match execution_run status")
        if self.execution_run.get("status") not in {"not_started", "simulation_completed"}:
            raise ValueError("Real device execution feedback is not connected")
        for row in self.execution_records:
            key = row.get("step_id")
            if not isinstance(key, str) or not key or key in seen:
                raise ValueError("Step IDs must be nonempty and unique")
            seen.add(key)
            if row.get("status") not in {"pending", "simulated_success"}:
                raise ValueError("Only pending and simulated records are currently accepted")
            if row["status"] == "simulated_success" and not completed:
                raise ValueError("Simulated steps require a simulation run")
            dates = []
            for field in ("started_at", "finished_at"):
                value = row.get(field)
                if value is None:
                    dates.append(None)
                    continue
                try:
                    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except (ValueError, TypeError, AttributeError) as exc:
                    raise ValueError("Step timestamps must be ISO 8601") from exc
                if date.tzinfo is None:
                    raise ValueError("Step timestamps must contain a timezone")
                dates.append(date)
            if all(dates) and dates[1] < dates[0]:
                raise ValueError("Step completion cannot precede its start")
        raw = json.dumps(self.model_dump(), ensure_ascii=False, allow_nan=False)
        if len(raw.encode("utf-8")) > 5 * 1024 * 1024:
            raise ValueError("Archive exceeds 5 MiB")
        return self


class ExecutionHistoryStore:
    def __init__(self, path: Path):
        self.path = path

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS archives (
                archive_id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL,
                task_id TEXT NOT NULL, created_at TEXT NOT NULL,
                kind TEXT NOT NULL, record_source TEXT NOT NULL,
                source_text TEXT NOT NULL, snapshot TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS archive_task ON archives(task_id);
            CREATE TABLE IF NOT EXISTS step_records (
                archive_id TEXT NOT NULL REFERENCES archives(archive_id),
                position INTEGER NOT NULL, step_id TEXT NOT NULL, record TEXT NOT NULL,
                PRIMARY KEY(archive_id, step_id));
            PRAGMA user_version=1;
        """)
        return db

    def save(self, request: ArchiveRequest):
        raw = json.dumps(request.model_dump(), ensure_ascii=False, sort_keys=True, allow_nan=False)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        archive_id = "archive_" + uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        db = self.connect()
        try:
            with db:
                db.execute("INSERT OR IGNORE INTO archives VALUES (?,?,?,?,?,?,?,?)",
                           (archive_id, digest, request.task_id, created_at, request.kind,
                            request.record_source, request.source_text, raw))
                saved = dict(db.execute("SELECT archive_id,created_at FROM archives WHERE digest=?", (digest,)).fetchone())
                if saved["archive_id"] == archive_id:
                    db.executemany("INSERT INTO step_records VALUES (?,?,?,?)", [
                        (archive_id, i, row["step_id"], json.dumps(row, ensure_ascii=False, allow_nan=False))
                        for i, row in enumerate(request.execution_records)])
            return {**saved, "deduplicated": saved["archive_id"] != archive_id,
                    "execution_allowed": False}
        finally:
            db.close()

    def list(self, task_id=None, limit=30, offset=0):
        db = self.connect()
        try:
            clause, args = (" WHERE task_id=?", [task_id]) if task_id else ("", [])
            total = db.execute("SELECT count(*) FROM archives" + clause, args).fetchone()[0]
            items = db.execute("SELECT archive_id,task_id,created_at,kind,record_source,source_text "
                               "FROM archives" + clause + " ORDER BY rowid DESC LIMIT ? OFFSET ?",
                               [*args, limit, offset]).fetchall()
            return {"total": total, "items": [dict(row) for row in items]}
        finally:
            db.close()

    def get(self, archive_id):
        db = self.connect()
        try:
            row = db.execute("SELECT archive_id,created_at,snapshot FROM archives WHERE archive_id=?", (archive_id,)).fetchone()
            if row is None:
                return None
            return {"archive_id": row["archive_id"], "created_at": row["created_at"],
                    "snapshot": json.loads(row["snapshot"]), "execution_allowed": False}
        finally:
            db.close()


store = ExecutionHistoryStore(Path(os.getenv("EXECUTION_HISTORY_DB") or
    Path(__file__).resolve().parent.parent / "data/execution_history/history.sqlite3"))
router = APIRouter(prefix="/api/execution", tags=["execution-history"])


@router.post("/archives")
def save_archive(request: ArchiveRequest):
    try:
        return store.save(request)
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(503, "Execution archive storage unavailable; please retry") from exc


@router.get("/archives")
def list_archives(task_id: str | None = Query(default=None, max_length=200),
                  limit: int = Query(default=30, ge=1, le=100),
                  offset: int = Query(default=0, ge=0)):
    try:
        return store.list(task_id, limit, offset)
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(503, "Execution archive storage unavailable") from exc


@router.get("/archives/{archive_id}")
def get_archive(archive_id: str):
    try:
        result = store.get(archive_id)
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(503, "Execution archive storage unavailable") from exc
    if result is None:
        raise HTTPException(404, "Execution archive not found")
    return result


@router.get("/capabilities")
def execution_capabilities():
    return {"archive_contract_version": "1.0.0", "persistence": True,
            "device_submission": False, "device_events": False, "device_control": False,
            "execution_allowed": False}


@router.post("/submit")
@router.post("/events")
@router.post("/control")
def reserved_execution_interface():
    raise HTTPException(501, "Reserved interface; device protocol and authorization are not connected")
