import json
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from local_reviewer import create_server
from tina.learning import POINT_VALUES, SKILLS, LearningJourney
from tina.lessons import LessonError, LessonLibrary

DOC_A = "sha256:" + "a" * 64
DOC_B = "sha256:" + "b" * 64
DOC_C = "sha256:" + "c" * 64


def write_library(payload: dict) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(payload, handle)
    handle.close()
    return Path(handle.name)


def minimal_lesson(**overrides) -> dict:
    lesson = {
        "lesson_id": "demo-101",
        "skill": "images_and_meaning",
        "title": "Demo",
        "steps": [
            {"kind": "encounter", "body": "A situation."},
            {"kind": "decide", "prompt": "Which?", "options": ["Right", "Wrong"],
             "correct_index": 0, "rationale": "Because."},
        ],
    }
    lesson.update(overrides)
    return lesson


class LessonContentTests(unittest.TestCase):
    def test_shipped_content_loads_and_covers_every_skill(self):
        library = LessonLibrary()
        covered = {lesson["skill"] for lesson in library.lessons}
        self.assertEqual(covered, set(SKILLS), f"Skills without a lesson: {sorted(set(SKILLS) - covered)}")

    def test_every_shipped_lesson_follows_the_prd_sequence(self):
        library = LessonLibrary()
        for lesson in library.lessons:
            kinds = [step["kind"] for step in lesson["steps"]]
            for required in ("encounter", "experience", "explain", "decide", "verify", "transfer"):
                self.assertIn(required, kinds, f"{lesson['lesson_id']} is missing the {required} step")
            self.assertEqual(kinds.count("decide"), 1)

    def test_catalog_withholds_the_correct_answer(self):
        catalog = LessonLibrary().catalog()
        payload = json.dumps(catalog)
        self.assertNotIn("correct_index", payload)
        self.assertNotIn("rationale", payload)
        decide = next(s for s in catalog["lessons"][0]["steps"] if s["kind"] == "decide")
        self.assertGreaterEqual(len(decide["options"]), 2)

    def test_catalog_filters_by_skill(self):
        catalog = LessonLibrary().catalog("images_and_meaning")
        self.assertTrue(catalog["lessons"])
        self.assertTrue(all(l["skill"] == "images_and_meaning" for l in catalog["lessons"]))


class LessonValidationTests(unittest.TestCase):
    def test_unknown_skill_is_rejected(self):
        path = write_library({"lessons": [minimal_lesson(skill="interpretive_dance")]})
        with self.assertRaises(LessonError):
            LessonLibrary(path)

    def test_out_of_range_correct_index_is_rejected(self):
        bad = minimal_lesson()
        bad["steps"][1]["correct_index"] = 7
        with self.assertRaises(LessonError):
            LessonLibrary(write_library({"lessons": [bad]}))

    def test_duplicate_lesson_ids_are_rejected(self):
        with self.assertRaises(LessonError):
            LessonLibrary(write_library({"lessons": [minimal_lesson(), minimal_lesson()]}))

    def test_missing_rationale_is_rejected(self):
        bad = minimal_lesson()
        bad["steps"][1]["rationale"] = "   "
        with self.assertRaises(LessonError):
            LessonLibrary(write_library({"lessons": [bad]}))


class LessonScoringTests(unittest.TestCase):
    def setUp(self):
        self.library = LessonLibrary(write_library({"lessons": [minimal_lesson()]}))

    def test_correct_answer_scores_and_explains(self):
        result = self.library.score("demo-101", 0)
        self.assertTrue(result["correct"])
        self.assertEqual(result["skill"], "images_and_meaning")
        self.assertEqual(result["rationale"], "Because.")

    def test_wrong_answer_is_not_punitive_and_reveals_the_reasoning(self):
        result = self.library.score("demo-101", 1)
        self.assertFalse(result["correct"])
        self.assertEqual(result["correct_index"], 0)
        self.assertIn("worth having", result["encouragement"])

    def test_out_of_range_choice_is_rejected(self):
        with self.assertRaises(LessonError):
            self.library.score("demo-101", 9)

    def test_unknown_lesson_is_rejected(self):
        with self.assertRaises(LessonError):
            self.library.score("no-such-lesson", 0)


