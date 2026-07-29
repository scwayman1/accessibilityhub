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
