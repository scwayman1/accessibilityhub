"""Produce the Hub's output files: accessible HTML and a tagged PDF.

The produced files are re-authored from the structured document model
(``tina/docmodel.py``) rather than patched into the source PDF:

* ``render_html`` writes one semantic, self-contained HTML5 file — ``lang``,
  ``<title>``, one ``<main>``, human-confirmed headings and lists, tables with
  ``<th scope>``, figures with their human-authored descriptions.
* ``render_pdf`` lays that same structure out with WeasyPrint's PDF/UA-1
  variant: a structure tree, ``/MarkInfo``, ``/Lang``, ``DisplayDocTitle``, and
  embedded fonts. Decorative figures are drawn as artifacts, not tagged
  figures.
* ``AccessiblePackageProducer`` runs both behind the tool gateway and then
  re-checks its own PDF with the same checker it applies to everyone else's
  documents. Whatever that check finds is returned, never hidden.

Document tooling makes no network requests: the PDF renderer may only read
``data:`` URIs embedded in the document itself. Nothing here authors alt
text, infers structure, or claims conformance.
"""
from __future__ import annotations

import html
import io
import tempfile
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

from tina.docmodel import DocModelError, pending_decisions, require_valid
from tina.kernel import ToolGateway, ToolManifest

PRODUCE_PERMISSION = "document.produce.accessible_package"
PRODUCER_NAME = "Coastline College Accessibility Hub"
RECORD_LINE = "A review record, not a certification."
CLAIM_BOUNDARY = (
    "This copy was re-authored from the original with structure and image "
    "descriptions confirmed by a person, then rechecked. The recheck is "
    "technical evidence for review, not a conformance result."
)
EVIDENCE_HASH_CHARS = 12

DOCUMENT_STYLE = """
@page{size:Letter;margin:0.9in 0.85in}
html{font-family:"DejaVu Sans","Noto Sans",Arial,sans-serif;font-size:11.5pt;line-height:1.55;color:#1c2730;background:#fff}
body{margin:0}
main{max-width:46em;margin:0 auto;padding:2em 1.25em}
h1,h2,h3,h4,h5,h6{line-height:1.25;color:#10324f;margin:1.3em 0 .45em;break-after:avoid}
h1{font-size:1.9em;margin-top:0}h2{font-size:1.45em}h3{font-size:1.2em}
p,ul,ol{margin:0 0 .85em}
li{margin:.2em 0}
figure{margin:1.2em 0;break-inside:avoid}
figure img,.decorative-image{max-width:100%;height:auto}
.decorative-image{display:block;width:100%;height:2.4in;background-position:center;background-repeat:no-repeat;background-size:contain}
figcaption{font-size:.9em;color:#4c5a64;margin-top:.35em}
table{border-collapse:collapse;width:100%;margin:1em 0;break-inside:auto}
caption{text-align:left;font-weight:bold;margin-bottom:.4em}
th,td{border:1px solid #b9c4cb;padding:.35em .55em;text-align:left;vertical-align:top}
th{background:#eef2f5}
.notice{border-left:4px solid #b26b00;background:#fff7e8;padding:.6em .8em}
.review-record{margin-top:2.5em;padding-top:1em;border-top:1px solid #c9d2d8;font-size:.92em;color:#33424d}
.review-record h2{font-size:1.15em}
a{color:#0b5c99}
"""


def _esc(value: Any) -> str:
    return html.escape(" ".join(str(value or "").split()))


def _figure_html(block: dict[str, Any], target: str) -> str:
    source = f"data:{block['mime']};base64,{block['base64']}"
    caption = f"<figcaption>{_esc(block['caption'])}</figcaption>" if block.get("caption") else ""
    if block.get("decorative"):
        if target == "pdf":
            # WeasyPrint tags <img alt=""> as a /Figure with no /Alt; a CSS
            # background is emitted as an /Artifact, which is what decorative is.
            return f'<div class="decorative-image" aria-hidden="true" style="background-image:url({source})"></div>'
        return f'<img class="decorative" src="{source}" alt="">'
    return f'<figure><img src="{source}" alt="{_esc(block["alt"])}">{caption}</figure>'


