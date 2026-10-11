"""veraPDF: report summary parsing, the local runner, and our produced PDFs under the UA-1 profile."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import check_pdf

LOCAL_VERAPDF = check_pdf.local_verapdf_command()

SAMPLE = {"report": {"jobs": [{"validationResult": [{
    "compliant": False, "profileName": "PDF/UA-1 validation profile",
    "details": {"failedRules": 2, "ruleSummaries": [
        {"status": "failed", "clause": "7.1", "testNumber": 10, "failedChecks": 1,
         "description": "The document catalog dictionary shall include a ViewerPreferences dictionary containing a DisplayDocTitle key"},
        {"status": "passed", "clause": "7.2", "testNumber": 1, "failedChecks": 0, "description": "ok"},
        {"status": "failed", "clause": "7.21.4.1", "testNumber": 1, "failedChecks": 3, "description": "Fonts shall be embedded"},
    ]},
}]}]}}


class SummaryTests(unittest.TestCase):
    def test_failed_rules_are_extracted_without_a_verdict(self):
        summary = check_pdf.summarize_verapdf(json.dumps(SAMPLE))
        self.assertFalse(summary["profile_compliant"])
        self.assertEqual([rule["clause"] for rule in summary["failed_rules"]], ["7.1", "7.21.4.1"])
        self.assertEqual(summary["failed_rule_count"], 2)

    def test_unparseable_output_is_reported_not_raised(self):
        self.assertIn("report_parse_error", check_pdf.summarize_verapdf("not json"))

    def test_local_command_resolution_prefers_the_configured_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "verapdf"
            fake.write_text("#!/bin/sh\nexit 0\n")
            fake.chmod(0o755)
            with mock.patch.dict(os.environ, {"VERAPDF_BIN": str(fake)}):
                self.assertEqual(check_pdf.local_verapdf_command(), str(fake))
            with mock.patch.dict(os.environ, {"VERAPDF_BIN": str(Path(directory) / "absent")}):
                self.assertIsNone(check_pdf.local_verapdf_command())

    def test_local_runner_summarizes_a_fake_validator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / "verapdf"
            fake.write_text("#!/bin/sh\ncat <<'JSON'\n" + json.dumps(SAMPLE) + "\nJSON\n")
            fake.chmod(0o755)
            pdf = root / "doc.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            with mock.patch.dict(os.environ, {"VERAPDF_BIN": str(fake)}):
                result = check_pdf.run_verapdf(pdf, root)
        self.assertEqual(result["runner"], "local")
        self.assertFalse(result["profile_compliant"])
        self.assertEqual(len(result["failed_rules"]), 2)


@unittest.skipUnless(LOCAL_VERAPDF, "veraPDF is not installed (scripts/install_verapdf.sh)")
class RealValidatorTests(unittest.TestCase):
    def test_produced_pdf_has_no_failed_ua1_machine_checks(self):
        try:
            from tina.author import render_pdf
        except ImportError:  # pragma: no cover
            self.skipTest("WeasyPrint is not installed")
        from tests.test_author import full_model

        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "produced.pdf"
            pdf.write_bytes(render_pdf(full_model()))
            result = check_pdf.run_verapdf(pdf, Path(directory))
        self.assertEqual(result["failed_rules"], [], json.dumps(result["failed_rules"], indent=1))
        self.assertTrue(result["profile_compliant"])

    def test_an_untagged_source_is_flagged(self):
        from tests.test_html_draft import text_pdf

        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "plain.pdf"
            pdf.write_bytes(text_pdf("Hello", title="Week 1", language="en-US"))
            result = check_pdf.run_verapdf(pdf, Path(directory))
        self.assertFalse(result["profile_compliant"])
        self.assertTrue(result["failed_rules"])


class CommandVersionTests(unittest.TestCase):
    def test_a_silent_tool_has_no_version_instead_of_crashing_the_review(self):
        with mock.patch.object(check_pdf, "run", return_value={"returncode": 0, "stdout": "", "stderr": ""}):
            self.assertIsNone(check_pdf.command_version(["sometool", "--version"]))
        with mock.patch.object(check_pdf, "run", return_value={"returncode": 0, "stdout": "tool 1.2\nmore", "stderr": ""}):
            self.assertEqual(check_pdf.command_version(["sometool", "--version"]), "tool 1.2")


if __name__ == "__main__":
    unittest.main()
