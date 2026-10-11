"""PdfCraft integration: a second-opinion checker, a tagged-PDF fixer, a renderer.

PdfCraft (https://github.com/storytold/pdfcraft, MIT OR Apache-2.0) is the
open-source, Acrobat-comparable PDF workbench from the ArtCraft suite. The Hub
drives its headless command-line tool (``pdfcraft-cli``, built by
``scripts/build_pdfcraft.sh`` at one pinned commit) as a subprocess:

* ``document.check.pdfcraft`` — its Acrobat-style accessibility checker
  (32 rules). A second opinion only: its failures route to *Review
  recommended*, never straight to a verdict, and where it disagrees with the
  Hub's own rule pack a person decides.
* ``document.remediate.pdfcraft_semantics`` — language, title, figure alt text
  and decorative marking **on PDFs that are already tagged**, the case the
  Hub's own structure tool declines. Mutates a copy only, with before/after
  hashes and a page-count/text preservation check.
* ``document.render.page`` — page images, so a person can see the page they are
  describing.

Each call runs in a fresh temporary root with a minimal environment; the tool
needs no network and is given none of the proxy settings. When the binary is
absent every entry point raises ``PdfCraftUnavailable`` and reviews disclose
the skipped check instead of failing.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from tina.kernel import ToolGateway, ToolManifest
from tina.remedy import RemediationError

CHECK_PERMISSION = "document.check.pdfcraft"
SEMANTICS_PERMISSION = "document.remediate.pdfcraft_semantics"
RENDER_PERMISSION = "document.render.page"
PINNED_REV = "bbbe60015c571ebfc39708ee07777b89e267122a"
BINARY_NAME = "pdfcraft-cli"
REPO_ROOT = Path(__file__).resolve().parents[1]

# PdfCraft rule -> the Hub rule that looks at the same thing. Used only to
# surface disagreements for a person; it never overrides either checker.
RULE_MAP = {
    "title": "PDF.METADATA.TITLE",
    "primary-language": "PDF.METADATA.LANGUAGE",
    "tagged-pdf": "PDF.STRUCTURE.SEMANTICS",
    "tagged-content": "PDF.STRUCTURE.SEMANTICS",
    "image-only": "PDF.TEXT_LAYER",
    "figures-alt-text": "PDF.IMAGES.ALT_MISSING",
    "tagged-annotations": "PDF.LINKS.NAME",
}

CLAIM_BOUNDARY = (
    "PdfCraft's accessibility checker is a second opinion modeled on Acrobat's "
    "checker. Its results are technical evidence for a person to review, not a "
    "conformance result."
)


class PdfCraftUnavailable(RuntimeError):
    """The pinned pdfcraft-cli binary is not installed in this environment."""


class PdfCraftError(RuntimeError):
    """pdfcraft-cli ran but did not complete the requested steps."""


def find_binary() -> str | None:
    """``PDFCRAFT_BIN``, then ``vendor-bin/pdfcraft-cli``, then ``PATH``."""
    configured = os.environ.get("PDFCRAFT_BIN", "").strip()
    if configured:
        return configured if Path(configured).is_file() and os.access(configured, os.X_OK) else None
    vendored = REPO_ROOT / "vendor-bin" / BINARY_NAME
    if vendored.is_file() and os.access(vendored, os.X_OK):
        return str(vendored)
    return shutil.which(BINARY_NAME)


@lru_cache(maxsize=4)
def _version_for(binary: str) -> str | None:
    try:
        completed = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10,
                                   env=_minimal_env(tempfile.gettempdir()), check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    line = (completed.stdout or completed.stderr).strip().splitlines()
    return line[0].strip() if line else None


def version() -> str | None:
    binary = find_binary()
    return _version_for(binary) if binary else None


def _minimal_env(home: str) -> dict[str, str]:
    # No proxy variables, no credentials: the tool has no reason to reach out.
    return {"PATH": "/usr/bin:/bin", "HOME": home, "LANG": "C.UTF-8"}


def parse_json_stream(text: str) -> list[Any]:
    """pdfcraft-cli ``run --script`` prints one JSON value per step, back to back."""
    decoder = json.JSONDecoder()
    values: list[Any] = []
    index = 0
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            return values
        try:
            value, index = decoder.raw_decode(text, index)
        except json.JSONDecodeError as error:
            raise PdfCraftError("pdfcraft-cli returned output that is not JSON.") from error
        values.append(value)


class PdfCraftRunner:
    """Run pdfcraft-cli steps against in-memory bytes in a throwaway root."""

    def __init__(self, binary: str | None = None, timeout: float = 60.0) -> None:
        self.binary = binary or find_binary()
        self.timeout = timeout

    def _require(self) -> str:
        if not self.binary:
            raise PdfCraftUnavailable(
                "PdfCraft is not installed in this environment (run scripts/build_pdfcraft.sh or set PDFCRAFT_BIN)."
            )
        return self.binary

    def _exec(self, arguments: list[str], root: Path) -> str:
        binary = self._require()
        try:
            completed = subprocess.run(
                [binary, *arguments], cwd=root, capture_output=True, text=True,
                timeout=self.timeout, env=_minimal_env(str(root)), check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise PdfCraftError(f"pdfcraft-cli did not finish within {self.timeout:g} seconds.") from error
        except OSError as error:
            raise PdfCraftUnavailable(f"pdfcraft-cli could not be started: {type(error).__name__}") from error
        if completed.returncode != 0:
            message = (completed.stderr or "").strip().splitlines()
            raise PdfCraftError((message[-1] if message else "pdfcraft-cli reported an error.")[:500])
        return completed.stdout

    def run_script(self, steps: list[dict[str, Any]], files: dict[str, bytes],
                   collect: tuple[str, ...] = ()) -> tuple[list[Any], dict[str, bytes]]:
        """Write ``files`` into a fresh root, run ``steps``, return (results, collected files)."""
        self._require()
        with tempfile.TemporaryDirectory(prefix="hub-pdfcraft-") as workdir:
            root = Path(workdir)
            for name, payload in files.items():
                (root / Path(name).name).write_bytes(payload)
            (root / "steps.json").write_text(json.dumps(steps))
            results = parse_json_stream(self._exec(["run", "--script", "steps.json", "--root", str(root)], root))
            collected = {name: (root / name).read_bytes() for name in collect if (root / name).is_file()}
        if len(results) != len(steps):
            raise PdfCraftError(f"pdfcraft-cli completed {len(results)} of {len(steps)} steps.")
        return results, collected

    def render(self, payload: bytes, page: int, dpi: int = 96) -> bytes:
        with tempfile.TemporaryDirectory(prefix="hub-pdfcraft-") as workdir:
            root = Path(workdir)
            (root / "in.pdf").write_bytes(payload)
            self._exec(["render", "in.pdf", "--page", str(int(page)), "--dpi", str(int(dpi)), "--out", "page.png"], root)
            output = root / "page.png"
            if not output.is_file():
                raise PdfCraftError("pdfcraft-cli did not write the page image.")
            return output.read_bytes()


def _summarize_check(raw: dict[str, Any]) -> dict[str, Any]:
    results = []
    for item in raw.get("results") or []:
        results.append({
            "rule": item.get("rule"),
            "name": item.get("name"),
            "category": item.get("category"),
            "status": item.get("status"),
            "findings": [
                {"message": str(f.get("message") or "")[:300], "page": f.get("page")}
                for f in (item.get("findings") or [])[:20] if isinstance(f, dict)
            ],
            "maps_to": RULE_MAP.get(str(item.get("rule"))),
        })
    return {
        "summary": {key: int(raw.get(key) or 0) for key in ("passed", "failed", "manual", "skipped")},
        "results": results,
    }


def _accessibility_check(input_data: dict[str, Any]) -> dict[str, Any]:
    runner: PdfCraftRunner = input_data["runner"]
    results, _ = runner.run_script(
        [{"tool": "doc_open", "args": {"path": "in.pdf"}}, {"tool": "accessibility_check", "args": {"doc": 1}}],
        {"in.pdf": input_data["payload"]},
    )
    return _summarize_check(results[-1])


def _list_figures(input_data: dict[str, Any]) -> dict[str, Any]:
    runner: PdfCraftRunner = input_data["runner"]
    results, _ = runner.run_script(
        [{"tool": "doc_open", "args": {"path": "in.pdf"}}, {"tool": "accessibility_figures", "args": {"doc": 1}}],
        {"in.pdf": input_data["payload"]},
    )
    figures = []
    for position, item in enumerate(results[-1].get("figures") or [], start=1):
        figures.append({"position": position, "figure": item.get("figure"), "page": item.get("page"),
                        "alt": item.get("alt"), "rect": item.get("rect")})
    return {"figures": figures}


def _page_texts(payload: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(payload), strict=False)
    return [" ".join((page.extract_text() or "").split()) for page in reader.pages]


def _semantic_fix(input_data: dict[str, Any]) -> dict[str, Any]:
    runner: PdfCraftRunner = input_data["runner"]
    payload: bytes = input_data["payload"]
    try:
        reader = PdfReader(io.BytesIO(payload), strict=False)
        root = reader.trailer["/Root"].get_object()
    except Exception as error:
        raise RemediationError(f"The PDF could not be parsed: {type(error).__name__}") from error
    if reader.is_encrypted:
        raise RemediationError("Encrypted PDFs are not changed; request an unencrypted source copy.")
    if "/StructTreeRoot" not in root:
        raise RemediationError(
            "This PDF has no tag structure, so there are no tagged figures to describe. "
            "Build tags from confirmed structure first, or produce an accessible copy instead."
        )
    figure_ids = [item["figure"] for item in _list_figures({"payload": payload, "runner": runner})["figures"]]
    steps: list[dict[str, Any]] = [{"tool": "doc_open", "args": {"path": "in.pdf"}}]
    actions: list[dict[str, Any]] = []
    language = str(input_data.get("language") or "").strip()
    title = str(input_data.get("title") or "").strip()
    if language:
        steps.append({"tool": "accessibility_fix", "args": {"doc": 1, "rule": "primary-language", "value": language}})
        actions.append({"rule_id": "PDF.METADATA.LANGUAGE", "action": "set_language", "provenance": "user_supplied"})
    if title:
        steps.append({"tool": "accessibility_fix", "args": {"doc": 1, "rule": "title", "value": title}})
        actions.append({"rule_id": "PDF.METADATA.TITLE", "action": "set_title", "provenance": "user_supplied"})
    for key, decision in sorted((input_data.get("figures") or {}).items(), key=lambda kv: int(kv[0])):
        figure = int(key)  # 1-based position in document order, as list_figures shows it
        if not 1 <= figure <= len(figure_ids):
            raise RemediationError(f"Figure {figure} is not one of the {len(figure_ids)} tagged figures in this PDF.")
        target = figure_ids[figure - 1]
        decision = decision or {}
        if decision.get("decorative"):
            steps.append({"tool": "accessibility_set_alt", "args": {"doc": 1, "figure": target, "decorative": True}})
            actions.append({"rule_id": "PDF.IMAGES.ALTERNATIVES", "action": "mark_decorative", "figure": figure, "provenance": "user_confirmed"})
        else:
            alt = " ".join(str(decision.get("alt") or "").split())
            if not alt:
                raise RemediationError(f"Figure {figure} needs a description or a decorative decision.")
            steps.append({"tool": "accessibility_set_alt", "args": {"doc": 1, "figure": target, "alt": alt[:1000]}})
            actions.append({"rule_id": "PDF.IMAGES.ALTERNATIVES", "action": "set_alt", "figure": figure, "provenance": "user_supplied"})
    if not actions:
        raise RemediationError("Nothing to change: supply a language, a title, or figure decisions.")
    steps.append({"tool": "doc_save", "args": {"doc": 1, "path": "out.pdf", "full": True}})
    try:
        _, collected = runner.run_script(steps, {"in.pdf": payload}, collect=("out.pdf",))
    except PdfCraftError as error:
        raise RemediationError(f"PdfCraft could not apply these changes: {error}") from error
    remediated = collected.get("out.pdf")
    if not remediated:
        raise RemediationError("PdfCraft did not write the changed copy.")
    # Asserted, never trusted: same pages, same text — only semantics changed.
    before, after = _page_texts(payload), _page_texts(remediated)
    if len(before) != len(after) or before != after:
        raise RemediationError("PdfCraft's copy did not preserve the pages and text exactly, so no output was produced.")
    return {
        "actions": actions,
        "verification": {"text_preserved": True, "pages_preserved": True},
        "source_sha256": f"sha256:{sha256(payload).hexdigest()}",
        "remediated_sha256": f"sha256:{sha256(remediated).hexdigest()}",
        "source_bytes": len(payload),
        "remediated_bytes": len(remediated),
        "remediated_payload": remediated,
    }


def _render_page(input_data: dict[str, Any]) -> dict[str, Any]:
    runner: PdfCraftRunner = input_data["runner"]
    image = runner.render(input_data["payload"], int(input_data.get("page") or 1), int(input_data.get("dpi") or 96))
    return {"png": image, "mime": "image/png", "page": int(input_data.get("page") or 1)}


class PdfCraft:
    """PdfCraft's checker, semantics fixer and renderer behind the tool gateway."""

    CONTRACT_VERSION = "tina-pdfcraft/v1"
    CLAIM_BOUNDARY = CLAIM_BOUNDARY

    def __init__(self, gateway: ToolGateway, runner: PdfCraftRunner) -> None:
        self.gateway = gateway
        self.runner = runner

    @classmethod
    def with_builtin_tools(cls, runner: PdfCraftRunner | None = None) -> "PdfCraft":
        gateway = ToolGateway()
        gateway.register(ToolManifest(
            name="pdfcraft_accessibility_check", version="1.0.0",
            purpose="Second-opinion accessibility check with PdfCraft's Acrobat-style rule set.",
            deterministic=True, mutates_document=False, permissions=(CHECK_PERMISSION,), timeout_ms=60_000,
        ), _accessibility_check)
        gateway.register(ToolManifest(
            name="pdfcraft_list_figures", version="1.0.0",
            purpose="List a tagged PDF's figures in document order with their current alt text.",
            deterministic=True, mutates_document=False, permissions=(CHECK_PERMISSION,), timeout_ms=60_000,
        ), _list_figures)
        gateway.register(ToolManifest(
            name="pdfcraft_semantic_fix", version="1.0.0",
            purpose="Apply human-supplied language, title, figure alt text, or decorative decisions to a copy of a tagged PDF.",
            deterministic=True, mutates_document=True, permissions=(SEMANTICS_PERMISSION,), timeout_ms=60_000,
        ), _semantic_fix)
        gateway.register(ToolManifest(
            name="pdfcraft_render_page", version="1.0.0",
            purpose="Render one page to a PNG so a person can see what they are reviewing.",
            deterministic=True, mutates_document=False, permissions=(RENDER_PERMISSION,), timeout_ms=30_000,
        ), _render_page)
        return cls(gateway, runner or PdfCraftRunner())

    @property
    def available(self) -> bool:
        return bool(self.runner.binary)

    def check(self, payload: bytes) -> dict[str, Any]:
        execution = self.gateway.execute("pdfcraft_accessibility_check", {"payload": payload, "runner": self.runner}, {CHECK_PERMISSION})
        return {"tool": "pdfcraft", "version": _version_for(self.runner.binary) if self.runner.binary else None,
                "pinned_rev": PINNED_REV, "claim_boundary": CLAIM_BOUNDARY, **execution["output"]}

    def list_figures(self, payload: bytes) -> list[dict[str, Any]]:
        execution = self.gateway.execute("pdfcraft_list_figures", {"payload": payload, "runner": self.runner}, {CHECK_PERMISSION})
        return execution["output"]["figures"]

    def apply_semantics(self, filename: str, payload: bytes, language: str | None = None, title: str | None = None,
                        figures: dict[str, dict[str, Any]] | None = None) -> tuple[bytes, dict[str, Any]]:
        execution = self.gateway.execute(
            "pdfcraft_semantic_fix",
            {"payload": payload, "runner": self.runner, "language": language, "title": title, "figures": figures},
            {SEMANTICS_PERMISSION},
        )
        remediated: bytes = execution["output"].pop("remediated_payload")
        return remediated, {
            "contract_version": self.CONTRACT_VERSION, "claim_boundary": CLAIM_BOUNDARY, "filename": filename,
            "tool": execution["tool"], "tool_version": execution["tool_version"],
            "deterministic": execution["deterministic"], "mutates_document": execution["mutates_document"],
            **execution["output"],
        }

    def render_page(self, payload: bytes, page: int = 1, dpi: int = 96) -> bytes:
        execution = self.gateway.execute("pdfcraft_render_page", {"payload": payload, "runner": self.runner, "page": page, "dpi": dpi}, {RENDER_PERMISSION})
        return execution["output"]["png"]