def _table_html(block: dict[str, Any]) -> str:
    header_rows = block["header_rows"]
    rows = block["rows"]
    parts = ["<table>"]
    if block.get("caption"):
        parts.append(f"<caption>{_esc(block['caption'])}</caption>")
    parts.append("<thead>")
    for row in rows[:header_rows]:
        parts.append("<tr>" + "".join(f'<th scope="col">{_esc(cell)}</th>' for cell in row) + "</tr>")
    parts.append("</thead><tbody>")
    for row in rows[header_rows:]:
        parts.append("<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in row) + "</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def _review_record_html(model: dict[str, Any], summary: dict[str, Any] | None) -> str:
    summary = summary or {}
    rows = [f"<p><strong>{_esc(PRODUCER_NAME)}</strong> · {_esc(summary.get('review_date') or date.today().isoformat())}</p>"]
    source_hash = str(model.get("source_sha256") or "").removeprefix("sha256:")
    if source_hash:
        rows.append(f"<p>Original document evidence hash: <code>{_esc(source_hash[:EVIDENCE_HASH_CHARS])}</code></p>")
    improvements = [str(item) for item in summary.get("improvements") or [] if str(item).strip()]
    if improvements:
        rows.append("<p>What changed in this copy:</p><ul>" + "".join(f"<li>{_esc(item)}</li>" for item in improvements) + "</ul>")
    rows.append(f"<p>{_esc(CLAIM_BOUNDARY)} {_esc(RECORD_LINE)}</p>")
    return '<section class="review-record" aria-labelledby="review-record-heading"><h2 id="review-record-heading">About this copy</h2>' + "".join(rows) + "</section>"


def render_html(model: dict[str, Any], summary: dict[str, Any] | None = None, target: str = "html") -> str:
    """Semantic, self-contained HTML for a valid document model."""
    require_valid(model)
    body: list[str] = []
    blocks = model["blocks"]
    if not (blocks[0]["kind"] == "heading" and blocks[0]["level"] == 1):
        body.append(f"<h1>{_esc(model['title'])}</h1>")
    for block in blocks:
        kind = block["kind"]
        if kind == "heading":
            body.append(f"<h{block['level']}>{_esc(block['text'])}</h{block['level']}>")
        elif kind == "paragraph":
            body.append(f"<p>{_esc(block['text'])}</p>")
        elif kind == "notice":
            body.append(f'<p class="notice">{_esc(block["text"])}</p>')
        elif kind == "list":
            tag = "ol" if block.get("ordered") else "ul"
            body.append(f"<{tag}>" + "".join(f"<li>{_esc(item)}</li>" for item in block["items"]) + f"</{tag}>")
        elif kind == "table":
            body.append(_table_html(block))
        elif kind == "figure":
            body.append(_figure_html(block, target))
    body.append(_review_record_html(model, summary))
    return (
        "<!doctype html>\n"
        f'<html lang="{_esc(model["language"])}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{_esc(model['title'])}</title>\n"
        f'<meta name="generator" content="{_esc(PRODUCER_NAME)}">\n'
        f"<style>{DOCUMENT_STYLE}</style>\n</head>\n<body>\n<main>\n"
        + "\n".join(body)
        + "\n</main>\n</body>\n</html>\n"
    )


def render_pdf(model: dict[str, Any], summary: dict[str, Any] | None = None) -> bytes:
    """A tagged PDF/UA-1 file for a valid document model (WeasyPrint)."""
    try:
        import weasyprint
        from weasyprint.urls import FatalURLFetchingError, URLFetcher
    except ImportError as error:  # pragma: no cover - exercised only without the dependency
        raise RuntimeError("WeasyPrint is not installed; the tagged PDF cannot be produced.") from error
    markup = render_html(model, summary, target="pdf")
    # Offline by construction: only the document's own data: URIs resolve.
    fetcher = URLFetcher(allowed_protocols={"data"}, fail_on_errors=True)
    try:
        document = weasyprint.HTML(string=markup, url_fetcher=fetcher)
        pdf_bytes = document.write_pdf(
            pdf_variant="pdf/ua-1",
            custom_metadata=True,
            pdf_identifier=sha256(markup.encode("utf-8")).hexdigest()[:32].encode("ascii"),
        )
    except FatalURLFetchingError as error:
        # A BaseException in WeasyPrint: convert it so no caller's
        # ``except Exception`` boundary is bypassed.
        raise RuntimeError("The document referenced a resource outside the document; nothing was fetched.") from error
    captions = [str(block.get("caption") or "").strip() for block in model["blocks"] if block["kind"] == "table"]
    return _attach_table_summaries(pdf_bytes, captions) if any(captions) else pdf_bytes


def _attach_table_summaries(pdf_bytes: bytes, captions: list[str]) -> bytes:
    """Give each tagged Table a /Summary attribute from its human-written caption.

    Acrobat-style checkers expect a table summary; WeasyPrint tags <caption>
    but writes no /Summary. Tables are matched in document order, and a table
    without a caption is left as is so a checker can still flag it.
    """
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, TextStringObject

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes)))
    tables: list[Any] = []

    def walk(node: Any) -> None:
        node = node.get_object() if hasattr(node, "get_object") else node
        if isinstance(node, dict) and node.get("/S") is not None:
            if node.get("/S") == "/Table":
                tables.append(node)
            kids = node.get("/K")
            for kid in kids if isinstance(kids, list) else ([kids] if kids is not None else []):
                walk(kid)

    tree = writer._root_object["/StructTreeRoot"].get_object()
    kids = tree.get("/K")
    for kid in kids if isinstance(kids, list) else ([kids] if kids is not None else []):
        walk(kid)
    if len(tables) != len(captions):
        return pdf_bytes  # Never guess which caption belongs to which table.
    for table, caption in zip(tables, captions):
        if caption:
            table[NameObject("/A")] = DictionaryObject({
                NameObject("/O"): NameObject("/Table"),
                NameObject("/Summary"): TextStringObject(caption),
            })
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def self_check(pdf_bytes: bytes) -> dict[str, Any]:
    """Run the Hub's own checker on a produced PDF and return lane counts."""
    import check_pdf
    from service.worker import normalize_report

    with tempfile.TemporaryDirectory(prefix="hub-produced-") as workdir:
        path = Path(workdir) / "produced.pdf"
        path.write_bytes(pdf_bytes)
        report = check_pdf.analyze(path, Path(workdir) / "report")
    normalized = normalize_report(report)
    lanes: dict[str, int] = {}
    attention: list[dict[str, str]] = []
    for signal in normalized["signals"]:
        lanes[signal["lane"]] = lanes.get(signal["lane"], 0) + 1
        if signal["lane"] == "needs_attention":
            attention.append({"rule_id": signal["rule_id"], "title": signal["title"], "evidence": signal["evidence"]})
    return {
        "checker": "check_pdf",
        "lanes": lanes,
        "needs_attention": attention,
        "completeness": normalized.get("completeness"),
        "second_opinion": report.get("second_opinion"),
    }


