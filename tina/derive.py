"""Tina Phase 3: derive an editable HTML working copy from a PDF.

The converter does not mutate the source PDF and does not claim the derived
document is accessible. It extracts text and images deterministically into a
structured HTML draft whose improvements — headings, alt text, title,
language, text corrections — are made by a human in the draft's embedded,
offline editing toolbar. The exported clean HTML is a working document for
human review, not a conformance result.
"""
from __future__ import annotations

import base64
import html
import io
import re
from hashlib import sha256
from typing import Any

from pypdf import PdfReader

from tina.kernel import ToolGateway, ToolManifest

DERIVE_HTML_PERMISSION = "document.derive.html_draft"


class DerivationError(ValueError):
    """Raised when a PDF cannot be converted into an HTML working copy."""

CLAIM_BOUNDARY = (
    "This draft is a re-authoring workspace derived from a PDF. Extracted text, "
    "order, and images need human review; the exported HTML is a working "
    "document, not a conformance result."
)

DOC_STYLE = """
body{margin:0;font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#16232d;background:#fff}
main{max-width:760px;margin:0 auto;padding:32px 20px 80px}
section{margin-bottom:28px}
h1,h2,h3{line-height:1.25;color:#003764}
figure{margin:20px 0}
figure img{max-width:100%;height:auto;border:1px solid #dce4e9;border-radius:6px}
figcaption{font-size:14px;color:#61707a;margin-top:6px}
"""

DRAFT_STYLE = """
.draft-banner{background:#fff4dc;color:#946000;border-bottom:1px solid #ecd9a8;padding:14px 20px;font-size:14px}
.draft-banner b{display:block;margin-bottom:3px}
.draft-tools{position:sticky;top:0;background:#f6f8fa;border-bottom:1px solid #dce4e9;padding:12px 20px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;font-size:13px;z-index:5}
.draft-tools label{font-weight:620}
.draft-tools input{font:inherit;padding:5px 8px;border:1px solid #c7d2d9;border-radius:6px}
.draft-tools button{font:inherit;font-weight:620;padding:6px 11px;border-radius:6px;border:1px solid #c7d2d9;background:#fff;cursor:pointer}
.draft-tools button.primary{background:#003764;border-color:#003764;color:#fff}
.draft-tools .todo{margin-left:auto;color:#946000;font-weight:620}
.draft-tools .todo.done{color:#15735b}
[data-block]:focus{outline:3px solid #007eb8;outline-offset:2px}
.alt-editor{margin-top:8px;padding:10px;background:#f6f8fa;border:1px solid #dce4e9;border-radius:6px;font-size:13px;display:grid;gap:6px}
.alt-editor label{font-weight:620}
.alt-editor input[type=text]{font:inherit;padding:5px 8px;border:1px solid #c7d2d9;border-radius:6px;width:100%;box-sizing:border-box}
img[data-needs-alt]{outline:3px dashed #946000;outline-offset:3px}
button:focus-visible,input:focus-visible,[contenteditable]:focus-visible{outline:3px solid #007eb8;outline-offset:2px}
"""

