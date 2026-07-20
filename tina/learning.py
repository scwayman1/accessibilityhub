"""Tina deterministic learning journey engine (PRD §12.4, §13, §18).

Tracks evidence-based skill mastery from real review and fix events — no AI,
no quizzes, no points for clicking "Next." Mastery advances only on
evidence-producing actions, and the Sustained level is earned by the defect
NOT appearing in later documents: the north-star metric (repeat defect
reduction) computed locally.

Privacy: the store records only document hash prefixes, rule identifiers,
decision text the user chose to attest, and timestamps. Never filenames,
never document content.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "tina-learning-journey/v1"
SUSTAIN_DOCUMENTS = 2

CLAIM_BOUNDARY = (
    "Mastery states describe evidence recorded by this workbench. They are "
    "practice milestones, not accessibility certifications."
)

# Skill map: PRD skill-map worlds, keyed by the deterministic rules that feed them.
SKILLS: dict[str, dict[str, Any]] = {
    "titles_and_language": {
        "label": "Titles and language",
        "world": "Structure That Communicates",
        "rules": ["PDF.METADATA.TITLE", "PDF.METADATA.LANGUAGE"],
    },
    "structure_and_reading_order": {
        "label": "Structure and reading order",
        "world": "Structure That Communicates",
        "rules": ["PDF.STRUCTURE.SEMANTICS"],
    },
    "images_and_meaning": {
        "label": "Images and meaning",
        "world": "Images and Meaning",
        "rules": ["PDF.IMAGES.ALTERNATIVES"],
    },
    "links_and_navigation": {
        "label": "Links and navigation",
        "world": "Links, Navigation, and Interaction",
        "rules": ["PDF.LINKS.PURPOSE"],
    },
    "scans_and_text_access": {
        "label": "Scans and text access",
        "world": "PDF Survival and Escape Routes",
        "rules": ["PDF.TEXT_LAYER"],
    },
    "document_integrity": {
        "label": "Document integrity",
        "world": "PDF Survival and Escape Routes",
        "rules": ["PDF.INTAKE.QPDF_CHECK", "PDF.INTAKE.ENCRYPTED", "PDF.PARSE.PYPDF"],
    },
}

RULE_TO_SKILL = {rule: skill for skill, spec in SKILLS.items() for rule in spec["rules"]}

MASTERY_STATES = ["not_started", "introduced", "practiced", "applied", "verified", "sustained"]


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _doc_id(sha256_value: str | None) -> str | None:
    if not sha256_value:
        return None
    return sha256_value.removeprefix("sha256:")[:16]


class LearningJourney:
    """Local, deterministic mastery tracker fed by review/fix/attestation events."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.events: list[dict[str, Any]] = []
        if path is not None and path.exists():
            try:
                self.events = json.loads(path.read_text()).get("events", [])
            except (json.JSONDecodeError, OSError):
                self.events = []

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"contract_version": CONTRACT_VERSION, "events": self.events}, indent=2))

    def _record(self, event: dict[str, Any]) -> None:
        event["recorded_at"] = _now()
        self.events.append(event)
        self._save()

    def record_review(self, document_sha256: str | None, finding_rule_ids: list[str]) -> None:
        document = _doc_id(document_sha256)
        if document is None:
            return
        skills = sorted({RULE_TO_SKILL[rule] for rule in finding_rule_ids if rule in RULE_TO_SKILL})
        self._record({"type": "review", "document": document, "skills_with_findings": skills})

    def record_fix(self, document_sha256: str | None, resolved_rule_ids: list[str]) -> None:
        document = _doc_id(document_sha256)
        skills = sorted({RULE_TO_SKILL[rule] for rule in resolved_rule_ids if rule in RULE_TO_SKILL})
        if document is None or not skills:
            return
        self._record({"type": "fix_verified", "document": document, "skills": skills})

    def record_attestation(self, rule_id: str, decision: str) -> None:
        skill = RULE_TO_SKILL.get(rule_id)
        if skill is None or not decision.strip():
            return
        self._record({"type": "attestation", "skill": skill, "rule_id": rule_id, "decision": decision.strip()[:2000]})

    def _skill_mastery(self, skill: str) -> dict[str, Any]:
        introduced_at = None
        applied = False
        verified_index = None
        for index, event in enumerate(self.events):
            if event["type"] == "review" and skill in event.get("skills_with_findings", []):
                if introduced_at is None:
                    introduced_at = event["recorded_at"]
            if event["type"] == "attestation" and event.get("skill") == skill:
                applied = True
            if event["type"] == "fix_verified" and skill in event.get("skills", []):
                applied = True
                verified_index = index

        state = "not_started"
        if introduced_at is not None:
            state = "introduced"
        if applied:
            state = "applied"
        if verified_index is not None:
            state = "verified"

        clean_documents: list[str] = []
        regressed = False
        if verified_index is not None:
            fixed_document = self.events[verified_index].get("document")
            for event in self.events[verified_index + 1 :]:
                if event["type"] != "review":
                    continue
                if event["document"] == fixed_document:
                    continue
                if skill in event.get("skills_with_findings", []):
                    regressed = True
                    clean_documents = []
                elif event["document"] not in clean_documents:
                    clean_documents.append(event["document"])
            if regressed:
                state = "introduced"
            elif len(clean_documents) >= SUSTAIN_DOCUMENTS:
                state = "sustained"

        return {
            "state": state,
            "introduced_at": introduced_at,
            "regressed": regressed,
            "clean_documents_since_verified": len(clean_documents),
            "clean_documents_needed_for_sustained": max(0, SUSTAIN_DOCUMENTS - len(clean_documents)),
        }

    def _repeat_defects(self) -> list[dict[str, Any]]:
        documents_by_skill: dict[str, set[str]] = {}
        for event in self.events:
            if event["type"] != "review":
                continue
            for skill in event.get("skills_with_findings", []):
                documents_by_skill.setdefault(skill, set()).add(event["document"])
        return [
            {
                "skill": skill,
                "label": SKILLS[skill]["label"],
                "documents_affected": len(documents),
                "recommendation": (
                    f"'{SKILLS[skill]['label']}' has appeared in {len(documents)} documents. "
                    "Review the teaching card for this finding and fix it in your source workflow "
                    "so the next export starts clean."
                ),
            }
            for skill, documents in sorted(documents_by_skill.items())
            if len(documents) >= 2
        ]

    def journey(self) -> dict[str, Any]:
        reviewed_documents = {event["document"] for event in self.events if event["type"] == "review"}
        return {
            "contract_version": CONTRACT_VERSION,
            "claim_boundary": CLAIM_BOUNDARY,
            "documents_reviewed": len(reviewed_documents),
            "skills": {
                skill: {"label": spec["label"], "world": spec["world"], **self._skill_mastery(skill)}
                for skill, spec in SKILLS.items()
            },
            "repeat_defects": self._repeat_defects(),
        }