def _produce_accessible_package(input_data: dict[str, Any]) -> dict[str, Any]:
    model = input_data["model"]
    summary = input_data.get("summary")
    pending = pending_decisions(model)
    if pending:
        raise DocModelError([
            f"Figure {item['figure']}{f' on page ' + str(item['page']) if item.get('page') else ''} needs a description or a decorative decision."
            for item in pending
        ])
    html_text = render_html(model, summary)
    pdf_bytes = render_pdf(model, summary)
    result: dict[str, Any] = {
        "html": html_text,
        "pdf": pdf_bytes,
        "html_sha256": f"sha256:{sha256(html_text.encode('utf-8')).hexdigest()}",
        "pdf_sha256": f"sha256:{sha256(pdf_bytes).hexdigest()}",
        "source_sha256": model.get("source_sha256"),
        "figures": sum(1 for block in model["blocks"] if block["kind"] == "figure"),
        "headings": sum(1 for block in model["blocks"] if block["kind"] == "heading"),
    }
    if input_data.get("verify", True):
        result["self_check"] = self_check(pdf_bytes)
    return result


class AccessiblePackageProducer:
    """Deterministic document-model → accessible HTML + tagged PDF, behind the gateway."""

    CONTRACT_VERSION = "tina-accessible-package/v1"
    CLAIM_BOUNDARY = CLAIM_BOUNDARY

    def __init__(self, gateway: ToolGateway) -> None:
        self.gateway = gateway

    @classmethod
    def with_builtin_tools(cls) -> "AccessiblePackageProducer":
        gateway = ToolGateway()
        gateway.register(
            ToolManifest(
                name="produce_accessible_package",
                version="1.0.0",
                purpose="Re-author a human-confirmed document model as accessible HTML and a tagged PDF/UA-1 file, then recheck the PDF.",
                deterministic=True,
                # Produces new files; the source document is never written.
                mutates_document=False,
                permissions=(PRODUCE_PERMISSION,),
                timeout_ms=120_000,
            ),
            _produce_accessible_package,
        )
        return cls(gateway)

    def produce(self, model: dict[str, Any], summary: dict[str, Any] | None = None, verify: bool = True) -> dict[str, Any]:
        execution = self.gateway.execute(
            "produce_accessible_package",
            {"model": model, "summary": summary, "verify": verify},
            {PRODUCE_PERMISSION},
        )
        return {
            "contract_version": self.CONTRACT_VERSION,
            "claim_boundary": self.CLAIM_BOUNDARY,
            "tool": execution["tool"],
            "tool_version": execution["tool_version"],
            "deterministic": execution["deterministic"],
            "mutates_document": execution["mutates_document"],
            **execution["output"],
        }