DRAFT_SCRIPT = r"""
(function(){
"use strict";
const doc=document;
function el(tag,attrs,text){const node=doc.createElement(tag);for(const k in attrs||{})node.setAttribute(k,attrs[k]);if(text)node.textContent=text;return node}
const tools=el('div',{'data-draft-ui':'','class':'draft-tools',role:'group','aria-label':'Draft improvement tools'});
const titleLabel=el('label',{for:'draft-title'},'Title');const titleInput=el('input',{id:'draft-title',type:'text'});titleInput.value=doc.title==='Untitled draft'?'':doc.title;
titleInput.addEventListener('input',()=>{doc.title=titleInput.value.trim()||'Untitled draft';refresh()});
const langLabel=el('label',{for:'draft-lang'},'Language');const langInput=el('input',{id:'draft-lang',type:'text',size:'6',placeholder:'en-US'});langInput.value=doc.documentElement.lang||'';
langInput.addEventListener('input',()=>{doc.documentElement.lang=langInput.value.trim();refresh()});
const headingButton=el('button',{type:'button',title:'Cycle the selected block between paragraph, section heading, and subheading'},'Toggle heading');
let focused=null;
doc.addEventListener('focusin',event=>{const block=event.target.closest('[data-block]');if(block)focused=block});
headingButton.addEventListener('click',()=>{if(!focused)return;const order={P:'H2',H2:'H3',H3:'P'};const next=order[focused.tagName]||'P';const swap=doc.createElement(next);for(const attr of focused.attributes)swap.setAttribute(attr.name,attr.value);swap.innerHTML=focused.innerHTML;focused.replaceWith(swap);swap.focus();focused=swap});
const exportButton=el('button',{type:'button','class':'primary'},'Export clean HTML');
exportButton.addEventListener('click',()=>{const clone=doc.documentElement.cloneNode(true);clone.querySelectorAll('[data-draft-ui],script').forEach(n=>n.remove());clone.querySelectorAll('#draft-style').forEach(n=>n.remove());clone.querySelectorAll('*').forEach(n=>{n.removeAttribute('contenteditable');n.removeAttribute('data-block');n.removeAttribute('data-needs-alt')});const blob=new Blob(['<!doctype html>\n'+clone.outerHTML],{type:'text/html'});const a=doc.createElement('a');a.href=URL.createObjectURL(blob);a.download=(doc.title||'document')+'.html';a.click();URL.revokeObjectURL(a.href)});
const todo=el('span',{'class':'todo',role:'status'});
function refresh(){const images=doc.querySelectorAll('img[data-needs-alt]').length;const missing=[];if(!doc.title||doc.title==='Untitled draft')missing.push('title');if(!doc.documentElement.lang)missing.push('language');if(images)missing.push(images+' image decision'+(images===1?'':'s'));todo.textContent=missing.length?'Still needed: '+missing.join(', '):'All tracked improvements decided — review, then export.';todo.classList.toggle('done',!missing.length)}
tools.append(titleLabel,titleInput,langLabel,langInput,headingButton,exportButton,todo);
const banner=doc.querySelector('.draft-banner');if(banner)banner.after(tools);else doc.body.prepend(tools);
doc.querySelectorAll('[data-block]').forEach(block=>{block.setAttribute('contenteditable','true');block.setAttribute('tabindex','0')});
doc.querySelectorAll('figure').forEach((figure,index)=>{const img=figure.querySelector('img');if(!img)return;const editor=el('div',{'data-draft-ui':'','class':'alt-editor'});const inputId='alt-'+index;const label=el('label',{for:inputId},'Describe this image (why it is here, for someone who cannot see it)');const input=el('input',{id:inputId,type:'text'});input.value=img.getAttribute('alt')||'';const checkboxId='dec-'+index;const wrap=el('span');const checkbox=el('input',{id:checkboxId,type:'checkbox'});const checkLabel=el('label',{for:checkboxId},' Decorative only — no description needed');
function apply(){if(checkbox.checked){img.setAttribute('alt','');input.value='';input.disabled=true;img.removeAttribute('data-needs-alt')}else{input.disabled=false;img.setAttribute('alt',input.value.trim());if(input.value.trim())img.removeAttribute('data-needs-alt');else img.setAttribute('data-needs-alt','')}refresh()}
input.addEventListener('input',apply);checkbox.addEventListener('change',apply);wrap.append(checkbox,checkLabel);editor.append(label,input,wrap);figure.append(editor)});
refresh();
})();
"""


