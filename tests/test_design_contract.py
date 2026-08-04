import unittest
from pathlib import Path


def contrast_ratio(foreground: str, background: str) -> float:
    def luminance(color: str) -> float:
        channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


class AccessibleDesignContractTests(unittest.TestCase):
    """The four UI surfaces share measurable navigation, type, state, and motion rules."""

    def setUp(self):
        self.public = Path("index.html").read_text()
        self.sample = Path("sample-review.html").read_text()
        self.local = Path("local_reviewer.html").read_text()
        self.staging = Path("service/app.py").read_text()

    def test_every_surface_exposes_a_keyboard_skip_target(self):
        for source in (self.public, self.sample, self.local):
            self.assertIn('class="skip-link" href="#main-content"', source)
            self.assertIn('id="main-content" tabindex="-1"', source)
        self.assertIn('<body id="top">', self.public)
        self.assertIn('class=skip-link href="#main-content"', self.staging)
        self.assertIn('id=main-content class=main-workspace tabindex="-1"', self.staging)

    def test_every_surface_uses_a_16_pixel_body_base(self):
        self.assertIn("font:16px/1.5 var(--sans)", self.public)
        self.assertIn("font:16px/1.5 var(--sans)", self.sample)
        self.assertIn("font:16px/1.5 var(--sans)", self.local)
        self.assertIn("font:16px/1.55 Inter", self.staging)

    def test_all_workflow_rails_use_the_shared_model(self):
        for label in ("Review", "Understand", "Improve", "Verify"):
            self.assertIn(f"<span>{label}</span>", self.local)
            self.assertIn(f'"{label}"', self.staging)

    def test_every_surface_honors_reduced_motion(self):
        for source in (self.public, self.sample, self.local, self.staging):
            self.assertIn("prefers-reduced-motion", source)

    def test_public_step_label_meets_normal_text_contrast(self):
        self.assertIn(".step-index { color:#0e7c66; font:14px", self.public)
        self.assertGreaterEqual(contrast_ratio("#0e7c66", "#ffffff"), 4.5)

    def test_functional_secondary_type_has_a_14_pixel_floor(self):
        self.assertIn(".brand small,.nav-links,.nav-cta,.button", self.public)
        self.assertIn(".path-card .path-kind { margin:0 0 7px; color:var(--teal); font:750 14px", self.public)
        self.assertIn(".brand small,.back,.eyebrow", self.sample)
        self.assertIn(".steps li,.upload p,.btn", self.local)
        self.assertIn("#meta{font:14px var(--mono);color:var(--muted)}", self.local)
        self.assertIn("@media(max-width:760px){.bar .scope{display:none}", self.local)
        self.assertIn(".eyebrow,.small,.product-lockup span", self.staging)
        for source in (self.public, self.sample, self.local, self.staging):
            self.assertIn("font-size:14px", source)

    def test_sponsor_content_never_becomes_a_live_region(self):
        scan_ad = self.local.split('id="scanAd"', 1)[1].split(">", 1)[0]
        fix_ad = self.local.split('id="fixAd"', 1)[1].split(">", 1)[0]
        self.assertNotIn("aria-live", scan_ad)
        self.assertNotIn("aria-live", fix_ad)
        self.assertIn('id="scanMessage" role="status" aria-live="polite"', self.local)

    def test_errors_are_assertive_and_routine_status_is_polite(self):
        self.assertIn("isError?'alert':'status'", self.local)
        self.assertIn("isError?'assertive':'polite'", self.local)

    def test_unknown_finding_categories_remain_visible(self):
        self.assertIn("const ungrouped=docFindings.filter", self.local)
        self.assertIn("label:'Review next'", self.local)
        self.assertIn("New finding types stay visible here", self.local)


if __name__ == "__main__":
    unittest.main()
