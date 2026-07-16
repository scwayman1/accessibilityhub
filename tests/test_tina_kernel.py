import unittest
from pathlib import Path

from tina.kernel import DeterministicScan, ToolManifest, ToolPermissionError


class TinaKernelContractTests(unittest.TestCase):
    def test_scan_returns_versioned_evidence_backed_finding_without_conformance_claim(self):
        scan = DeterministicScan.with_builtin_pdf_intake_tools()
        result = scan.inspect_bytes(
            filename="course.pdf",
            payload=b"%PDF-1.7\nexample",
            declared_mime_type="application/pdf",
        )

        self.assertEqual(result["contract_version"], "tina-scan-report/v1")
        self.assertEqual(result["document"]["dar_version"], "tina-dar/v0")
        self.assertFalse(result["conformance_determined"])
        self.assertEqual(result["findings"][0]["rule_id"], "TINA-INTAKE-PDF-001")
        self.assertEqual(result["findings"][0]["evidence"][0]["tool"], "inspect_file_signature")
        self.assertEqual(result["findings"][0]["rule_version"], "1.0.0")

    def test_gateway_rejects_unregistered_tool_permission(self):
        scan = DeterministicScan.with_builtin_pdf_intake_tools()
        with self.assertRaises(ToolPermissionError):
            scan.gateway.execute("arbitrary_shell", {}, {"document.structure.read"})

    def test_tool_manifest_requires_explicit_read_only_mutation_status(self):
        with self.assertRaises(ValueError):
            ToolManifest(
                name="bad_tool",
                version="1.0.0",
                purpose="invalid test tool",
                deterministic=True,
                mutates_document=None,
                permissions=("document.structure.read",),
            )


if __name__ == "__main__":
    unittest.main()