def _detect_image(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    return None


def _page_paragraphs(text: str) -> list[str]:
    blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
    if len(blocks) <= 1:
        blocks = [line.strip() for line in text.splitlines() if line.strip()]
    return [" ".join(block.split()) for block in blocks]


def extract_blocks(payload: bytes) -> list[str]:
    """The draft's text blocks, in the exact order the converter emits them —
    the shared index space for structure proposals."""
    try:
        reader = PdfReader(io.BytesIO(payload), strict=False)
    except Exception as error:
        raise DerivationError(f"The PDF could not be parsed: {type(error).__name__}") from error
    if reader.is_encrypted:
        raise DerivationError("Encrypted PDFs are not converted; request an unencrypted source copy.")
    blocks: list[str] = []
    for page in reader.pages:
        blocks.extend(_page_paragraphs(page.extract_text() or ""))
    return blocks


def _extract_html_draft(input_data: dict[str, Any]) -> dict[str, Any]:
    payload: bytes = input_data["payload"]
    # Optional human-confirmed / model-proposed roles per block index (h1|h2|h3|p|li).
    roles: dict[str, str] = {str(k): v for k, v in (input_data.get("roles") or {}).items()
                             if v in {"h1", "h2", "h3", "p", "li"}}
    try:
        reader = PdfReader(io.BytesIO(payload), strict=False)
    except Exception as error:
        raise DerivationError(f"The PDF could not be parsed for conversion: {type(error).__name__}") from error
    if reader.is_encrypted:
        raise DerivationError("Encrypted PDFs are not converted; request an unencrypted source copy.")

    info = reader.metadata or {}
    title = str(info.get("/Title")) if info.get("/Title") else ""
    root = reader.trailer.get("/Root", {})
    try:
        root = root.get_object()
    except AttributeError:
        pass
    language = str(root.get("/Lang")) if root.get("/Lang") else ""

    sections: list[str] = []
    stats = {"pages": len(reader.pages), "paragraphs": 0, "images_embedded": 0,
             "images_not_extracted": 0, "pages_without_text": 0, "roles_applied": 0}
    block_index = 0
    open_list = False
    for number, page in enumerate(reader.pages, start=1):
        parts: list[str] = [f'<section aria-label="Content extracted from page {number}">']
        paragraphs = _page_paragraphs(page.extract_text() or "")
        if not paragraphs:
            stats["pages_without_text"] += 1
        for paragraph in paragraphs:
            role = roles.get(str(block_index), "p")
            block_index += 1
            escaped = html.escape(paragraph)
            proposed = ' data-proposed="model"' if str(block_index - 1) in roles else ""
            if role == "li":
                if not open_list:
                    parts.append("<ul>")
                    open_list = True
                parts.append(f"<li data-block{proposed}>{escaped}</li>")
                stats["roles_applied"] += bool(proposed)
                continue
            if open_list:
                parts.append("</ul>")
                open_list = False
            tag = role if role in {"h1", "h2", "h3"} else "p"
            if proposed:
                stats["roles_applied"] += 1
            parts.append(f"<{tag} data-block{proposed}>{escaped}</{tag}>")
        if open_list:
            parts.append("</ul>")
            open_list = False
        stats["paragraphs"] += len(paragraphs)
        try:
            images = list(page.images)
        except Exception:
            images = []
        for image in images:
            mime = _detect_image(image.data or b"")
            if mime is None:
                stats["images_not_extracted"] += 1
                parts.append(
                    "<p data-block><em>An image on this page could not be extracted; "
                    "review it in the original document.</em></p>"
                )
                continue
            stats["images_embedded"] += 1
            encoded = base64.b64encode(image.data).decode("ascii")
            parts.append(f'<figure><img src="data:{mime};base64,{encoded}" alt="" data-needs-alt></figure>')
        parts.append("</section>")
        sections.append("\n".join(parts))

    draft = f"""<!doctype html>
<html lang="{html.escape(language)}">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title) or "Untitled draft"}</title>
<style id="doc-style">{DOC_STYLE}</style>
<style id="draft-style">{DRAFT_STYLE}</style>
</head>
<body>
<div class="draft-banner" data-draft-ui><b>Draft working copy — needs your review</b>{html.escape(CLAIM_BOUNDARY)}</div>
<main>
{chr(10).join(sections)}
</main>
<script>{DRAFT_SCRIPT}</script>
</body>
</html>
"""
    return {
        "html": draft,
        "stats": stats,
        "source_title": title or None,
        "source_language": language or None,
        "source_sha256": f"sha256:{sha256(payload).hexdigest()}",
    }


LINK_SCHEMES = ("http://", "https://", "mailto:")
_BARE_URL = re.compile(r"(?:https?://|mailto:)[^\s<>()\[\]{}\"']+[^\s<>()\[\]{}\"'.,;:!?]")


def _safe_href(value: Any) -> str | None:
    href = str(value or "").strip()
    return href if href.lower().startswith(LINK_SCHEMES) and len(href) <= 2000 else None


def _page_link_annotations(page: Any) -> list[dict[str, Any]]:
    """URI link annotations on a page, each with the words drawn under its rectangle.

    Text under a link is found geometrically: text runs whose start point
    falls inside the rectangle, trimmed word by word to the rectangle's width
    with an average glyph width estimate. When that is not trustworthy the
    caller falls back to the address itself.
    """
    annotations = []
    for raw in page.get("/Annots", []) or []:
        try:
            annotation = raw.get_object()
            if annotation.get("/Subtype") != "/Link":
                continue
            action = annotation.get("/A")
            action = action.get_object() if action is not None else {}
            href = _safe_href(action.get("/URI"))
            rect = [float(v) for v in annotation.get("/Rect")]
        except Exception:
            continue
        if not href:
            continue
        x0, y0, x1, y1 = min(rect[0], rect[2]), min(rect[1], rect[3]), max(rect[0], rect[2]), max(rect[1], rect[3])
        annotations.append({"href": href, "rect": (x0, y0, x1, y1), "words": []})
    if not annotations:
        return []

    def visit(text: str, cm: Any, tm: Any, font_dict: Any, font_size: Any) -> None:
        if not text or not text.strip():
            return
        try:
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            size = abs(float(font_size or 12) * (tm[0] or 1) * (cm[0] or 1)) or 12.0
        except Exception:
            return
        for link in annotations:
            lx0, ly0, lx1, ly1 = link["rect"]
            if lx0 - 2 <= x <= lx1 and ly0 - 3 <= y <= ly1 + 3:
                cursor = x
                for word in text.split():
                    width = 0.5 * size * len(word)
                    if cursor + width > lx1 + 0.5 * size:
                        break
                    link["words"].append(word)
                    cursor += width + 0.25 * size

    try:
        page.extract_text(visitor_text=visit)
    except Exception:
        pass
    return [{"href": link["href"], "text": " ".join(link["words"]).strip()} for link in annotations]


def _attach_links(blocks: list[dict[str, Any]], page_number: int, annotations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Inline each link into the paragraph that contains its text; return the leftovers."""
    leftovers = []
    page_paragraphs = [b for b in blocks if b.get("page") == page_number and b["kind"] == "paragraph"]
    for link in annotations:
        target = next((b for b in page_paragraphs if link["text"] and link["text"] in b["text"]), None)
        if target is None:
            leftovers.append(link)
            continue
        links = target.setdefault("links", [])
        if not any(existing["href"] == link["href"] and existing["text"] == link["text"] for existing in links):
            links.append({"text": link["text"], "href": link["href"], "source": "link_annotation"})
    return leftovers


def _reading_order(reader: Any, payload: bytes):
    """Yield (page_number, page, items) with items = [("text", str) | ("image", ImageFile)]
    in reading order. Uses poppler's layout (whole paragraphs, images placed by
    position) when available; otherwise plain extraction with images last."""
    from tina.layout import page_layout

    layout = page_layout(payload)
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            images = list(page.images)
        except Exception:
            images = []
        if layout is None:
            items = [("text", paragraph) for paragraph in _page_paragraphs(page.extract_text() or "")]
            items += [("image", image) for image in images]
        else:
            page_layout_info = layout[page_number - 1]
            placed = [(block["top"], 0, ("text", block["text"])) for block in page_layout_info["blocks"]]
            tops = page_layout_info["image_tops"]
            for order, image in enumerate(images):
                name = str(getattr(image, "name", "")).rsplit(".", 1)[0].lstrip("/")
                placed.append((tops.get(name, float("inf")), 1 + order, ("image", image)))
            items = [item for _, _, item in sorted(placed, key=lambda entry: (entry[0], entry[1]))]
        yield page_number, page, items


def docmodel_blocks(payload: bytes) -> list[str]:
    """The text blocks an accessible copy is built from, in the order
    ``build_docmodel`` numbers them: the index space for confirmed roles."""
    try:
        reader = PdfReader(io.BytesIO(payload), strict=False)
    except Exception as error:
        raise DerivationError(f"The PDF could not be parsed: {type(error).__name__}") from error
    if reader.is_encrypted:
        raise DerivationError("Encrypted PDFs are not converted; request an unencrypted source copy.")
    return [item for _, _, items in _reading_order(reader, payload) for kind, item in items if kind == "text"]


def build_docmodel(
    payload: bytes,
    roles: dict[str, str] | None = None,
    title: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """The structured document model (``tina/docmodel.py``) for a PDF.

    Uses the same block order as the HTML draft, so the human-confirmed
    ``roles`` index space (h1|h2|h3|p|li per block) is shared. Unconfirmed
    blocks stay paragraphs, and every figure starts undecided: the model
    records human structure and descriptions, it never infers them.
    """
    roles = {str(k): v for k, v in (roles or {}).items() if v in {"h1", "h2", "h3", "p", "li"}}
    try:
        reader = PdfReader(io.BytesIO(payload), strict=False)
    except Exception as error:
        raise DerivationError(f"The PDF could not be parsed: {type(error).__name__}") from error
    if reader.is_encrypted:
        raise DerivationError("Encrypted PDFs are not converted; request an unencrypted source copy.")
    info = reader.metadata or {}
    root = reader.trailer.get("/Root", {})
    try:
        root = root.get_object()
    except AttributeError:
        pass
    source_title = str(info.get("/Title") or "").strip()
    source_language = str(root.get("/Lang") or "").strip()

    blocks: list[dict[str, Any]] = []
    block_index = 0
    figure_number = 0
    for page_number, page, items in _reading_order(reader, payload):
        page_start = len(blocks)
        for kind, item in items:
            if kind == "text":
                role = roles.get(str(block_index), "p")
                block_index += 1
                if role == "li":
                    if blocks and blocks[-1]["kind"] == "list" and blocks[-1].get("page") == page_number:
                        blocks[-1]["items"].append(item)
                    else:
                        blocks.append({"kind": "list", "ordered": False, "items": [item], "page": page_number})
                elif role in {"h1", "h2", "h3"}:
                    blocks.append({"kind": "heading", "level": int(role[1]), "text": item, "page": page_number})
                else:
                    blocks.append({"kind": "paragraph", "text": item, "page": page_number})
                continue
            mime = _detect_image(item.data or b"")
            if mime is None:
                blocks.append({
                    "kind": "notice",
                    "text": f"An image on page {page_number} could not be carried into this copy; review it in the original document.",
                    "page": page_number,
                })
                continue
            figure_number += 1
            blocks.append({
                "kind": "figure", "figure": figure_number, "page": page_number, "mime": mime,
                "base64": base64.b64encode(item.data).decode("ascii"),
                "alt": None, "decorative": False, "caption": None,
            })
        # Addresses written out in the text become links to themselves.
        for block in blocks[page_start:]:
            if block["kind"] == "paragraph":
                for match in _BARE_URL.finditer(block["text"]):
                    block.setdefault("links", []).append({"text": match.group(0), "href": match.group(0), "source": "text"})
        linked = {link["href"] for block in blocks[page_start:] for link in block.get("links", [])}
        annotations = [link for link in _page_link_annotations(page) if link["href"] not in linked]
        for link in _attach_links(blocks[page_start:], page_number, annotations):
            blocks.append({
                "kind": "paragraph", "page": page_number,
                "text": f"Link on page {page_number}: {link['href']}",
                "links": [{"text": link["href"], "href": link["href"], "source": "link_annotation"}],
            })
    return {
        "version": "tina-docmodel/v1",
        "title": (title or "").strip() or source_title,
        "language": (language or "").strip() or source_language,
        "source_sha256": f"sha256:{sha256(payload).hexdigest()}",
        "blocks": blocks,
    }


def scanned_pages(payload: bytes) -> list[int]:
    """Pages with images but no extractable text: candidates for OCR before a rebuild."""
    try:
        reader = PdfReader(io.BytesIO(payload), strict=False)
    except Exception:
        return []
    if reader.is_encrypted:
        return []
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            has_text = bool((page.extract_text() or "").strip())
            has_image = bool(list(page.images))
        except Exception:
            continue
        if has_image and not has_text:
            pages.append(number)
    return pages


def extract_images(payload: bytes, limit: int = 20) -> list[dict[str, Any]]:
    """Extract embedded images (browser-safe base64) so a human can see what
    they are describing. Read-only; never persisted."""
    try:
        reader = PdfReader(io.BytesIO(payload), strict=False)
    except Exception as error:
        raise DerivationError(f"The PDF could not be parsed: {type(error).__name__}") from error
    if reader.is_encrypted:
        raise DerivationError("Encrypted PDFs are not inspected; request an unencrypted source copy.")
    results: list[dict[str, Any]] = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            images = list(page.images)
        except Exception:
            images = []
        for image in images:
            if len(results) >= limit:
                return results
            mime = _detect_image(image.data or b"")
            if mime is None:
                continue
            results.append({
                "index": len(results),
                "page": page_number,
                "mime": mime,
                "base64": base64.b64encode(image.data).decode("ascii"),
            })
    return results


class HtmlDraftConverter:
    """Deterministic PDF-to-editable-HTML derivation behind the tool gateway."""

    CONTRACT_VERSION = "tina-html-draft/v1"
    CLAIM_BOUNDARY = CLAIM_BOUNDARY

    def __init__(self, gateway: ToolGateway) -> None:
        self.gateway = gateway

    @classmethod
    def with_builtin_tools(cls) -> "HtmlDraftConverter":
        gateway = ToolGateway()
        gateway.register(
            ToolManifest(
                name="extract_html_draft",
                version="1.0.0",
                purpose="Derive an editable, structured HTML working copy from a PDF without mutating the source.",
                deterministic=True,
                mutates_document=False,
                permissions=(DERIVE_HTML_PERMISSION,),
                timeout_ms=60_000,
            ),
            _extract_html_draft,
        )
        return cls(gateway)

    def convert(self, filename: str, payload: bytes, roles: dict[str, str] | None = None) -> dict[str, Any]:
        execution = self.gateway.execute("extract_html_draft", {"payload": payload, "roles": roles}, {DERIVE_HTML_PERMISSION})
        return {
            "contract_version": self.CONTRACT_VERSION,
            "claim_boundary": self.CLAIM_BOUNDARY,
            "filename": filename,
            "tool": execution["tool"],
            "tool_version": execution["tool_version"],
            "deterministic": execution["deterministic"],
            "mutates_document": execution["mutates_document"],
            **execution["output"],
        }
