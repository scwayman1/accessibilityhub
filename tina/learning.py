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

POINTS_CLAIM_BOUNDARY = (
    "Accessibility Points reward evidence-producing practice. They never "
    "measure or imply the conformance of any document."
)

# PRD §12.2: points only for evidence-producing actions, never for clicking through.
POINT_VALUES = {
    "review": 10,          # per document review completed
    "fix_skill": 25,       # per skill resolved and rechecked
    "attestation": 15,     # per judgment decision recorded
    "convert": 20,         # per HTML working copy created
    "receipt": 15,         # per evidence receipt exported
    "lesson": 10,          # per distinct lesson answered correctly
    "sustained_skill": 50, # per skill currently sustained
}

MILESTONES = [
    (0, "Getting Started"),
    (50, "Barrier Spotter"),
    (150, "Barrier Remover"),
    (300, "Practice Builder"),
    (600, "Access Champion"),
]

STREAK_BADGE_DAYS = 3

BADGES = [
    {"id": "evidence_builder", "label": "Evidence Builder",
     "description": "Exported an evidence receipt for a review."},
    {"id": "pdf_escape_artist", "label": "PDF Escape Artist",
     "description": "Rebuilt a document as an editable HTML working copy."},
    {"id": "meaningful_image_reviewer", "label": "Meaningful Image Reviewer",
     "description": "Recorded a human judgment about image alternatives."},
    {"id": "metadata_mender", "label": "Metadata Mender",
     "description": "Resolved and rechecked a title or language barrier."},
    {"id": "sustained_practice", "label": "Sustained Practice",
     "description": "Kept a learned defect from recurring across later documents."},
    {"id": "streak_keeper", "label": "Streak Keeper",
     "description": f"Practiced on {STREAK_BADGE_DAYS} days in a row."},
    {"id": "guided_learner", "label": "Guided Learner",
     "description": "Completed a micro-lesson and got the judgment call right."},
]

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

    def _canonical(self, document: str | None) -> str | None:
        """Resolve a document id through recorded fix lineage to its original.

        A fixed copy produced by this workbench is the same document with a new
        hash; treating it as its original keeps repeat-defect and sustained-skill
        math honest across chained fixes."""
        if document is None:
            return None
        parents = {
            event["child"]: event["parent"]
            for event in self.events
            if event["type"] == "lineage" and event.get("child") and event.get("parent")
        }
        seen = set()
        while document in parents and document not in seen:
            seen.add(document)
            document = parents[document]
        return document

    def record_lineage(self, parent_sha256: str | None, child_sha256: str | None) -> None:
        """Link a fixed copy's fingerprint to its source document's fingerprint."""
        parent = self._canonical(_doc_id(parent_sha256))
        child = _doc_id(child_sha256)
        if parent is None or child is None or parent == child:
            return
        self._record({"type": "lineage", "parent": parent, "child": child})

    def record_review(self, document_sha256: str | None, finding_rule_ids: list[str]) -> None:
        document = self._canonical(_doc_id(document_sha256))
        if document is None:
            return
        skills = sorted({RULE_TO_SKILL[rule] for rule in finding_rule_ids if rule in RULE_TO_SKILL})
        self._record({"type": "review", "document": document, "skills_with_findings": skills})

    def record_fix(self, document_sha256: str | None, resolved_rule_ids: list[str]) -> None:
        document = self._canonical(_doc_id(document_sha256))
        skills = sorted({RULE_TO_SKILL[rule] for rule in resolved_rule_ids if rule in RULE_TO_SKILL})
        if document is None or not skills:
            return
        self._record({"type": "fix_verified", "document": document, "skills": skills})

    def record_attestation(self, rule_id: str, decision: str) -> None:
        skill = RULE_TO_SKILL.get(rule_id)
        if skill is None or not decision.strip():
            return
        self._record({"type": "attestation", "skill": skill, "rule_id": rule_id, "decision": decision.strip()[:2000]})

    def record_activity(self, activity: str, document_sha256: str | None = None) -> None:
        """Record a non-review practice activity (e.g. 'convert', 'receipt')."""
        if activity not in {"convert", "receipt"}:
            return
        self._record({"type": activity, "document": _doc_id(document_sha256)})

    def record_lesson(self, skill: str, lesson_id: str, passed: bool) -> None:
        """Record a guided-practice result. Only a passed lesson is evidence."""
        if skill not in SKILLS or not lesson_id or not passed:
            return
        self._record({"type": "lesson_passed", "skill": skill, "lesson_id": lesson_id})

    def _skill_mastery(self, skill: str) -> dict[str, Any]:
        introduced_at = None
        practiced = False
        applied = False
        verified_index = None
        lessons_passed: list[str] = []
        for index, event in enumerate(self.events):
            if event["type"] == "review" and skill in event.get("skills_with_findings", []):
                if introduced_at is None:
                    introduced_at = event["recorded_at"]
            if event["type"] == "lesson_passed" and event.get("skill") == skill:
                practiced = True
                if event["lesson_id"] not in lessons_passed:
                    lessons_passed.append(event["lesson_id"])
            if event["type"] == "attestation" and event.get("skill") == skill:
                applied = True
            if event["type"] == "fix_verified" and skill in event.get("skills", []):
                applied = True
                verified_index = index

        state = "not_started"
        if introduced_at is not None:
            state = "introduced"
        # A passed lesson is guided practice: it can start a skill or advance an
        # introduced one, but it never outranks real-document evidence below.
        if practiced:
            state = "practiced"
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
                # The defect came back, so demonstrated mastery is not sustained —
                # but guided practice already completed is not erased.
                state = "practiced" if practiced else "introduced"
            elif len(clean_documents) >= SUSTAIN_DOCUMENTS:
                state = "sustained"

        return {
            "state": state,
            "introduced_at": introduced_at,
            "regressed": regressed,
            "lessons_passed": lessons_passed,
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

    def _streak(self) -> dict[str, Any]:
        """Consecutive practice days, counted humanely: the streak survives until
        a full day with no practice has actually passed (no punitive resets)."""
        dates = sorted({event["recorded_at"][:10] for event in self.events if event.get("recorded_at")})
        today = dt.datetime.now(dt.timezone.utc).date()
        if not dates:
            return {"days": 0, "active_today": False,
                    "message": "Review one document to start a practice streak."}
        day_set = {dt.date.fromisoformat(value) for value in dates}
        anchor = today if today in day_set else today - dt.timedelta(days=1)
        days = 0
        while anchor in day_set:
            days += 1
            anchor -= dt.timedelta(days=1)
        active_today = today in day_set
        if days == 0:
            message = "Welcome back — any practice today restarts your streak. No guilt, just documents."
        elif active_today:
            message = f"{days}-day practice streak. Nice, steady work."
        else:
            message = f"{days}-day streak — practice today to keep it going (grace period in effect)."
        return {"days": days, "active_today": active_today, "message": message}

    def _points(self, skills_state: dict[str, dict[str, Any]]) -> dict[str, Any]:
        counts = {
            "review": sum(1 for e in self.events if e["type"] == "review"),
            "fix_skill": sum(len(e.get("skills", [])) for e in self.events if e["type"] == "fix_verified"),
            "attestation": sum(1 for e in self.events if e["type"] == "attestation"),
            "convert": sum(1 for e in self.events if e["type"] == "convert"),
            "receipt": sum(1 for e in self.events if e["type"] == "receipt"),
            # Distinct lessons only: repeating one you already passed earns nothing.
            "lesson": len({e["lesson_id"] for e in self.events if e["type"] == "lesson_passed"}),
            "sustained_skill": sum(1 for state in skills_state.values() if state["state"] == "sustained"),
        }
        breakdown = {key: counts[key] * POINT_VALUES[key] for key in POINT_VALUES}
        total = sum(breakdown.values())
        current = next(name for threshold, name in reversed(MILESTONES) if total >= threshold)
        upcoming = [(threshold, name) for threshold, name in MILESTONES if threshold > total]
        milestone = {"current": current}
        if upcoming:
            threshold, name = upcoming[0]
            milestone.update({"next": name, "points_to_next": threshold - total})
        return {"total": total, "breakdown": breakdown, "milestone": milestone,
                "claim_boundary": POINTS_CLAIM_BOUNDARY}

    def _badges(self, skills_state: dict[str, dict[str, Any]], streak_days: int) -> list[dict[str, Any]]:
        earned = {
            "evidence_builder": any(e["type"] == "receipt" for e in self.events),
            "pdf_escape_artist": any(e["type"] == "convert" for e in self.events),
            "meaningful_image_reviewer": any(
                e["type"] == "attestation" and e.get("skill") == "images_and_meaning" for e in self.events
            ),
            "metadata_mender": any(
                e["type"] == "fix_verified" and "titles_and_language" in e.get("skills", [])
                for e in self.events
            ),
            "sustained_practice": any(state["state"] == "sustained" for state in skills_state.values()),
            "streak_keeper": streak_days >= STREAK_BADGE_DAYS,
            "guided_learner": any(e["type"] == "lesson_passed" for e in self.events),
        }
        return [{**badge, "earned": earned[badge["id"]]} for badge in BADGES]

    def journey(self) -> dict[str, Any]:
        reviewed_documents = {event["document"] for event in self.events if event["type"] == "review"}
        skills_state = {
            skill: {"label": spec["label"], "world": spec["world"], **self._skill_mastery(skill)}
            for skill, spec in SKILLS.items()
        }
        streak = self._streak()
        return {
            "contract_version": CONTRACT_VERSION,
            "claim_boundary": CLAIM_BOUNDARY,
            "documents_reviewed": len(reviewed_documents),
            "skills": skills_state,
            "repeat_defects": self._repeat_defects(),
            "points": self._points(skills_state),
            "streak": streak,
            "badges": self._badges(skills_state, streak["days"]),
        }
