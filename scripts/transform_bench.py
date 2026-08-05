#!/usr/bin/env python3
"""Transformation test bench over the real review pipeline.

For every PDF in a corpus directory (or explicit file arguments) this runs the
exact code path the staging worker runs, in-process:

    assess (check_pdf.analyze → service.worker.normalize_report)
    → auto-improve title/language on a copy when those lanes are open,
      with full provenance (tina.remedy.MetadataRemediation — the same
      AUTO_FIX_RULES gate as service/worker.py)
    → re-assess the improved copy
    → seal (tina.seal.append_review_summary appends the one-page review record)

Outputs: a per-document console table, a self-contained white/coral HTML
report (bench-report.html) next to the produced .ready.pdf files, and an
optional machine-readable JSON stream (--json) for refinement loops.

Exit code 0 means every document either transformed, needed no changes, or
declined for an expected, honestly-stated reason (e.g. password-protected).
Any crash or unexplained outcome exits 1. Nothing here is an accessibility
determination: the bench reports technical evidence and review routing only.

    python3.11 scripts/make_test_corpus.py
    python3.11 scripts/transform_bench.py corpus --out bench-out
    python3.11 scripts/transform_bench.py corpus --fast --json
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from check_pdf import analyze  # noqa: E402  — the same checker the worker imports
from service.toolchain import status_lines, toolchain_versions, verapdf_unavailable_reason  # noqa: E402
from service.worker import (  # noqa: E402  — the worker's own gates and mapping
    AUTO_FIX_LANGUAGE,
    AUTO_FIX_RULES,
    LANE_ORDER,
    normalize_report,
    pipeline_title,
)
from tina.remedy import MetadataRemediation, RemediationError  # noqa: E402
from tina.seal import append_review_summary  # noqa: E402

TIMING_DOC = "long-50-pages.pdf"  # skipped by --fast

LANE_SHORT = {"needs_attention": "attn", "review_recommended": "review",
              "verified_signal": "verified", "not_assessed": "unchecked"}
LANE_LABELS = {"needs_attention": "Needs attention", "review_recommended": "Review recommended",
               "verified_signal": "Verified signals", "not_assessed": "Not assessed"}
STATUS_LABELS = {
    "transformed": "transformed",
    "nothing_to_improve": "no changes needed",
    "declined_expected": "declined (expected)",
    "error": "ERROR",
}
EXPECTED_STATUSES = {"transformed", "nothing_to_improve", "declined_expected"}


def _lane_counts(result: dict[str, Any]) -> dict[str, int]:
    counts = {lane: 0 for lane in LANE_ORDER}
    for signal in result.get("signals", []):
        counts[signal.get("lane") if signal.get("lane") in counts else "not_assessed"] += 1
    return counts


def _assess(payload: bytes, filename: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the real checker on a temp copy; return (raw report, normalized result)."""
    with tempfile.TemporaryDirectory(prefix="bench-assess-") as temp_dir:
        pdf = Path(temp_dir) / filename
        pdf.write_bytes(payload)
        report = analyze(pdf, Path(temp_dir) / "evidence")
    return report, normalize_report(report)


def _safe_output_name(filename: str) -> str:
    stem = filename[:-4] if filename.lower().endswith(".pdf") else filename
    return f"{stem}.ready.pdf"


