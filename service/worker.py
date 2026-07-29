"""In-process synthetic staging queue worker; hosted isolation is a required external boundary."""
from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from check_pdf import analyze

from service.repository import StagingRepository


LANES = {
    "deterministic_defect": "needs_attention",
    "review_required": "review_recommended",
    "tool_failure_or_unsupported": "not_assessed",
    "blocking_technical_failure": "not_assessed",
    "advisory": "not_assessed",
}

UNASSESSED_SIGNALS = (
    ("PDF.VISUAL.CONTRAST", "Contrast", "Not assessed", "Visual contrast needs source or rendered-page review."),
    ("PDF.TABLES.MEANING", "Tables", "Not assessed", "Table headers, scope, and reading order need contextual review."),
    ("PDF.FORMS.LABELS", "Forms", "Not assessed", "Form labels and instructions are not assessed in this staging slice."),
)


def normalize_report(report: dict[str, Any]) -> dict[str, Any]:
    """Map checker evidence into discrete product lanes without creating a score."""
    signals: list[dict[str, Any]] = []
    for item in report.get("findings", []):
        signals.append({
            "lane": LANES.get(item.get("category"), "not_assessed"),
            "rule_id": item.get("rule_id"),
            "title": item.get("rule_id", "Finding").replace("PDF.", "").replace("_", " ").title(),
            "evidence": item.get("evidence"),
            "next_action": item.get("next_action"),
            "educator_context": item.get("category") in {"review_required", "advisory"},
            "location": item.get("location"),
        })
    for item in report.get("strengths", []):
        signals.append({
            "lane": "verified_signal", "rule_id": item.get("rule_id"),
            "title": item.get("rule_id", "Signal").replace("PDF.", "").replace("_", " ").title(),
            "evidence": item.get("evidence"), "next_action": "Keep this document detail in place.",
            "educator_context": False, "location": "machine evidence",
        })
    for rule_id, title, lane_label, evidence in UNASSESSED_SIGNALS:
        signals.append({
            "lane": "not_assessed", "rule_id": rule_id, "title": title,
            "evidence": evidence, "next_action": "Review this detail in the source material.",
            "educator_context": True, "location": lane_label,
        })
    report_copy = json.loads(json.dumps(report))
    report_copy.get("input", {}).pop("path", None)
    report_copy.get("verapdf", {}).pop("report_path", None)
    return {"report": report_copy, "signals": signals, "claim": "Signals are shown separately. They are not an overall accessibility result."}


class AssessmentWorker:
    def __init__(self, repository: StagingRepository) -> None:
        self.repository = repository
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="hub-synthetic-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self.run_once():
                self._stop.wait(0.08)

    def run_once(self) -> bool:
        try:
            job = self.repository.claim_next_job()
        except Exception:
            # A controlled shutdown can remove the local development directory
            # after the worker has entered its polling cycle. Do not crash the
            # process or turn a storage boundary failure into a document result.
            return False
        if job is None:
            return False
        try:
            with self.repository._connect() as db:  # Worker resolves tenant from the persisted document, never request input.
                row = db.execute("SELECT tenant_id FROM documents WHERE id=?", (job["document_id"],)).fetchone()
            if row is None:
                raise RuntimeError("job document no longer exists")
            payload = self.repository.document_bytes(row["tenant_id"], job["document_id"])
            with tempfile.TemporaryDirectory(prefix="hub-staging-assessment-") as temp_dir:
                root = Path(temp_dir)
                pdf = root / "synthetic.pdf"
                pdf.write_bytes(payload)
                result = normalize_report(analyze(pdf, root / "evidence"))
            self.repository.finish_job(job["id"], result=result)
        except Exception as error:  # Do not leak parser diagnostics to browser clients.
            self.repository.finish_job(job["id"], error_code=f"assessment_failed:{type(error).__name__}")
        return True
