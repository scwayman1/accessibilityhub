import ast
import unittest
from pathlib import Path


class PdfWorkerHardeningTests(unittest.TestCase):
    def test_verapdf_worker_uses_pinned_local_image_with_no_pull_and_no_network(self):
        source = Path("check_pdf.py").read_text()
        tree = ast.parse(source)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_verapdf")
        literals = {node.value for node in ast.walk(function) if isinstance(node, ast.Constant) and isinstance(node.value, str)}

        for required in {"--pull=never", "--network", "none", ":/input:ro"}:
            self.assertIn(required, literals)
        for command_token in {"docker", "image", "inspect"}:
            self.assertIn(command_token, literals)
        self.assertIn("will not pull images during a check", source)


if __name__ == "__main__":
    unittest.main()
