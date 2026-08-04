"""In-process synthetic staging queue worker; hosted isolation is a required external boundary."""
from __future__ import annotations

import json
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from check_pdf import analyze

from service.repository import StagingRepository

# Rules the educator pipeline may resolve automatically — metadata only, ever.
AUTO_FIX_RULES = frozenset({"PDF.METADATA.TITLE", "PDF.METADATA.LANGUAGE"})
AUTO_FIX_LANGUAGE = "en-US"

_VERSION_PATTERN = re.compile(r"^(?P<base>.+)\.v(?P<version>\d+)$")


def split_version(filename: str) -> tuple[str, int]:
    """('base', N) for base.vN.pdf; legacy '.rechecked' chains collapse to the base."""
    stem = filename[:-4] if filename.lower().endswith(".pdf") else filename
    while stem.endswith(".rechecked"):
        stem = stem[: -len(".rechecked")]
    match = _VERSION_PATTERN.match(stem)
    if match:
        return match.group("base"), int(match.group("version"))
    return stem, 1


def next_version_name(filename: str) -> str:
    base, version = split_version(filename)
    return f"{base}.v{version + 1}.pdf"


def pipeline_title(filename: str, source_kind: str) -> str:
    """Prettified filename for the automatic title fix: strip the extension,
    turn dashes/underscores into spaces, and title-case each word."""
    if source_kind == "bundled_synthetic_fixture":
        return "Week 3 Course Handout"
    base = split_version(filename)[0]
    words = re.sub(r"[-_]+", " ", base).strip()
    return " ".join(word[:1].upper() + word[1:] for word in words.split()) or "Course Handout"


LANES = {
    "deterministic_defect": "needs_attention",
    "review_required": "review_recommended",
    # A document that cannot be read at all is a problem the educator must act
    # on, not a shrug: it belongs in "Needs attention", never in gray.
    "blocking_technical_failure": "needs_attention",
    "advisory": "review_recommended",
}

LANE_ORDER = ("needs_attention", "review_recommended", "verified_signal", "not_assessed")

# Educator-ready titles authored in rule_knowledge.json, loaded once.
_KNOWLEDGE_PATH = Path(__file__).resolve().parents[1] / "rule_knowledge.json"
try:
    _RULE_TITLES: dict[str, str] = {
        rule_id: entry["title"]
        for rule_id, entry in json.loads(_KNOWLEDGE_PATH.read_text(encoding="utf-8")).get("rules", {}).items()
        if isinstance(entry, dict) and entry.get("title")
    }
except (OSError, json.JSONDecodeError):
    _RULE_TITLES = {}

# A verified strength should never be named after the defect it disproves.
_STRENGTH_TITLES = {
    "PDF.IMAGES.ALT_MISSING": "Figure descriptions in place",
    "PDF.LINKS.NAME": "Links are named",
    "PDF.INTAKE.QPDF_CHECK": "Structural integrity",
}

# Plain-language copy for documents the reviewer could not read at all.
_BLOCKED_COPY = {
    "PDF.INTAKE.ENCRYPTED": (
        "This document is password-protected, so it could not be reviewed.",
        "Ask the document owner for an unencrypted copy, then review that copy.",
    ),
    "PDF.INTAKE.QPDF_CHECK": (
        "This document appears to be damaged, so it could not be reviewed reliably.",
        "Export a fresh PDF from the original source document, then review again.",
    ),
    "PDF.PARSE.PYPDF": (
        "This document could not be opened for review.",
        "Export a fresh PDF from the original source document, then review again.",
    ),
}

# Tool-availability items never lead the review: they collapse into a quiet
# "Review completeness" note in plain language, at the end of the page.
_COMPLETENESS_COPY = {
    "PDF.INTAKE.QPDF_UNAVAILABLE": "The structural integrity checker isn't available in this environment, so that check was not run.",
    "PDF.VERAPDF.UNAVAILABLE": "The full-standard validator isn't available in this environment, so those checks were not run.",
}


def _humanize(rule_id: str) -> str:
    """Fallback title: never a raw dotted rule id, never a mangled non-word."""
    cleaned = rule_id.removeprefix("PDF.").replace(".", " ").replace("_", " ")
    return cleaned.strip().title() or "Finding"


def title_for(rule_id: str | None) -> str:
    rule_id = rule_id or ""
    return _RULE_TITLES.get(rule_id) or _humanize(rule_id)


def _strength_title(rule_id: str | None) -> str:
    rule_id = rule_id or ""
    return _STRENGTH_TITLES.get(rule_id) or title_for(rule_id)


def _is_toolchain_area(area: str) -> bool:
    lowered = area.lower()
    return "qpdf" in lowered or "verapdf" in lowered


