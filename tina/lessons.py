"""Authored micro-lessons (PRD §11).

Deterministic content only: lessons are written by humans, validated on load,
and scored by exact match. Nothing here generates text, adapts difficulty, or
decides whether a document is acceptable. A lesson demonstrates understanding;
it certifies nothing.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tina.learning import SKILLS

CONTRACT_VERSION = "tina-lessons/v1"
STEP_KINDS = ("encounter", "experience", "explain", "decide", "verify", "transfer")
CONTENT_PATH = Path(__file__).resolve().parent.parent / "lesson_content.json"


class LessonError(ValueError):
    """Raised when lesson content is invalid or a scoring request is malformed."""


def _validate(payload: dict[str, Any]) -> list[dict[str, Any]]:
    lessons = payload.get("lessons")
    if not isinstance(lessons, list) or not lessons:
        raise LessonError("Lesson content must contain a non-empty 'lessons' list.")
    seen: set[str] = set()
    for lesson in lessons:
        lesson_id = lesson.get("lesson_id")
        if not lesson_id or lesson_id in seen:
            raise LessonError(f"Each lesson needs a unique lesson_id (problem near: {lesson_id!r}).")
        seen.add(lesson_id)
        if lesson.get("skill") not in SKILLS:
            raise LessonError(f"Lesson {lesson_id} references an unknown skill: {lesson.get('skill')!r}.")
        steps = lesson.get("steps")
        if not isinstance(steps, list) or not steps:
            raise LessonError(f"Lesson {lesson_id} has no steps.")
        decide_steps = 0
        for index, step in enumerate(steps):
            kind = step.get("kind")
            if kind not in STEP_KINDS:
                raise LessonError(f"Lesson {lesson_id} step {index} has an unknown kind: {kind!r}.")
            if kind != "decide":
                if not str(step.get("body", "")).strip():
                    raise LessonError(f"Lesson {lesson_id} step {index} ({kind}) has no body.")
                continue
            decide_steps += 1
            options = step.get("options")
            if not isinstance(options, list) or len(options) < 2:
                raise LessonError(f"Lesson {lesson_id} step {index} needs at least two options.")
            correct = step.get("correct_index")
            if not isinstance(correct, int) or not 0 <= correct < len(options):
                raise LessonError(f"Lesson {lesson_id} step {index} has an out-of-range correct_index.")
            if not str(step.get("rationale", "")).strip():
                raise LessonError(f"Lesson {lesson_id} step {index} needs a rationale.")
        if decide_steps != 1:
            raise LessonError(f"Lesson {lesson_id} must have exactly one 'decide' step (found {decide_steps}).")
    return lessons


class LessonLibrary:
    """Loads, validates, and serves authored lessons. No generation, ever."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or CONTENT_PATH
        try:
            payload = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise LessonError(f"Lesson content could not be read: {type(error).__name__}") from error
        self.claim_boundary = payload.get("claim_boundary", "")
        self.lessons = _validate(payload)

    def for_skill(self, skill: str) -> list[dict[str, Any]]:
        return [lesson for lesson in self.lessons if lesson["skill"] == skill]

    def get(self, lesson_id: str) -> dict[str, Any]:
        for lesson in self.lessons:
            if lesson["lesson_id"] == lesson_id:
                return lesson
        raise LessonError(f"No lesson with id {lesson_id!r}.")

    def catalog(self, skill: str | None = None) -> dict[str, Any]:
        """Browser-safe lesson listing. Correct answers are withheld until scoring."""
        selected = self.for_skill(skill) if skill else self.lessons
        safe = []
        for lesson in selected:
            steps = []
            for step in lesson["steps"]:
                if step["kind"] == "decide":
                    steps.append({"kind": "decide", "prompt": step["prompt"], "options": list(step["options"])})
                else:
                    steps.append({"kind": step["kind"], "body": step["body"]})
            safe.append({
                "lesson_id": lesson["lesson_id"],
                "skill": lesson["skill"],
                "skill_label": SKILLS[lesson["skill"]]["label"],
                "title": lesson["title"],
                "minutes": lesson.get("minutes"),
                "steps": steps,
            })
        return {
            "contract_version": CONTRACT_VERSION,
            "claim_boundary": self.claim_boundary,
            "lessons": safe,
        }

    def score(self, lesson_id: str, chosen_index: Any) -> dict[str, Any]:
        """Score the lesson's decide step by exact match. Fully deterministic."""
        lesson = self.get(lesson_id)
        step = next(step for step in lesson["steps"] if step["kind"] == "decide")
        if not isinstance(chosen_index, int) or not 0 <= chosen_index < len(step["options"]):
            raise LessonError("Choose one of the offered options.")
        correct = chosen_index == step["correct_index"]
        return {
            "lesson_id": lesson_id,
            "skill": lesson["skill"],
            "correct": correct,
            "correct_index": step["correct_index"],
            "rationale": step["rationale"],
            "encouragement": (
                "That's the one. Practice recorded."
                if correct else
                "Not quite — and this is exactly the distinction worth having. Read the reasoning, then try again."
            ),
        }
