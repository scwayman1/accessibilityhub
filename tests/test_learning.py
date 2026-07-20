import json
import tempfile
import unittest
from pathlib import Path

from tina.learning import SUSTAIN_DOCUMENTS, LearningJourney


DOC_A = "sha256:" + "a" * 64
DOC_B = "sha256:" + "b" * 64
DOC_C = "sha256:" + "c" * 64
DOC_D = "sha256:" + "d" * 64


class MasteryProgressionTests(unittest.TestCase):
    def test_finding_introduces_skill(self):
        journey = LearningJourney()
        journey.record_review(DOC_A, ["PDF.METADATA.TITLE"])
        state = journey.journey()["skills"]["titles_and_language"]
        self.assertEqual(state["state"], "introduced")

    def test_verified_fix_advances_to_verified(self):
        journey = LearningJourney()
        journey.record_review(DOC_A, ["PDF.METADATA.TITLE"])
        journey.record_fix(DOC_A, ["PDF.METADATA.TITLE"])
        self.assertEqual(journey.journey()["skills"]["titles_and_language"]["state"], "verified")

    def test_attestation_advances_judgment_skill_to_applied(self):
        journey = LearningJourney()
        journey.record_review(DOC_A, ["PDF.IMAGES.ALTERNATIVES"])
        journey.record_attestation("PDF.IMAGES.ALTERNATIVES", "Reviewed all images; two are decorative.")
        self.assertEqual(journey.journey()["skills"]["images_and_meaning"]["state"], "applied")

    def test_sustained_requires_clean_subsequent_distinct_documents(self):
        journey = LearningJourney()
        journey.record_review(DOC_A, ["PDF.METADATA.TITLE"])
        journey.record_fix(DOC_A, ["PDF.METADATA.TITLE"])
        journey.record_review(DOC_B, [])
        self.assertEqual(journey.journey()["skills"]["titles_and_language"]["state"], "verified")
        journey.record_review(DOC_C, [])
        self.assertEqual(journey.journey()["skills"]["titles_and_language"]["state"], "sustained")
        self.assertEqual(SUSTAIN_DOCUMENTS, 2)

    def test_regression_resets_mastery_and_is_reported(self):
        journey = LearningJourney()
        journey.record_review(DOC_A, ["PDF.METADATA.TITLE"])
        journey.record_fix(DOC_A, ["PDF.METADATA.TITLE"])
        journey.record_review(DOC_B, ["PDF.METADATA.TITLE"])
        state = journey.journey()["skills"]["titles_and_language"]
        self.assertEqual(state["state"], "introduced")
        self.assertTrue(state["regressed"])

    def test_repeat_defects_flag_skills_seen_in_multiple_documents(self):
        journey = LearningJourney()
        journey.record_review(DOC_A, ["PDF.IMAGES.ALTERNATIVES"])
        journey.record_review(DOC_B, ["PDF.IMAGES.ALTERNATIVES"])
        repeats = journey.journey()["repeat_defects"]
        self.assertEqual(len(repeats), 1)
        self.assertEqual(repeats[0]["skill"], "images_and_meaning")
        self.assertEqual(repeats[0]["documents_affected"], 2)

    def test_same_document_reviewed_twice_is_not_a_repeat_defect(self):
        journey = LearningJourney()
        journey.record_review(DOC_A, ["PDF.IMAGES.ALTERNATIVES"])
        journey.record_review(DOC_A, ["PDF.IMAGES.ALTERNATIVES"])
        self.assertEqual(journey.journey()["repeat_defects"], [])


class JourneyPrivacyAndPersistenceTests(unittest.TestCase):
    def test_events_persist_to_disk_and_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journey.json"
            journey = LearningJourney(path)
            journey.record_review(DOC_A, ["PDF.METADATA.TITLE"])
            reloaded = LearningJourney(path)
            self.assertEqual(reloaded.journey()["skills"]["titles_and_language"]["state"], "introduced")

    def test_store_contains_only_hash_prefixes_never_full_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journey.json"
            journey = LearningJourney(path)
            journey.record_review(DOC_A, ["PDF.METADATA.TITLE"])
            stored = path.read_text()
            self.assertNotIn("a" * 64, stored)
            self.assertIn("a" * 16, stored)

    def test_review_without_hash_is_ignored(self):
        journey = LearningJourney()
        journey.record_review(None, ["PDF.METADATA.TITLE"])
        self.assertEqual(journey.journey()["documents_reviewed"], 0)

    def test_journey_carries_claim_boundary_not_certification(self):
        journey = LearningJourney()
        payload = json.dumps(journey.journey())
        self.assertIn("not accessibility certifications", payload)


if __name__ == "__main__":
    unittest.main()
