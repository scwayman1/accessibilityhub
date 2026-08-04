"""SQLite-backed document, job, provenance, and audit persistence for synthetic staging."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(UTC).isoformat()


class StagingRepository:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.db_path = data_dir / "accessibility-hub.sqlite3"
        self.documents_dir = data_dir / "documents"
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, filename TEXT NOT NULL,
                    source_kind TEXT NOT NULL, sha256 TEXT NOT NULL, storage_key TEXT NOT NULL,
                    parent_document_id TEXT, created_at TEXT NOT NULL,
                    FOREIGN KEY(parent_document_id) REFERENCES documents(id)
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL, kind TEXT NOT NULL,
                    state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, result_json TEXT,
                    error_code TEXT, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                    FOREIGN KEY(document_id) REFERENCES documents(id)
                );
                CREATE TABLE IF NOT EXISTS remediations (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL, parent_document_id TEXT NOT NULL,
                    kind TEXT NOT NULL, provenance_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES documents(id),
                    FOREIGN KEY(parent_document_id) REFERENCES documents(id)
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, actor TEXT NOT NULL,
                    action TEXT NOT NULL, target_id TEXT, detail_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_state_created ON jobs(state, created_at);
                CREATE INDEX IF NOT EXISTS documents_tenant_created ON documents(tenant_id, created_at DESC);
                """
            )

    def audit(self, tenant_id: str, actor: str, action: str, target_id: str | None, detail: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), tenant_id, actor, action, target_id, json.dumps(detail, sort_keys=True), now()),
            )

    def create_document(self, tenant_id: str, filename: str, source_kind: str, payload: bytes, parent_document_id: str | None = None) -> dict[str, str]:
        document_id = str(uuid.uuid4())
        storage_key = f"{document_id}.pdf"
        path = self.documents_dir / storage_key
        path.write_bytes(payload)
        item = {
            "id": document_id, "tenant_id": tenant_id, "filename": filename, "source_kind": source_kind,
            "sha256": hashlib.sha256(payload).hexdigest(), "storage_key": storage_key,
            "parent_document_id": parent_document_id, "created_at": now(),
        }
        with self._connect() as db:
            db.execute(
                "INSERT INTO documents VALUES (:id, :tenant_id, :filename, :source_kind, :sha256, :storage_key, :parent_document_id, :created_at)", item,
            )
        return item

    def document(self, tenant_id: str, document_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM documents WHERE id = ? AND tenant_id = ?", (document_id, tenant_id)).fetchone()
        return dict(row) if row else None

    def document_bytes(self, tenant_id: str, document_id: str) -> bytes:
        item = self.document(tenant_id, document_id)
        if item is None:
            raise KeyError("document not found")
        return (self.documents_dir / item["storage_key"]).read_bytes()

    def latest_child(self, tenant_id: str, document_id: str) -> dict[str, Any] | None:
        """Newest direct derived copy of a document, if one exists."""
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM documents WHERE parent_document_id = ? AND tenant_id = ? ORDER BY created_at DESC LIMIT 1",
                (document_id, tenant_id),
            ).fetchone()
        return dict(row) if row else None

    def list_documents(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT d.*, j.id AS job_id, j.state AS job_state, j.finished_at AS job_finished_at "
                "FROM documents d LEFT JOIN jobs j ON j.id = (SELECT id FROM jobs WHERE document_id=d.id ORDER BY created_at DESC LIMIT 1) "
                "WHERE d.tenant_id=? ORDER BY d.created_at DESC", (tenant_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def enqueue(self, document_id: str, kind: str = "assessment") -> str:
        job_id = str(uuid.uuid4())
        with self._connect() as db:
            db.execute("INSERT INTO jobs (id, document_id, kind, state, created_at) VALUES (?, ?, ?, 'queued', ?)", (job_id, document_id, kind, now()))
        return job_id

    def claim_next_job(self) -> dict[str, Any] | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created_at LIMIT 1").fetchone()
            if row is None:
                return None
            changed = db.execute("UPDATE jobs SET state='running', attempts=attempts+1, started_at=? WHERE id=? AND state='queued'", (now(), row["id"])).rowcount
            if changed != 1:
                return None
            return dict(db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())

    def finish_job(self, job_id: str, result: dict[str, Any] | None = None, error_code: str | None = None) -> None:
        state = "succeeded" if error_code is None else "failed"
        with self._connect() as db:
            db.execute("UPDATE jobs SET state=?, result_json=?, error_code=?, finished_at=? WHERE id=?", (state, json.dumps(result, sort_keys=True) if result else None, error_code, now(), job_id))

    def latest_job(self, tenant_id: str, document_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT j.* FROM jobs j JOIN documents d ON d.id=j.document_id WHERE j.document_id=? AND d.tenant_id=? ORDER BY j.created_at DESC LIMIT 1",
                (document_id, tenant_id),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["result"] = json.loads(item.pop("result_json")) if item.get("result_json") else None
        return item

    def record_remediation(self, document_id: str, parent_document_id: str, kind: str, provenance: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO remediations VALUES (?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), document_id, parent_document_id, kind, json.dumps(provenance, sort_keys=True), now()))

    def remediations(self, tenant_id: str, document_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT r.* FROM remediations r JOIN documents d ON d.id=r.document_id WHERE r.document_id=? AND d.tenant_id=? ORDER BY r.created_at",
                (document_id, tenant_id),
            ).fetchall()
        return [{**dict(row), "provenance": json.loads(row["provenance_json"])} for row in rows]

    def delete_document_lineage(self, tenant_id: str, document_id: str) -> int:
        """Delete a synthetic document and its derived copies; audit remains outside this lineage."""
        with self._connect() as db:
            rows = db.execute(
                """WITH RECURSIVE lineage(id) AS (
                       SELECT id FROM documents WHERE id=? AND tenant_id=?
                       UNION ALL
                       SELECT d.id FROM documents d JOIN lineage l ON d.parent_document_id=l.id
                   ) SELECT id, storage_key FROM documents WHERE id IN lineage""",
                (document_id, tenant_id),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if not ids:
                return 0
            placeholders = ",".join("?" for _ in ids)
            db.execute(f"DELETE FROM remediations WHERE document_id IN ({placeholders}) OR parent_document_id IN ({placeholders})", ids + ids)
            db.execute(f"DELETE FROM jobs WHERE document_id IN ({placeholders})", ids)
            db.execute(f"DELETE FROM documents WHERE id IN ({placeholders})", ids)
        for row in rows:
            (self.documents_dir / row["storage_key"]).unlink(missing_ok=True)
        return len(ids)
