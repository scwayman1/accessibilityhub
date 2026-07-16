#!/usr/bin/env python3
"""Local-only deterministic PDF evidence checker for Coastline Spike 001.

This tool intentionally produces technical evidence and review queues, not a
conformance or legal determination. It never uploads, rewrites, or transmits
its input PDF.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from pypdf import PdfReader, __version__ as pypdf_version

VERAPDF_IMAGE = "verapdf/cli@sha256:d5ee329657cf9bc4b2400392dd54c7d0a0ce9980ff6fa2da5590eebeec007cdb"
VERAPDF_PROFILE = "ua1"
MAX_FILE_BYTES = 50 * 1024 * 1024


def run(command: list[str], timeout: int = 60) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired as error:
        return {
            "command": command,
            "returncode": None,
            "stdout": error.stdout or "",
            "stderr": f"timeout after {timeout}s",
        }


def command_version(command: list[str]) -> str | None:
    result = run(command, timeout=10)
    if result["returncode"] == 0:
        return (result["stdout"] or result["stderr"]).strip().splitlines()[0]
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finding(category: str, rule_id: str, severity: str, location: str, evidence: str, next_action: str) -> dict[str, str]:
    return {
        "category": category,
        "rule_id": rule_id,
        "severity": severity,
        "location": location,
        "evidence": evidence,
        "next_action": next_action,
    }


def indirect(value: Any) -> Any:
    try:
        return value.get_object()
    except AttributeError:
        return value


def count_page_objects(page: Any) -> tuple[int, int]:
    images = 0
    links = 0
    resources = indirect(page.get("/Resources", {})) or {}
    xobjects = indirect(resources.get("/XObject", {})) or {}
    for _, raw in xobjects.items():
        obj = indirect(raw)
        if obj and obj.get("/Subtype") == "/Image":
            images += 1
    for raw in page.get("/Annots", []) or []:
        annotation = indirect(raw)
        if annotation and annotation.get("/Subtype") == "/Link":
            links += 1
    return images, links


def run_verapdf(pdf: Path, output_dir: Path) -> dict[str, Any]:
    report = output_dir / "verapdf-ua1.json"
    image_check = run(["docker", "image", "inspect", VERAPDF_IMAGE], timeout=10)
    if image_check["returncode"] != 0:
        return {
            "image": VERAPDF_IMAGE,
            "profile": VERAPDF_PROFILE,
            "classification": "experimental_technical_findings_only",
            "returncode": None,
            "tool_available": False,
            "stderr": "Pinned veraPDF image is unavailable locally; the reviewer will not pull images during a check.",
            "report_path": None,
        }
    mounted_dir = str(pdf.parent.resolve())
    mounted_name = pdf.name
    result = run(
        [
            "docker", "run", "--rm", "--network", "none", "--platform", "linux/amd64",
            "-v", f"{mounted_dir}:/input:ro",
            VERAPDF_IMAGE,
            "--format", "json", "--flavour", VERAPDF_PROFILE, f"/input/{mounted_name}",
        ],
        timeout=120,
    )
    report.write_text(result["stdout"] or "")
    summary: dict[str, Any] = {
        "image": VERAPDF_IMAGE,
        "profile": VERAPDF_PROFILE,
        "classification": "experimental_technical_findings_only",
        "returncode": result["returncode"],
        "stderr": (result["stderr"] or "").strip()[:2000],
        "report_path": str(report),
    }
    try:
        payload = json.loads(result["stdout"])
        summary["report_top_level_keys"] = sorted(payload.keys()) if isinstance(payload, dict) else []
        report_text = json.dumps(payload)
        summary["report_bytes"] = len(report_text)
    except json.JSONDecodeError:
        summary["report_parse_error"] = "veraPDF did not emit parseable JSON"
    return summary


def analyze(pdf: Path, output_dir: Path) -> dict[str, Any]:
    if not pdf.exists() or not pdf.is_file():
        raise ValueError("Input must be an existing local file.")
    if pdf.suffix.lower() != ".pdf":
        raise ValueError("Only .pdf files are accepted in Spike 001.")
    if pdf.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"Input exceeds {MAX_FILE_BYTES // (1024 * 1024)} MB spike limit.")

    output_dir.mkdir(parents=True, exist_ok=True)
    findings: list[dict[str, str]] = []
    qpdf = run(["qpdf", "--check", str(pdf)], timeout=60)
    if qpdf["returncode"] != 0:
        findings.append(finding(
            "blocking_technical_failure", "PDF.INTAKE.QPDF_CHECK", "high", "document",
            (qpdf["stderr"] or qpdf["stdout"] or "qpdf could not validate the PDF structure").strip()[:1000],
            "Quarantine the file and request a new source artifact before further processing.",
        ))

    encryption_probe = run(["qpdf", "--show-encryption", str(pdf)], timeout=30)
    encryption_text = (encryption_probe["stdout"] or "") + "\n" + (encryption_probe["stderr"] or "")
    encrypted = "File is not encrypted" not in encryption_text and (
        "encryption method" in encryption_text.lower() or "r =" in encryption_text.lower()
    )
    if encrypted:
        findings.append(finding(
            "blocking_technical_failure", "PDF.INTAKE.ENCRYPTED", "high", "document",
            (encryption_probe["stdout"] or encryption_probe["stderr"] or "qpdf reported encrypted content").strip()[:1000],
            "Do not process this file in the spike; request an authorized unencrypted source copy.",
        ))

    try:
        reader = None if encrypted else PdfReader(str(pdf), strict=False)
    except Exception as error:  # pypdf exposes varying parser exceptions
        findings.append(finding(
            "blocking_technical_failure", "PDF.PARSE.PYPDF", "high", "document",
            f"pypdf could not open the PDF: {type(error).__name__}: {error}",
            "Route to a specialist or request a new source artifact.",
        ))
        reader = None

    metadata: dict[str, Any] = {}
    if reader is not None:
        root = indirect(reader.trailer.get("/Root", {})) or {}
        info = reader.metadata or {}
        metadata = {
            "page_count": len(reader.pages),
            "encrypted": bool(reader.is_encrypted),
            "title": str(info.get("/Title")) if info.get("/Title") else None,
            "language": str(root.get("/Lang")) if root.get("/Lang") else None,
            "marked": bool((indirect(root.get("/MarkInfo", {})) or {}).get("/Marked", False)),
            "has_structure_tree": bool(root.get("/StructTreeRoot")),
        }
        if reader.is_encrypted:
            findings.append(finding(
                "blocking_technical_failure", "PDF.INTAKE.ENCRYPTED", "high", "document catalog",
                "PDF is encrypted or password-protected.",
                "Do not process this file in the spike; request an authorized unencrypted source copy.",
            ))
        if not metadata["title"]:
            findings.append(finding(
                "deterministic_defect", "PDF.METADATA.TITLE", "medium", "document information dictionary",
                "No document title metadata was found.",
                "Set a meaningful title in the source application and regenerate the PDF.",
            ))
        if not metadata["language"]:
            findings.append(finding(
                "deterministic_defect", "PDF.METADATA.LANGUAGE", "medium", "document catalog /Lang",
                "No primary document language metadata was found.",
                "Set the primary language in the source application and regenerate the PDF.",
            ))
        if not metadata["marked"] or not metadata["has_structure_tree"]:
            findings.append(finding(
                "review_required", "PDF.STRUCTURE.SEMANTICS", "high", "document catalog",
                f"Marked={metadata['marked']}; structure_tree={metadata['has_structure_tree']}.",
                "Review the original source and PDF tag/reading-order behavior with an accessibility specialist.",
            ))

        images = links = pages_without_text = 0
        for index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                pages_without_text += 1
            image_count, link_count = count_page_objects(page)
            images += image_count
            links += link_count
        metadata.update({"image_objects": images, "link_annotations": links, "pages_without_extractable_text": pages_without_text})
        if pages_without_text:
            findings.append(finding(
                "review_required", "PDF.TEXT_LAYER", "high", "document pages",
                f"{pages_without_text} of {len(reader.pages)} pages had no extractable text using pypdf.",
                "Classify as scan/image-based or parser-limited; route for OCR assessment and human review.",
            ))
        if images:
            findings.append(finding(
                "review_required", "PDF.IMAGES.ALTERNATIVES", "medium", "page resources",
                f"Detected {images} image XObject(s). This count does not determine whether alternatives are meaningful.",
                "Review image purpose and text alternatives with a human reviewer.",
            ))
        if links:
            findings.append(finding(
                "review_required", "PDF.LINKS.PURPOSE", "low", "link annotations",
                f"Detected {links} link annotation(s). Link purpose requires contextual review.",
                "Review link text and destination purpose in context.",
            ))

    if qpdf["returncode"] == 0 and not encrypted and reader is not None:
        verapdf = run_verapdf(pdf, output_dir)
        findings.append(finding(
            "advisory", "PDF.VERAPDF.UA1", "info", "veraPDF report",
            "veraPDF UA-1 profile report was generated as experimental technical evidence only.",
            "Review the raw report alongside the Coastline rule pack; do not convert its outcome into a conformance claim.",
        ))
    else:
        verapdf = {
            "image": VERAPDF_IMAGE,
            "profile": VERAPDF_PROFILE,
            "classification": "not_run_due_to_blocking_intake",
            "report_path": None,
        }

    report = {
        "schema_version": "0.1",
        "spike": "001-pdf-deterministic-checker",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "input": {
            "path": str(pdf.resolve()),
            "sha256": sha256(pdf),
            "bytes": pdf.stat().st_size,
            "network_upload": False,
            "mutation_performed": False,
        },
        "tools": {
            "qpdf": command_version(["qpdf", "--version"]),
            "pypdf": pypdf_version,
            "docker": command_version(["docker", "--version"]),
            "verapdf_image": VERAPDF_IMAGE,
        },
        "metadata": metadata,
        "verapdf": verapdf,
        "findings": findings,
        "claim_boundary": "Technical evidence and review routing only. No conformance, legal, publish-readiness, or end-user usability determination is produced.",
    }
    return report


def markdown(report: dict[str, Any]) -> str:
    rows = [
        "# Coastline Accessibility Studio — Spike 001 report",
        "",
        "## Boundary",
        "",
        report["claim_boundary"],
        "",
        "## Input",
        "",
        f"- SHA-256: `{report['input']['sha256']}`",
        f"- Bytes: `{report['input']['bytes']}`",
        f"- Pages: `{report['metadata'].get('page_count', 'unavailable')}`",
        f"- Network upload: `{report['input']['network_upload']}`",
        f"- Mutation performed: `{report['input']['mutation_performed']}`",
        "",
        "## Tool evidence",
        "",
    ]
    for name, version in report["tools"].items():
        rows.append(f"- {name}: `{version or 'unavailable'}`")
    rows.extend(["", "## Findings", ""])
    for item in report["findings"]:
        rows.extend([
            f"### {item['rule_id']} — {item['category']}",
            f"- Severity: {item['severity']}",
            f"- Location: {item['location']}",
            f"- Evidence: {item['evidence']}",
            f"- Next action: {item['next_action']}",
            "",
        ])
    rows.extend([
        "## Raw validator artifact",
        "",
        f"- {report['verapdf']['report_path']}",
        "",
        "## Verdict",
        "",
        "Pending human review of the normalized findings and raw validator artifact.",
    ])
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="Path to a local PDF")
    parser.add_argument("--output-dir", type=Path, default=Path("out"), help="Directory for local evidence artifacts")
    args = parser.parse_args()
    try:
        report = analyze(args.pdf, args.output_dir)
    except ValueError as error:
        print(f"input_error: {error}", file=sys.stderr)
        return 2
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "report.json"
    md_path = args.output_dir / "report.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    md_path.write_text(markdown(report) + "\n")
    print(json.dumps({"report_json": str(json_path), "report_markdown": str(md_path), "findings": len(report["findings"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