def second_opinion(payload: bytes, hub_findings: list[dict[str, Any]], hub_strengths: list[dict[str, Any]]) -> dict[str, Any]:
    """The report's ``second_opinion`` block: PdfCraft's results plus disagreements.

    Never raises: an absent or failing PdfCraft becomes an honest
    ``available: false`` block that the review discloses.
    """
    craft = PdfCraft.with_builtin_tools()
    if not craft.available:
        return {"tool": "pdfcraft", "available": False,
                "reason": "PdfCraft is not installed in this environment, so its second-opinion check did not run."}
    try:
        result = craft.check(payload)
    except (PdfCraftUnavailable, PdfCraftError) as error:
        return {"tool": "pdfcraft", "available": False, "reason": f"PdfCraft's check did not complete: {error}"}
    defects = {f.get("rule_id") for f in hub_findings if f.get("category") == "deterministic_defect"}
    strengths = {s.get("rule_id") for s in hub_strengths}
    disagreements = []
    for item in result["results"]:
        hub_rule = item.get("maps_to")
        if not hub_rule:
            continue
        if item["status"] == "failed" and hub_rule in strengths:
            disagreements.append({"pdfcraft_rule": item["rule"], "hub_rule": hub_rule, "pdfcraft": "failed", "hub": "verified"})
        elif item["status"] == "passed" and hub_rule in defects:
            disagreements.append({"pdfcraft_rule": item["rule"], "hub_rule": hub_rule, "pdfcraft": "passed", "hub": "needs attention"})
    return {"available": True, **result, "disagreements": disagreements}