def run_document(path: Path, out_dir: Path) -> dict[str, Any]:
    """One document through assess → improve → re-assess → seal. Never raises."""
    record: dict[str, Any] = {
        "name": path.name, "status": "error", "expected": False,
        "pages_before": None, "pages_after": None,
        "lanes_before": None, "lanes_after": None,
        "applied": [], "narration": [], "decline_reason": None,
        "output": None, "elapsed_ms": None,
    }
    started = time.perf_counter()
    try:
        payload = path.read_bytes()
        before_report, before = _assess(payload, path.name)
        record["lanes_before"] = _lane_counts(before)
        record["pages_before"] = before_report.get("metadata", {}).get("page_count")

        blocking = [f for f in before_report.get("findings", [])
                    if f.get("category") == "blocking_technical_failure"]
        if blocking:
            # The reviewer could not read the document at all. An honest,
            # plain-language decline is the correct outcome, not a crash.
            # Prefer the most specific blocking finding: "password-protected"
            # beats the generic structural-failure wording when both fire.
            blocking.sort(key=lambda f: f.get("rule_id") != "PDF.INTAKE.ENCRYPTED")
            reason = next((s.get("evidence") for s in before.get("signals", [])
                           if s.get("rule_id") == blocking[0].get("rule_id")), None)
            record.update({
                "status": "declined_expected", "expected": True,
                "decline_reason": reason or blocking[0].get("evidence"),
                "narration": ["The document was not changed; the review recorded why it could not be read."],
            })
            return record

        # The worker's exact auto-improve gate: metadata lanes only, ever.
        defects = {
            signal.get("rule_id")
            for signal in before.get("signals", [])
            if signal.get("lane") in {"needs_attention", "review_recommended"}
        } & AUTO_FIX_RULES
        improved = payload
        if defects:
            title = pipeline_title(path.name, "bench_corpus") if "PDF.METADATA.TITLE" in defects else None
            language = AUTO_FIX_LANGUAGE if "PDF.METADATA.LANGUAGE" in defects else None
            improved, provenance = MetadataRemediation.with_builtin_tools().apply(
                path.name, payload, title=title, language=language)
            for action in provenance.get("actions", []):
                value = action.get("value")
                label = {
                    "set_document_title": f'Set the document title to "{value}"',
                    "set_primary_language": f"Set the primary language to {value}",
                }.get(action.get("action"), action.get("detail") or action.get("action"))
                record["applied"].append(label)
                record["narration"].append(action.get("detail") or label)

        after_report, after = _assess(improved, path.name)
        record["lanes_after"] = _lane_counts(after)

        summary = {
            "lanes": record["lanes_after"],
            "applied_fixes": record["applied"],
            "verified": [s.get("title") or "" for s in after.get("signals", [])
                         if s.get("lane") == "verified_signal"],
        }
        sealed, seal_provenance = append_review_summary(
            path.name, improved, summary, dt.date.today().isoformat())
        record["pages_after"] = seal_provenance.get("result_pages")
        record["narration"].append(
            "Appended one Review summary page — a review record, not a certification.")

        out_path = out_dir / _safe_output_name(path.name)
        out_path.write_bytes(sealed)
        record["output"] = out_path.name
        record["status"] = "transformed" if defects else "nothing_to_improve"
        record["expected"] = True
        if not defects:
            record["narration"].insert(0, "No automatic metadata improvement was needed on this copy.")
        return record
    except RemediationError as error:
        # The engine declined with its own plain-language reason — honest, expected.
        record.update({"status": "declined_expected", "expected": True,
                       "decline_reason": str(error),
                       "narration": ["The pipeline declined and said why; the source file is untouched."]})
        return record
    except Exception as error:  # a crash is a bench failure, never hidden
        record.update({"status": "error", "expected": False,
                       "decline_reason": f"{type(error).__name__}: {error}"})
        return record
    finally:
        record["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)


def _lane_cell(counts: dict[str, int] | None) -> str:
    if counts is None:
        return "—"
    return " ".join(f"{LANE_SHORT[lane]}:{counts.get(lane, 0)}" for lane in LANE_ORDER)


def render_table(records: list[dict[str, Any]]) -> str:
    headers = ["Document", "Before (lanes)", "After (lanes)", "Applied", "Pages", "ms", "Outcome"]
    rows = []
    for r in records:
        pages = "—"
        if r["pages_before"] is not None:
            pages = f"{r['pages_before']}→{r['pages_after']}" if r["pages_after"] is not None else str(r["pages_before"])
        applied = "; ".join(r["applied"]) if r["applied"] else ("declined" if r["status"] == "declined_expected" else "none")
        rows.append([
            r["name"], _lane_cell(r["lanes_before"]), _lane_cell(r["lanes_after"]),
            applied[:44], pages, str(r["elapsed_ms"]), STATUS_LABELS.get(r["status"], r["status"]),
        ])
    widths = [max(len(h), *(len(row[i]) for row in rows)) if rows else len(h)
              for i, h in enumerate(headers)]
    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)),
             "  ".join("-" * w for w in widths)]
    lines += ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) for row in rows]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML report — self-contained, white ground with the product's coral accent.
# ---------------------------------------------------------------------------

def _chips(counts: dict[str, int] | None) -> str:
    if counts is None:
        return '<span class="chip mute">not read</span>'
    out = []
    for lane in LANE_ORDER:
        count = counts.get(lane, 0)
        out.append(f'<span class="chip {lane}{" zero" if not count else ""}">'
                   f'{html.escape(LANE_LABELS[lane])} {count}</span>')
    return "".join(out)