def normalize_report(report: dict[str, Any]) -> dict[str, Any]:
    """Map checker evidence into discrete product lanes without creating a score."""
    signals: list[dict[str, Any]] = []
    completeness: list[str] = []
    for item in report.get("findings", []):
        category = item.get("category")
        rule_id = item.get("rule_id")
        if category == "tool_failure_or_unsupported":
            completeness.append(
                _COMPLETENESS_COPY.get(rule_id or "")
                or f"{title_for(rule_id)}: this check could not run in this environment, so it was not included."
            )
            continue
        evidence, next_action = item.get("evidence"), item.get("next_action")
        if category == "blocking_technical_failure" and rule_id in _BLOCKED_COPY:
            evidence, next_action = _BLOCKED_COPY[rule_id]
        signals.append({
            "lane": LANES.get(category, "not_assessed"),
            "rule_id": rule_id,
            "title": title_for(rule_id),
            "evidence": evidence,
            "next_action": next_action,
            "educator_context": category in {"review_required", "advisory"},
            "location": item.get("location"),
        })
    for item in report.get("strengths", []):
        signals.append({
            "lane": "verified_signal", "rule_id": item.get("rule_id"),
            "title": _strength_title(item.get("rule_id")),
            "evidence": item.get("evidence"), "next_action": "Keep this document detail in place.",
            "educator_context": False, "location": "machine evidence",
        })
    # The report's own honesty list, in full — including color-only meaning.
    # Toolchain entries are already covered by the completeness notes above.
    for item in report.get("not_assessed", []):
        area = str(item.get("area") or "").strip()
        if not area:
            continue
        if _is_toolchain_area(area):
            continue
        signals.append({
            "lane": "not_assessed", "rule_id": None,
            "title": area[:1].upper() + area[1:],
            "evidence": item.get("reason"),
            "next_action": "Review this detail in the source material.",
            "educator_context": True, "location": "human review",
        })
    signals.sort(key=lambda signal: LANE_ORDER.index(signal["lane"]) if signal["lane"] in LANE_ORDER else len(LANE_ORDER))
    report_copy = json.loads(json.dumps(report))
    report_copy.get("input", {}).pop("path", None)
    report_copy.get("verapdf", {}).pop("report_path", None)
    return {
        "report": report_copy,
        "signals": signals,
        "completeness": completeness,
        "claim": "Signals are shown separately. They are not an overall accessibility result.",
    }


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
                row = db.execute("SELECT * FROM documents WHERE id=?", (job["document_id"],)).fetchone()
            if row is None:
                raise RuntimeError("job document no longer exists")
            document = dict(row)
            payload = self.repository.document_bytes(document["tenant_id"], job["document_id"])
            with tempfile.TemporaryDirectory(prefix="hub-staging-assessment-") as temp_dir:
                root = Path(temp_dir)
                pdf = root / "synthetic.pdf"
                pdf.write_bytes(payload)
                result = normalize_report(analyze(pdf, root / "evidence"))
            if job["kind"] == "pipeline":
                # Chain the safe improvement BEFORE this job turns terminal so
                # a refreshing status page always finds the improved copy the
                # moment the first assessment lands.
                self._apply_pipeline_improvement(document, payload, result)
            self.repository.finish_job(job["id"], result=result)
        except Exception as error:  # Do not leak parser diagnostics to browser clients.
            self.repository.finish_job(job["id"], error_code=f"assessment_failed:{type(error).__name__}")
        return True

    def _apply_pipeline_improvement(self, document: dict[str, Any], payload: bytes, result: dict[str, Any]) -> None:
        """Auto-apply ONLY the title/language metadata fix, on a copy, with full
        provenance — exactly what the manual one-click path records. Anything
        else stays a human decision. Improved copies (they have a parent) are
        only re-assessed, never re-improved, so the chain always terminates.
        """
        if document.get("parent_document_id"):
            return
        defects = {
            signal.get("rule_id")
            for signal in result.get("signals", [])
            if signal.get("lane") in {"needs_attention", "review_recommended"}
        } & AUTO_FIX_RULES
        if not defects:
            return
        from tina.remedy import MetadataRemediation
        title = pipeline_title(document["filename"], document["source_kind"]) if "PDF.METADATA.TITLE" in defects else None
        language = AUTO_FIX_LANGUAGE if "PDF.METADATA.LANGUAGE" in defects else None
        try:
            fixed, provenance = MetadataRemediation.with_builtin_tools().apply(
                document["filename"], payload, title=title, language=language)
        except Exception:
            # The improvement is best-effort: a copy that cannot be improved
            # safely still gets its honest assessment, nothing more.
            return
        child = self.repository.create_document(
            document["tenant_id"], next_version_name(document["filename"]),
            "synthetic_remediated_copy", fixed, parent_document_id=document["id"])
        self.repository.record_remediation(child["id"], document["id"], "metadata", provenance)
        job_id = self.repository.enqueue(child["id"], kind="pipeline")
        self.repository.audit(document["tenant_id"], "automated-pipeline", "remediation_applied", child["id"], {
            "parent": document["id"], "kind": "metadata", "job_id": job_id, "provenance": provenance,
        })