class PracticedMasteryTests(unittest.TestCase):
    def test_passed_lesson_reaches_practiced(self):
        journey = LearningJourney()
        journey.record_lesson("images_and_meaning", "images-101", passed=True)
        skill = journey.journey()["skills"]["images_and_meaning"]
        self.assertEqual(skill["state"], "practiced")
        self.assertEqual(skill["lessons_passed"], ["images-101"])

    def test_failed_lesson_records_nothing(self):
        journey = LearningJourney()
        journey.record_lesson("images_and_meaning", "images-101", passed=False)
        self.assertEqual(journey.journey()["skills"]["images_and_meaning"]["state"], "not_started")

    def test_lesson_never_outranks_real_document_evidence(self):
        journey = LearningJourney()
        journey.record_review(DOC_A, ["PDF.METADATA.TITLE"])
        journey.record_fix(DOC_A, ["PDF.METADATA.TITLE"])
        journey.record_lesson("titles_and_language", "titles-and-language-101", passed=True)
        self.assertEqual(journey.journey()["skills"]["titles_and_language"]["state"], "verified")

    def test_full_ladder_introduced_practiced_applied_verified_sustained(self):
        journey = LearningJourney()
        journey.record_review(DOC_A, ["PDF.METADATA.TITLE"])
        self.assertEqual(journey.journey()["skills"]["titles_and_language"]["state"], "introduced")
        journey.record_lesson("titles_and_language", "titles-and-language-101", passed=True)
        self.assertEqual(journey.journey()["skills"]["titles_and_language"]["state"], "practiced")
        journey.record_attestation("PDF.METADATA.TITLE", "Set the title from the course catalog.")
        self.assertEqual(journey.journey()["skills"]["titles_and_language"]["state"], "applied")
        journey.record_fix(DOC_A, ["PDF.METADATA.TITLE"])
        self.assertEqual(journey.journey()["skills"]["titles_and_language"]["state"], "verified")
        journey.record_review(DOC_B, [])
        journey.record_review(DOC_C, [])
        self.assertEqual(journey.journey()["skills"]["titles_and_language"]["state"], "sustained")

    def test_regression_falls_back_to_practiced_not_below(self):
        journey = LearningJourney()
        journey.record_lesson("titles_and_language", "titles-and-language-101", passed=True)
        journey.record_review(DOC_A, ["PDF.METADATA.TITLE"])
        journey.record_fix(DOC_A, ["PDF.METADATA.TITLE"])
        journey.record_review(DOC_B, ["PDF.METADATA.TITLE"])
        skill = journey.journey()["skills"]["titles_and_language"]
        self.assertTrue(skill["regressed"])
        self.assertEqual(skill["state"], "practiced")

    def test_lesson_points_count_distinct_lessons_only(self):
        journey = LearningJourney()
        journey.record_lesson("images_and_meaning", "images-101", passed=True)
        journey.record_lesson("images_and_meaning", "images-101", passed=True)
        points = journey.journey()["points"]
        self.assertEqual(points["breakdown"]["lesson"], POINT_VALUES["lesson"])

    def test_guided_learner_badge_is_earned_by_passing(self):
        journey = LearningJourney()
        self.assertFalse({b["id"]: b["earned"] for b in journey.journey()["badges"]}["guided_learner"])
        journey.record_lesson("links_and_navigation", "links-101", passed=True)
        self.assertTrue({b["id"]: b["earned"] for b in journey.journey()["badges"]}["guided_learner"])


class LessonEndpointTests(unittest.TestCase):
    def setUp(self):
        self.journey = LearningJourney()
        self.server = create_server(0, lambda pdf, out: {"findings": []}, journey=self.journey)
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def post(self, path: str, payload: dict):
        request = Request(self.base + path, data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read())

    def test_lessons_endpoint_serves_the_catalog(self):
        with urlopen(self.base + "/api/lessons", timeout=10) as response:
            catalog = json.loads(response.read())
        self.assertEqual(len(catalog["lessons"]), len(SKILLS))
        self.assertNotIn("correct_index", json.dumps(catalog))

    def test_lesson_result_scores_and_advances_the_journey(self):
        result = self.post("/api/lesson-result", {"lesson_id": "images-101", "chosen_index": 0})
        self.assertTrue(result["correct"])
        self.assertEqual(result["journey"]["skills"]["images_and_meaning"]["state"], "practiced")

    def test_wrong_answer_does_not_advance_mastery(self):
        result = self.post("/api/lesson-result", {"lesson_id": "images-101", "chosen_index": 1})
        self.assertFalse(result["correct"])
        self.assertEqual(result["journey"]["skills"]["images_and_meaning"]["state"], "not_started")

    def test_invalid_choice_is_rejected(self):
        with self.assertRaises(HTTPError) as context:
            self.post("/api/lesson-result", {"lesson_id": "images-101", "chosen_index": 99})
        self.assertEqual(context.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