def render_html(records: list[dict[str, Any]], corpus_label: str, when: str) -> str:
    versions = toolchain_versions()
    tool_bits = []
    for name in ("qpdf", "tesseract"):
        version = versions[name]
        state = f'live — {html.escape(version)}' if version else "not detected; its checks are disclosed as not run"
        tool_bits.append(f'<span class="tool {"live" if version else "off"}"><strong>{name}</strong> {state}</span>')
    if versions["verapdf"]:
        tool_bits.append(f'<span class="tool live"><strong>veraPDF</strong> live — {html.escape(versions["verapdf"])}</span>')
    else:
        tool_bits.append('<span class="tool off"><strong>veraPDF</strong> unavailable — '
                         f'{html.escape(verapdf_unavailable_reason() or "")}</span>')

    rows = []
    for r in records:
        pages = ""
        if r["pages_before"] is not None and r["pages_after"] is not None:
            pages = f'{r["pages_before"]} pages → {r["pages_after"]} pages (review record appended)'
        elif r["pages_before"] is not None:
            pages = f'{r["pages_before"]} pages'
        narration = "".join(f"<li>{html.escape(item)}</li>" for item in r["narration"]) or \
            "<li>No changes were made to this document.</li>"
        reason = (f'<p class="reason">{html.escape(r["decline_reason"])}</p>'
                  if r["decline_reason"] else "")
        link = (f'<a class="ready" href="{html.escape(r["output"])}">{html.escape(r["output"])}</a>'
                if r["output"] else '<span class="mutetext">no output file</span>')
        status = STATUS_LABELS.get(r["status"], r["status"])
        rows.append(f"""
      <article class="doc {html.escape(r['status'])}">
        <header><h2>{html.escape(r['name'])}</h2>
          <span class="status s-{html.escape(r['status'])}">{html.escape(status)}</span>
          <span class="timing">{r['elapsed_ms']} ms</span></header>
        <div class="beforeafter">
          <div><h3>Before</h3>{_chips(r['lanes_before'])}</div>
          <div class="arrow" aria-hidden="true">→</div>
          <div><h3>After</h3>{_chips(r['lanes_after'])}</div>
        </div>
        <h3>What changed</h3>
        <ul class="narration">{narration}</ul>
        {reason}
        <p class="meta">{html.escape(pages)}</p>
        <p class="meta">Improved copy: {link}</p>
      </article>""")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Transformation bench report — Accessibility Hub</title>
