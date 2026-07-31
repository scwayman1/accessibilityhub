import re
import unittest
from pathlib import Path


class UnifiedEntryTests(unittest.TestCase):
    """The two public entry files expose one honest, task-first front door."""

    def setUp(self):
        self.index = Path("index.html").read_text()
        self.landing = Path("landing.html").read_text()

    def test_public_entry_aliases_stay_in_sync(self):
        self.assertEqual(self.index, self.landing)

    def test_entry_offers_safe_sample_and_local_review_paths(self):
        self.assertIn("Try a guided sample", self.index)
        self.assertIn('href="sample-review.html"', self.index)
        self.assertIn("Review a PDF on this computer", self.index)
        self.assertIn('href="http://127.0.0.1:8765/"', self.index)

    def test_local_path_names_its_loopback_and_privacy_boundary(self):
        self.assertIn("Available after the loopback reviewer is started locally", self.index)
        self.assertIn("Your PDF stays on this computer", self.index)
        self.assertIn('aria-describedby="local-path-note"', self.index)

    def test_public_entry_uses_the_shared_four_step_model(self):
        for label in ("REVIEW", "UNDERSTAND", "IMPROVE", "VERIFY"):
            self.assertIn(f"/ {label}", self.index)
        self.assertIn("Review → Understand → Improve → Verify", self.index)

    def test_narrow_navigation_keeps_every_destination_available(self):
        self.assertNotIn('.nav-links a:not(.nav-cta) { display:none; }', self.index)
        for destination in ('href="#how-it-works"', 'href="#boundaries"', 'href="#choose-path"'):
            self.assertIn(destination, self.index)


class GuidedSampleTests(unittest.TestCase):
    """The public sample is interactive while remaining unmistakably synthetic."""

    def setUp(self):
        self.source = Path("sample-review.html").read_text()

    def test_sample_keeps_the_no_upload_boundary(self):
        self.assertIn("This page has no file picker or analysis service", self.source)
        self.assertNotIn('type="file"', self.source)
        self.assertNotIn("type=file", self.source)

    def test_sample_exposes_the_same_four_step_model(self):
        for label in ("1 · Review", "2 · Understand", "3 · Improve", "4 · Verify"):
            self.assertIn(label, self.source)

    def test_each_finding_is_a_native_toggle_button(self):
        buttons = re.findall(r'<button class="lane [^"]+"[^>]+>', self.source)
        self.assertEqual(len(buttons), 4)
        self.assertEqual(sum('aria-pressed="true"' in button for button in buttons), 1)
        self.assertEqual(sum('aria-pressed="false"' in button for button in buttons), 3)

    def test_guidance_reveals_evidence_impact_action_and_verification(self):
        for detail_id in ("detailEvidence", "detailImpact", "detailAction", "detailVerify"):
            self.assertIn(f'id="{detail_id}"', self.source)
        self.assertIn('role="status" aria-live="polite"', self.source)

    def test_selection_is_programmatic_and_focus_managed(self):
        self.assertIn('button.setAttribute("aria-pressed"', self.source)
        self.assertIn("if (moveFocus) detailTitle.focus()", self.source)
        self.assertIn('tabindex="-1"', self.source)

    def test_lane_focus_ring_contrasts_with_its_light_surface(self):
        self.assertIn(".lane:focus-visible { outline-color:#176878; }", self.source)


if __name__ == "__main__":
    unittest.main()
