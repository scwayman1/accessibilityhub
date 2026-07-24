import datetime as dt
import json
import unittest
from pathlib import Path

from tina.learning import POINT_VALUES, STREAK_BADGE_DAYS, LearningJourney

DOC_A = "sha256:" + "a" * 64
DOC_B = "sha256:" + "b" * 64
DOC_C = "sha256:" + "c" * 64


def stamp(days_ago: int) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)).isoformat()


class PointsTests(unittest.TestCase):
    def test_points_reward_evidence_producing_actions_only(self):
        journey = LearningJourney()
        journey.record_review(DOC_A, ["PDF.METADATA.TITLE"])
        journey.record_fix(DOC_A, ["PDF.METADATA.TITLE", "PDF.METADATA.LANGUAGE"])
        journey.record_attestation("PDF.IMAGES.ALTERNATIVES", "Reviewed all images.")
        journey.record_activity("convert", DOC_A)
        journey.record_activity("receipt", DOC_A)

        points = journey.journey()["points"]
        expected = (POINT_VALUES["review"] + POINT_VALUES["fix_skill"]  # one skill: both rules map to titles_and_language
                    + POINT_VALUES["attestation"] + POINT_VALUES["convert"] + POINT_VALUES["receipt"])
        self.assertEqual(points["total"], expected)
        self.assertIn("never measure or imply", points["claim_boundary"])

    def test_sustained_skills_earn_bonus_and_milestones_progress(self):
        journey = LearningJourney()
        journey.record_review(DOC_A, ["PDF.METADATA.TITLE"])
        journey.record_fix(DOC_A, ["PDF.METADATA.TITLE"])
        journey.record_review(DOC_B, [])
        journey.record_review(DOC_C, [])
        points = journey.journey()["points"]
        self.assertEqual(points["breakdown"]["sustained_skill"], POINT_VALUES["sustained_skill"])
        self.assertEqual(points["milestone"]["current"], "Barrier Spotter")
        self.assertIn("points_to_next", points["milestone"])

    def test_unknown_activity_types_are_ignored(self):
        journey = LearningJourney()
        journey.record_activity("clicked_next")
        self.assertEqual(journey.journey()["points"]["total"], 0)


class StreakTests(unittest.TestCase):
    def _journey_with_event_days(self, days_ago: list[int]) -> LearningJourney:
        journey = LearningJourney()
        for offset in days_ago:
            journey.events.append({"type": "review", "document": "x" * 16,
                                   "skills_with_findings": [], "recorded_at": stamp(offset)})
        return journey

    def test_consecutive_days_count_and_today_is_active(self):
        streak = self._journey_with_event_days([2, 1, 0]).journey()["streak"]
        self.assertEqual(streak["days"], 3)
        self.assertTrue(streak["active_today"])

    def test_streak_survives_one_quiet_day_with_grace_message(self):
        streak = self._journey_with_event_days([3, 2, 1]).journey()["streak"]
        self.assertEqual(streak["days"], 3)
        self.assertFalse(streak["active_today"])
        self.assertIn("grace", streak["message"])

    def test_streak_message_is_humane_after_a_break(self):
        streak = self._journey_with_event_days([10, 9]).journey()["streak"]
        self.assertEqual(streak["days"], 0)
        self.assertIn("No guilt", streak["message"])


class BadgeTests(unittest.TestCase):
    def test_badges_are_earned_only_by_evidence(self):
        journey = LearningJourney()
        badges = {b["id"]: b["earned"] for b in journey.journey()["badges"]}
        self.assertFalse(any(badges.values()))

        journey.record_activity("receipt", DOC_A)
        journey.record_activity("convert", DOC_A)
        journey.record_attestation("PDF.IMAGES.ALTERNATIVES", "Two decorative, one described.")
        journey.record_fix(DOC_A, ["PDF.METADATA.TITLE"])
        badges = {b["id"]: b["earned"] for b in journey.journey()["badges"]}
        self.assertTrue(badges["evidence_builder"])
        self.assertTrue(badges["pdf_escape_artist"])
        self.assertTrue(badges["meaningful_image_reviewer"])
        self.assertTrue(badges["metadata_mender"])
        self.assertFalse(badges["sustained_practice"])

    def test_streak_keeper_badge_requires_consecutive_days(self):
        journey = LearningJourney()
        for offset in range(STREAK_BADGE_DAYS):
            journey.events.append({"type": "review", "document": "x" * 16,
                                   "skills_with_findings": [], "recorded_at": stamp(offset)})
        badges = {b["id"]: b["earned"] for b in journey.journey()["badges"]}
        self.assertTrue(badges["streak_keeper"])


class FoundationAdsTests(unittest.TestCase):
    def test_ads_content_is_authored_valid_and_disclosed(self):
        ads = json.loads(Path("foundation_ads.json").read_text())
        self.assertTrue(ads["enabled"])
        self.assertEqual(ads["sponsor"], "Coastline College Foundation")
        self.assertTrue(ads["link"].startswith("https://"))
        self.assertIn("sponsor", ads["disclosure"].lower())
        self.assertGreaterEqual(len(ads["items"]), 5)
        for item in ads["items"]:
            self.assertIsInstance(item, str)
            self.assertLess(len(item), 300)

    def test_ads_never_use_prohibited_outcome_language(self):
        text = Path("foundation_ads.json").read_text().lower()
        for phrase in ["fully compliant", "certified accessible", "passed accessibility",
                       "guaranteed accessible", "fully accessible"]:
            self.assertNotIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