<style>
  :root {{ --brand:#F0563F; --brand-press:#C93E2A; --ink:#232A33; --muted:#5B6470;
          --cream:#FBF8F4; --line:#ECE9E6; --good:#1E7A46; }}
  * {{ box-sizing:border-box }} body {{ margin:0; background:#fff; color:var(--ink);
      font:16px/1.55 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif }}
  .wrap {{ max-width:960px; margin:0 auto; padding:36px 24px 64px }}
  h1 {{ font-size:30px; margin:0 0 4px }} h2 {{ font-size:19px; margin:0 }}
  h3 {{ font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin:14px 0 6px }}
  .rule {{ height:4px; background:var(--brand); border-radius:2px; width:64px; margin:14px 0 18px }}
  .lead {{ color:var(--muted); margin:0 0 8px }}
  .claim {{ background:var(--cream); border:1px solid var(--line); border-left:4px solid var(--brand);
           border-radius:8px; padding:12px 16px; margin:16px 0; font-size:14.5px }}
  .tools {{ display:flex; flex-wrap:wrap; gap:10px; margin:18px 0 26px }}
  .tool {{ font-size:13.5px; border:1px solid var(--line); border-radius:999px; padding:6px 14px; background:#fff }}
  .tool.live {{ border-color:#BFDCCB; background:#F1F8F3 }}
  .tool.off {{ background:var(--cream); color:var(--muted) }}
  .doc {{ border:1px solid var(--line); border-radius:12px; padding:20px 22px; margin:0 0 18px; background:#fff }}
  .doc.declined_expected {{ background:var(--cream) }}
  .doc.error {{ border-color:var(--brand-press) }}
  .doc header {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap }}
  .status {{ font-size:12.5px; font-weight:700; text-transform:uppercase; letter-spacing:.05em;
            border-radius:999px; padding:4px 12px }}
  .s-transformed {{ background:var(--brand); color:#fff }}
  .s-nothing_to_improve {{ background:#F1F8F3; color:var(--good); border:1px solid #BFDCCB }}
  .s-declined_expected {{ background:#fff; color:var(--muted); border:1px solid var(--line) }}
  .s-error {{ background:var(--brand-press); color:#fff }}
  .timing {{ margin-left:auto; color:var(--muted); font-size:13.5px; font-variant-numeric:tabular-nums }}
  .beforeafter {{ display:flex; gap:18px; align-items:flex-start; flex-wrap:wrap }}
  .beforeafter > div {{ flex:1 1 240px }} .arrow {{ flex:0 0 auto; align-self:center; color:var(--brand); font-size:24px }}
  .chip {{ display:inline-block; font-size:12.5px; border-radius:999px; padding:3px 10px; margin:2px 4px 2px 0;
          border:1px solid var(--line); background:#fff }}
  .chip.needs_attention {{ border-color:var(--brand); color:var(--brand-press) }}
  .chip.verified_signal {{ border-color:#BFDCCB; color:var(--good); background:#F1F8F3 }}
  .chip.zero {{ opacity:.45 }} .chip.mute {{ color:var(--muted) }}
  .narration {{ margin:4px 0 0; padding-left:20px; font-size:14.5px }}
  .reason {{ font-size:14.5px; color:var(--muted); border-left:3px solid var(--line); padding-left:12px }}
  .meta {{ font-size:13.5px; color:var(--muted); margin:8px 0 0 }}
  .ready {{ color:var(--brand-press); font-weight:600 }}
  .mutetext {{ color:var(--muted) }}
  footer {{ margin-top:28px; color:var(--muted); font-size:13.5px }}
</style></head><body><div class="wrap">
  <h1>Transformation bench report</h1>
  <div class="rule"></div>
  <p class="lead">Corpus: {html.escape(corpus_label)} · run {html.escape(when)} · the same
  assess → improve-a-copy → re-assess → seal pipeline the staging worker runs.</p>
  <p class="claim">Signals are shown separately. They are not an overall accessibility
  result, and the sealed page each copy gains is a review record, not a certification.</p>
  <div class="tools">{''.join(tool_bits)}</div>
  {''.join(rows)}
  <footer>Every improvement was applied to a copy with full provenance; source files
  were never modified. Technical evidence and review routing only.</footer>
</div></body></html>
"""


def collect_inputs(paths: list[Path], fast: bool) -> list[Path]:
    inputs: list[Path] = []
    for path in paths:
        if path.is_dir():
            inputs.extend(sorted(p for p in path.iterdir() if p.suffix.lower() == ".pdf"))
        elif path.is_file():
            inputs.append(path)
        else:
            raise SystemExit(f"input not found: {path}")
    if fast:
        inputs = [p for p in inputs if p.name != TIMING_DOC]
    if not inputs:
        raise SystemExit("no PDF inputs found — run scripts/make_test_corpus.py first")
    return inputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the real assess→improve→re-assess→seal pipeline over a corpus.")
    parser.add_argument("inputs", nargs="+", type=Path,
                        help="Corpus directory (or explicit PDF files)")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "bench-out",
                        help="Output directory for .ready.pdf files and bench-report.html")
    parser.add_argument("--fast", action="store_true", help=f"Skip the timing document ({TIMING_DOC})")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="Emit machine-readable JSON on stdout instead of the table")
    args = parser.parse_args(argv)

    inputs = collect_inputs(args.inputs, args.fast)
    args.out.mkdir(parents=True, exist_ok=True)

    records = [run_document(path, args.out) for path in inputs]
    ok = all(r["status"] in EXPECTED_STATUSES for r in records)
    when = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    corpus_label = ", ".join(str(p) for p in args.inputs)

    report_path = args.out / "bench-report.html"
    report_path.write_text(render_html(records, corpus_label, when), encoding="utf-8")

    payload = {
        "ok": ok,
        "generated_at": when,
        "toolchain": {**toolchain_versions(),
                      "verapdf_unavailable_reason": verapdf_unavailable_reason()},
        "report_html": str(report_path),
        "documents": records,
        "claim": ("Technical evidence and review routing only; no accessibility "
                  "determination is produced."),
    }
    if args.as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("\n".join(status_lines()))
        if not shutil.which("qpdf"):
            print("  note: without qpdf, structural-integrity evidence is disclosed as not run")
        print()
        print(render_table(records))
        print()
        print(f"HTML report: {report_path}")
        print("Expected outcomes: transformed, no changes needed, or an honestly stated decline.")
        print(f"Result: {'all documents behaved as expected' if ok else 'UNEXPECTED OUTCOMES PRESENT'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
