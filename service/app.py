"""WSGI control plane for the private, synthetic-only Accessibility Hub staging slice."""
from __future__ import annotations

import base64
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime
from hashlib import sha256
from html import escape
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

from tina.remedy import MetadataRemediation, RemediationError
from tina.ocr import OcrRemediation
from tina.structure import StructureRemediation
from tina.derive import extract_blocks

from service.fixtures import synthetic_handout_pdf, synthetic_scan_pdf
from service.repository import StagingRepository, now as repo_now
from service.settings import ServiceSettings
from service.worker import AssessmentWorker, LANE_ORDER

TENANT_ID = "coastline-staging"
ACTOR_ID = "staging-educator"
WORKFLOW_STEPS = (("add", "1", "Review"), ("review", "2", "Understand"), ("improve", "3", "Improve"), ("check", "4", "Verify"))
LANE_PRESENTATION = {
    "needs_attention": ("!", "Needs attention"),
    "review_recommended": ("?", "Review recommended"),
    "verified_signal": ("✓", "Verified signal"),
    "not_assessed": ("–", "Not assessed"),
}
STATE_LABELS = {"queued": "Review queued", "running": "Review in progress", "succeeded": "Review complete", "failed": "Review did not complete"}
SOURCE_LABELS = {"bundled_synthetic_fixture": "Supplied sample", "synthetic_remediated_copy": "Improved copy", "educator_upload": "Your upload"}
REMEDIATION_LABELS = {"metadata": "Title & language", "structure": "Tag structure", "ocr": "Text layer (OCR)", "seal": "Review summary page"}
SUMMARY_PHRASES = {"needs_attention": ("needs attention", "need attention"), "review_recommended": ("to review", "to review"), "verified_signal": ("verified", "verified"), "not_assessed": ("not assessed", "not assessed")}
SSO_ACTOR = "jordan-rivera"
SSO_DISPLAY = "Jordan Rivera, Faculty"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
UPLOAD_READ_CAP = MAX_UPLOAD_BYTES + 2 * 1024 * 1024  # payload plus multipart framing
PARTNER_ADS_PATH = Path(__file__).resolve().parents[1] / "partner_ads.json"
STRUCTURE_ROLES = (("h1", "Heading level 1"), ("h2", "Heading level 2"), ("h3", "Heading level 3"), ("p", "Paragraph"), ("li", "List item"))
MAX_FORM_BLOCKS = 80

_VERSION_PATTERN = re.compile(r"^(?P<base>.+)\.v(?P<version>\d+)$")

_FALLBACK_FAVICON = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    b'<rect width="64" height="64" rx="14" fill="#F0563F"/>'
    b'<path d="M17 34 L28 45 L47 21" fill="none" stroke="#FFFFFF" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)


def _split_version(filename: str) -> tuple[str, int]:
    """('base', N) for base.vN.pdf; legacy '.rechecked' chains collapse to the base."""
    stem = filename[:-4] if filename.lower().endswith(".pdf") else filename
    while stem.endswith(".rechecked"):
        stem = stem[: -len(".rechecked")]
    match = _VERSION_PATTERN.match(stem)
    if match:
        return match.group("base"), int(match.group("version"))
    return stem, 1


def _next_version_name(filename: str) -> str:
    base, version = _split_version(filename)
    return f"{base}.v{version + 1}.pdf"


def _when(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%b %-d, %H:%M")
    except ValueError:
        return iso[:19]


def _load_partner_ads() -> dict[str, Any] | None:
    """Load partner_ads.json; any problem means no ad, never a broken review page."""
    try:
        data = json.loads(PARTNER_ADS_PATH.read_text(encoding="utf-8"))
        partners = [p for p in data.get("partners", []) if isinstance(p, dict) and p.get("name") and p.get("message")]
        if not partners:
            return None
        return {
            "disclosure": str(data.get("disclosure") or ""),
            "rotation_seconds": max(int(data.get("rotation_seconds") or 10), 1),
            "partners": partners,
        }
    except Exception:
        return None


def _sponsored_card() -> str:
    """Server-rendered, first-party Sponsored card shown only while a job runs.

    Rotation is a pure time bucket — no scripts, no pixels, no tracking — and
    the card never gates anything: the moment a job is terminal the results
    page renders without it.
    """
    ads = _load_partner_ads()
    if not ads:
        return ""
    partner = ads["partners"][int(time.time() // ads["rotation_seconds"]) % len(ads["partners"])]
    tagline = f"<p class=sponsor-tagline>{escape(str(partner.get('tagline') or ''))}</p>" if partner.get("tagline") else ""
    cta = f"<span class=sponsor-cta>{escape(str(partner.get('cta_label') or ''))}</span>" if partner.get("cta_label") else ""
    return (
        '<aside class="panel sponsor-card" aria-label="Sponsored message">'
        f'<div class=sponsor-top><span class=sponsor-label>Sponsored</span><span class=sponsor-disclosure>{escape(ads["disclosure"])}</span></div>'
        f'<h3>{escape(str(partner["name"]))}</h3>{tagline}<p class=sponsor-message>{escape(str(partner["message"]))}</p>{cta}'
        '<div class=sponsor-progress aria-hidden=true></div>'
        '<p class=sponsor-note>Sponsor messages never delay your results.</p></aside>'
    )


def _seal_available() -> bool:
    """Lazy check for tina.seal; a missing seal module never breaks review flow."""
    try:
        from tina.seal import append_review_summary  # noqa: F401
        return True
    except Exception:
        return False


def _lane_counts(result: dict[str, Any] | None) -> dict[str, int]:
    counts = {lane: 0 for lane in LANE_ORDER}
    for signal in (result or {}).get("signals", []):
        counts[signal.get("lane") if signal.get("lane") in counts else "not_assessed"] += 1
    return counts


def _summary_chips(counts: dict[str, int]) -> str:
    chips = []
    for lane in LANE_ORDER:
        count = counts.get(lane, 0)
        singular, plural = SUMMARY_PHRASES[lane]
        phrase = singular if count == 1 else plural
        chips.append(f'<span class="summary-item {lane}"><span class=chip>{count} {phrase}</span></span>')
    return f'<div class=summary-chips aria-label="Review at a glance">{"".join(chips)}</div>'


def _suggested_title(filename: str, source_kind: str) -> str:
    if source_kind == "bundled_synthetic_fixture":
        return "Week 3 Course Handout"
    base = _split_version(filename)[0]
    words = re.sub(r"[-_]+", " ", base).strip()
    return (words[:1].upper() + words[1:]) if words else "Course Handout"


def _safe_upload_name(raw: str) -> str:
    name = Path(raw.replace("\\", "/")).name
    stem = name[:-4] if name.lower().endswith(".pdf") else name
    stem = re.sub(r"[^A-Za-z0-9._ ()-]+", "-", stem).strip(" .-") or "course-material"
    return f"{stem[:96]}.pdf"


def _multipart_file(environ: dict[str, Any], field: str) -> tuple[str, bytes] | None:
    """Minimal, capped multipart/form-data reader for the dev-only upload route."""
    content_type = environ.get("CONTENT_TYPE", "")
    match = re.search(r'boundary="?([^";,]+)"?', content_type)
    if "multipart/form-data" not in content_type or not match:
        return None
    try:
        declared = int(environ.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        declared = 0
    if declared <= 0:
        return None
    body = environ["wsgi.input"].read(min(declared, UPLOAD_READ_CAP))
    for part in body.split(b"--" + match.group(1).encode("utf-8", "replace")):
        head, separator, data = part.partition(b"\r\n\r\n")
        if not separator:
            continue
        headers = head.decode("utf-8", "replace")
        name = re.search(r'name="([^"]*)"', headers)
        filename = re.search(r'filename="([^"]*)"', headers)
        if name and name.group(1) == field and filename:
            return filename.group(1), data.removesuffix(b"\r\n")
    return None


def _workflow_rail(current: str) -> str:
    current_index = next((index for index, (key, _, _) in enumerate(WORKFLOW_STEPS) if key == current), 0)
    items = []
    for index, (key, number, label) in enumerate(WORKFLOW_STEPS):
        state = "current" if key == current else ("complete" if index < current_index else "upcoming")
        marker = "✓" if state == "complete" else number
        aria = ' aria-current="step"' if state == "current" else ""
        items.append(f'<li class="{state}"{aria}><span class=step-number aria-hidden=true>{marker}</span><span>{label}</span></li>')
    return f'<nav class=workflow-rail aria-label="Review workflow"><p class=nav-label>Review workflow</p><ol>{"".join(items)}</ol></nav>'


def _app_shell(current: str, content: str, signed_in: bool = False, dev: bool = False, persona: str = "") -> str:
    signout = '<form class=signout method=post action="/logout"><button>Sign out</button></form>' if signed_in else ""
    persona_block = f'<div class=persona><span class=persona-mark aria-hidden=true>{escape(persona[:1])}</span><div><strong>{escape(persona)}</strong><p>Signed in</p></div></div>' if persona else ""
    if dev:
        note = "<strong>Development workspace</strong><p>Uploads stay on this machine and are reviewed locally.</p>"
    else:
        note = "<strong>Synthetic demo only</strong><p>Real-document upload is unavailable.</p>"
    return f'''<a class=skip-link href="#main-content">Skip to main content</a><div class=app-shell>
    <aside class=sidebar><a class=brand href="/app"><img src="/assets/coastline-college-logo-white.png" alt="Coastline College"></a>
    <div class=product-lockup><span>Accessibility Hub</span><strong>Staging workspace</strong></div>
    {_workflow_rail(current)}
    {persona_block}
    {signout}
    <div class=sidebar-note><span class=status-dot aria-hidden=true></span><div>{note}</div></div></aside>
    <main id=main-content class=main-workspace tabindex="-1">{content}</main></div>'''


def _html_page(title: str, body: str, head: str = "") -> bytes:
    css = """
    :root { /* Brand tokens — swap hexes here to retune the brand */ --brand:#F0563F; --brand-deep:#CF3A24; --brand-press:#B0301C; --navy:#FFFFFF; --sky:#ECE9E6; --ink:#232A33; --ink-soft:#3A434E; --muted:#5C6670; --canvas:#FFFFFF; --wash:#FAFAF8; --surface:#fff; --line:#ECE9E6; --line-strong:#D9D4CF; --cream:#FFF6EE; --blush:#FFE3D6; --blush-line:#F3CDBB; --sun:#FFC94D; --teal:#0E7C66; --attention:#A83224; --attention-soft:#FBE2DC; --review:#0C6172; --review-soft:#DDF0F2; --success:#1D6E4C; --success-soft:#DFF2E6; --success-line:#B7DFC6; --neutral:#565E68; --neutral-soft:#ECEDEF; --display:ui-rounded,"SF Pro Rounded","Hiragino Maru Gothic ProN","Arial Rounded MT Bold",Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; --shadow:0 8px 24px rgba(35,42,51,.06); }
    * { box-sizing:border-box } html { background:var(--canvas) } body { margin:0; color:var(--ink); background:var(--canvas); font:16px/1.55 Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; } a { color:inherit } button,input,textarea,select { font:inherit } :focus-visible { outline:0; box-shadow:0 0 0 2px #fff,0 0 0 5px var(--brand-deep) } .skip-link { position:fixed; z-index:50; top:10px; left:10px; padding:10px 16px; color:white; background:var(--brand-deep); border-radius:999px; transform:translateY(-160%); } .skip-link:focus { transform:none; }
    h1,h2,h3 { margin:0; color:var(--ink); font-family:var(--display); letter-spacing:-.02em; overflow-wrap:anywhere } h1 { max-width:760px; font-size:clamp(32px,4vw,52px); line-height:1.05; font-weight:800 } h2 { font-size:24px; line-height:1.15; font-weight:800 } h3 { font-size:16px; line-height:1.25; font-weight:750 } p { margin:0; overflow-wrap:anywhere } .eyebrow { margin:0 0 8px; color:var(--brand-deep); font-size:11px; font-weight:850; letter-spacing:.14em; text-transform:uppercase; } .lead { max-width:690px; margin-top:14px; color:var(--muted); font-size:17px; } .small { color:var(--muted); font-size:12px; }
    header { background:var(--navy); color:var(--ink); border-bottom:3px solid var(--sky); } .shell { width:min(1240px,calc(100% - 48px)); margin:auto; } header nav { min-height:72px; display:flex; align-items:center; justify-content:space-between; gap:24px; } .brand-top { display:flex; align-items:center; gap:14px; text-decoration:none; } .brand-top img { display:block; width:188px; height:auto; filter:brightness(0) opacity(.85); } .nav-note { color:var(--muted); font-size:11px; font-weight:800; letter-spacing:.13em; text-transform:uppercase; }
    .app-shell { min-height:100vh; display:grid; grid-template-columns:248px minmax(0,1fr) } .sidebar { position:sticky; top:0; min-width:0; height:100vh; display:flex; flex-direction:column; padding:28px 20px 20px; color:var(--ink); background:var(--navy); border-right:1px solid var(--line); overflow:auto } .brand { display:block; width:176px; max-width:100%; line-height:0 } .brand img { display:block; width:100%; height:auto; filter:brightness(0) opacity(.85) } .product-lockup { margin:27px 8px 22px; padding-top:20px; border-top:1px solid var(--line) } .product-lockup span,.product-lockup strong { display:block } .product-lockup span { color:var(--brand-deep); font-size:11px; font-weight:800; letter-spacing:.14em; text-transform:uppercase } .product-lockup strong { margin-top:3px; color:var(--ink); font-size:18px; font-family:var(--display); font-weight:800; letter-spacing:-.02em }
    .workflow-rail { min-height:0 } .nav-label { margin:0 10px 8px; color:var(--muted); font-size:10px; font-weight:800; letter-spacing:.12em; text-transform:uppercase } .workflow-rail ol { display:grid; gap:4px; margin:0; padding:0; list-style:none } .workflow-rail li { position:relative; display:flex; align-items:center; gap:11px; min-height:46px; padding:8px 12px; color:var(--muted); border-radius:999px; font-size:13px; font-weight:700 } .workflow-rail li.current { color:var(--ink); background:var(--blush) } .workflow-rail li.current:before { content:""; position:absolute; left:-20px; width:4px; height:26px; border-radius:0 3px 3px 0; background:var(--brand) } .workflow-rail li.complete { color:var(--success) } .step-number { flex:0 0 auto; display:grid; place-items:center; width:24px; height:24px; color:var(--muted); border:1px solid var(--line-strong); border-radius:50%; font-size:11px } .workflow-rail li.current .step-number { color:#fff; border-color:var(--brand-deep); background:var(--brand-deep) } .workflow-rail li.complete .step-number { color:var(--success); border-color:var(--success-line); background:var(--success-soft) }
    .signout { margin:18px 8px 0 } .signout button { min-height:36px; padding:0 14px; color:var(--ink); border:1px solid var(--line-strong); border-radius:999px; background:transparent; font-size:11px; font-weight:800; letter-spacing:.1em; text-transform:uppercase; cursor:pointer } .signout button:hover { color:var(--brand-press); border-color:var(--brand-press); background:var(--cream) }
    .sidebar-note { display:flex; gap:10px; align-items:flex-start; margin-top:auto; padding:15px; color:var(--muted); border:1px solid var(--line); border-radius:12px; background:var(--wash) } .sidebar-note>div { min-width:0 } .sidebar-note strong { display:block; color:var(--ink); font-size:12px } .sidebar-note p { margin-top:2px; color:var(--muted); font-size:11px; line-height:1.4 } .status-dot { flex:0 0 auto; width:8px; height:8px; margin-top:5px; border-radius:50%; background:var(--brand); box-shadow:0 0 0 4px rgba(240,86,63,.16) }
    .main-workspace { min-width:0; padding:36px clamp(22px,4vw,64px) 72px } .workspace-inner { width:min(1120px,100%); margin:0 auto } .page-header { display:flex; justify-content:space-between; align-items:flex-start; gap:24px; margin-bottom:28px } .page-header-copy { min-width:0 } .top-status { display:inline-flex; align-items:center; gap:8px; min-height:30px; padding:5px 12px; color:var(--brand-press); border:1px solid var(--blush-line); border-radius:999px; background:var(--blush); font-size:11px; font-weight:800; white-space:nowrap }
    .panel { padding:26px; border:1px solid var(--line); border-radius:16px; background:var(--surface); box-shadow:var(--shadow) } .panel p { margin-top:7px; color:var(--muted) } .hero-card { position:relative; overflow:hidden; padding:38px; border-top:4px solid var(--brand) } .hero-card:after { content:""; position:absolute; right:-72px; bottom:-100px; width:230px; height:230px; border:44px solid var(--blush); border-radius:50%; opacity:.75 } .hero-copy { position:relative; z-index:1 }
    .actions { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-top:20px } button,.button { max-width:100%; min-height:46px; display:inline-flex; align-items:center; justify-content:center; gap:8px; padding:10px 22px; color:white; border:1px solid var(--brand-deep); border-radius:999px; background:var(--brand-deep); font-weight:800; text-align:center; white-space:normal; text-decoration:none; cursor:pointer; transition:transform .14s ease,box-shadow .14s ease,background .14s ease } button:hover,.button:hover { background:var(--brand-press); border-color:var(--brand-press); box-shadow:0 8px 18px rgba(240,86,63,.22); transform:translateY(-1px) } button.secondary,.button.secondary { color:var(--ink); border-color:var(--ink); background:white } button.secondary:hover,.button.secondary:hover { color:var(--brand-press); background:var(--cream) }
    .upload-note { display:flex; gap:10px; align-items:flex-start; margin-top:18px; padding:14px 16px; color:var(--muted); border:1px dashed var(--line-strong); border-radius:12px; background:var(--wash); font-size:12px } .upload-note strong { color:var(--ink) }
    .section-heading { display:flex; justify-content:space-between; gap:18px; align-items:end; margin:36px 0 14px } .section-heading h2 { font-size:21px } .queue { display:grid; gap:10px; min-width:0; margin:15px 0 0; padding:0; list-style:none } .queue li { min-width:0; padding:13px 16px; border:1px solid var(--line); border-radius:12px; background:white; box-shadow:var(--shadow) } .queue a { font-weight:800; text-decoration-color:var(--brand); text-decoration-thickness:2px; text-underline-offset:4px } .empty-state { color:var(--muted); border-style:dashed; text-align:center }
    .meta { display:flex; flex-wrap:wrap; gap:8px; margin-top:9px; color:var(--muted); font-size:12px } .tag { display:inline-flex; align-items:center; padding:4px 10px; color:var(--ink-soft); border:1px solid var(--line-strong); border-radius:999px; background:var(--wash); font-size:10px; font-weight:850; letter-spacing:.05em; text-transform:uppercase } .mono { font:11px ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:0 }
    .document-layout { display:grid; grid-template-columns:minmax(0,1fr) 360px; gap:20px; align-items:start } .signal { display:grid; grid-template-columns:152px minmax(0,1fr); gap:18px; padding:20px 0; border-bottom:1px solid var(--line) } .signal:last-of-type { border-bottom:0 } .signal-heading { display:flex; align-items:center; gap:9px } .signal-icon { flex:0 0 auto; display:grid; place-items:center; width:25px; height:25px; border:1px solid currentColor; border-radius:50%; font-weight:900; line-height:1 } .chip { display:inline-flex; align-items:center; gap:5px; width:max-content; max-width:100%; padding:5px 10px; border:1px solid currentColor; border-radius:999px; font-size:10px; font-weight:850; letter-spacing:.055em; line-height:1.1; text-transform:uppercase } .needs_attention .chip { background:var(--attention-soft) } .review_recommended .chip { background:var(--review-soft) } .verified_signal .chip { background:var(--success-soft) } .not_assessed .chip { background:var(--neutral-soft) } .needs_attention .chip,.needs_attention .signal-icon { color:var(--attention) } .review_recommended .chip,.review_recommended .signal-icon { color:var(--review) } .verified_signal .chip,.verified_signal .signal-icon { color:var(--success) } .not_assessed .chip,.not_assessed .signal-icon { color:var(--neutral) } .signal p { margin-top:5px; color:var(--muted); font-size:13px }
    .fixlab { position:sticky; top:24px; padding:24px; border:1px solid var(--line); border-top:4px solid var(--brand); border-radius:16px; background:white; box-shadow:var(--shadow) } .fixlab h2 { font-size:22px } .fixlab p { margin-top:7px; color:var(--muted); font-size:13px } label { display:block; margin:15px 0 6px; color:var(--ink); font-size:13px; font-weight:760 } input,select { width:100%; padding:11px 12px; color:var(--ink); border:1px solid var(--line-strong); border-radius:10px; background:white } input[type=checkbox] { width:auto; margin-right:7px } details { margin-top:12px; padding:13px 14px; border:1px solid var(--line); border-radius:12px; background:var(--wash) } summary { color:var(--ink); cursor:pointer; font-weight:760 } .advanced { margin-top:18px }
    .completeness { border-style:dashed; background:var(--wash) } .completeness ul { margin:8px 0 0; padding-left:19px; color:var(--muted); font-size:12px } .completeness li { margin:4px 0 }
    .block-row { margin:10px 0; padding:9px 11px; border:1px solid var(--line); border-radius:10px; background:white } .block-row label { margin:0 0 4px; font-size:11px; letter-spacing:.09em; text-transform:uppercase } .block-row select { min-height:36px; padding:6px 8px; font-size:13px } .block-preview { display:block; margin-top:5px; color:var(--muted); font-size:12px }
    .progress-card { max-width:760px; margin:34px auto; padding:38px; text-align:center } .progress-orb { position:relative; display:grid; place-items:center; width:72px; height:72px; margin:0 auto 20px; border:8px solid var(--blush); border-top-color:var(--brand); border-radius:50%; animation:spin 1.1s linear infinite } .progress-orb:after { content:""; width:26px; height:34px; border:2px solid var(--brand-deep); border-radius:6px; background:white } .progress-list { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin:26px 0 0; padding:0; list-style:none; text-align:left } .progress-list li { padding:13px; color:var(--muted); border:1px solid var(--line); border-radius:12px; background:var(--wash); font-size:12px } .progress-list li strong { display:block; color:var(--ink); font-size:13px } .progress-list li.active { border-color:var(--blush-line); background:var(--blush) }
    .completion { display:flex; gap:14px; align-items:flex-start; margin-bottom:20px; padding:20px 22px; color:var(--success); border:1px solid var(--success-line); border-radius:16px; background:var(--success-soft) } .completion-mark { flex:0 0 auto; display:grid; place-items:center; width:36px; height:36px; color:white; border-radius:12px; background:var(--success); font-weight:900 } .completion h2 { color:var(--success); font-size:21px } .completion p { margin-top:4px; color:var(--success) }
    .sso-caption { margin-top:9px; color:var(--muted); font-size:14px } .login-divider { display:flex; align-items:center; gap:12px; margin:20px 0 4px; color:var(--muted); font-size:14px; font-weight:800; letter-spacing:.12em; text-transform:uppercase } .login-divider:before,.login-divider:after { content:""; flex:1; height:1px; background:var(--line) }
    #upload-file { padding:12px; border-style:dashed; background:var(--wash); cursor:pointer } #upload-file::file-selector-button { margin-right:12px; min-height:38px; padding:6px 16px; color:var(--ink); border:1px solid var(--ink); border-radius:999px; background:white; font:inherit; font-weight:800; cursor:pointer }
    .sample-row { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-top:18px; padding-top:18px; border-top:1px dashed var(--line-strong) } .sample-row p { margin:0; color:var(--muted) }
    .persona { display:flex; gap:10px; align-items:center; margin:18px 8px 0; padding:12px 14px; border:1px solid var(--line); border-radius:12px; background:var(--wash) } .persona-mark { flex:0 0 auto; display:grid; place-items:center; width:30px; height:30px; color:white; border-radius:50%; background:var(--brand-deep); font-weight:850 } .persona>div { min-width:0 } .persona strong { display:block; color:var(--ink); font-size:14px } .persona p { color:var(--muted); font-size:14px }
    .sponsor-card { max-width:760px; margin:18px auto 0; background:var(--wash) } .sponsor-top { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-bottom:12px } .sponsor-label { display:inline-flex; align-items:center; padding:4px 12px; color:white; border-radius:999px; background:var(--ink); font-size:14px; font-weight:850; letter-spacing:.08em; text-transform:uppercase } .sponsor-disclosure { color:var(--muted); font-size:14px } .sponsor-tagline { margin-top:4px; color:var(--brand-press); font-size:14px; font-weight:800 } .sponsor-message { margin-top:8px; color:var(--ink-soft) } .sponsor-cta { display:inline-flex; align-items:center; margin-top:12px; padding:7px 14px; color:var(--brand-press); border:1px solid var(--blush-line); border-radius:999px; background:var(--blush); font-size:14px; font-weight:800 } .sponsor-note { margin-top:12px; color:var(--muted); font-size:14px }
    .sponsor-progress { position:relative; height:4px; margin-top:14px; border-radius:999px; background:var(--blush); overflow:hidden } .sponsor-progress:after { content:""; position:absolute; top:0; bottom:0; left:0; width:34%; border-radius:999px; background:var(--brand); animation:sweep 2.4s ease-in-out infinite alternate } @keyframes sweep { from { transform:translateX(-20%) } to { transform:translateX(220%) } }
    .summary-chips { display:flex; flex-wrap:wrap; gap:8px; margin:0 0 18px } .summary-chips .chip { font-size:14px }
    .produce-card { margin-bottom:20px; border-top:4px solid var(--brand) } .produce-grid { display:flex; flex-wrap:wrap; gap:30px; align-items:center } .produce-copy { flex:1 1 320px; min-width:0 } .produce-copy p { margin-top:7px; color:var(--muted) }
    .seal-badge { flex:0 0 auto; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:3px; width:190px; height:190px; padding:20px; border:6px solid var(--brand); border-radius:50%; background:var(--cream); box-shadow:0 0 0 3px white,0 0 0 4px var(--blush-line); text-align:center } .seal-badge span { color:var(--brand-press); font-size:14px; font-weight:850; letter-spacing:.06em; text-transform:uppercase } .seal-badge strong { color:var(--ink); font-family:var(--display); font-size:15px; line-height:1.25; font-weight:800 } .seal-badge .seal-fineprint { color:var(--ink-soft); font-size:14px; font-weight:700; letter-spacing:0; text-transform:none }
    .locked { padding:24px; color:var(--attention); border-left:4px solid var(--attention); border-radius:12px; background:var(--attention-soft) } .login { width:min(470px,calc(100% - 30px)); margin:56px auto } .login .panel { padding:32px } main.simple { padding:28px 0 72px }
    .eyebrow,.small,.product-lockup span,.nav-label,.workflow-rail li,.step-number,.sidebar-note strong,.sidebar-note p,.top-status,.upload-note,.meta,.tag,.chip,.signal p,.fixlab p,label,.completeness,.block-preview,.progress-list li,.progress-list li strong,.mono,.nav-note { font-size:14px }
    @keyframes spin { to { transform:rotate(360deg) } }
    @media(max-width:900px) { .app-shell { grid-template-columns:1fr } .sidebar { position:static; width:100%; height:auto; padding:18px 20px; border-right:0; border-bottom:1px solid var(--line); overflow-x:hidden } .brand { width:150px } .product-lockup { display:none } .workflow-rail { width:100%; max-width:100%; margin-top:18px; overflow-x:auto } .workflow-rail .nav-label { display:none } .workflow-rail ol { display:flex; min-width:max-content } .workflow-rail li { min-height:42px; padding:7px 12px } .workflow-rail li.current:before { display:none } .sidebar-note { margin-top:14px; padding:10px 12px } .signout { margin:14px 0 0 } .main-workspace { padding-top:26px } .document-layout { grid-template-columns:1fr } .fixlab { position:static } .brand-top img { width:160px } .nav-note { display:none } }
    @media(max-width:680px) { .main-workspace { padding:22px 15px 56px } .page-header { display:block } .top-status { margin-top:14px; white-space:normal } .hero-card { padding:26px 22px } .panel { padding:21px } .section-heading { align-items:start; flex-direction:column } .signal { grid-template-columns:1fr; gap:9px } .progress-card { padding:28px 20px } .progress-list { grid-template-columns:1fr } }
    @media(prefers-reduced-motion:reduce) { *,*:before,*:after { scroll-behavior:auto!important; animation-duration:.01ms!important; animation-iteration-count:1!important; transition-duration:.01ms!important } }
    """
    icon = "<link rel=\"icon\" href=\"/assets/favicon.svg\" type=\"image/svg+xml\">"
    return f"""<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><meta name=\"theme-color\" content=\"#FFFFFF\"><title>{escape(title)}</title>{icon}{head}<style>{css}</style></head><body>{body}</body></html>""".encode()


def _simple_page(title: str, inner: str) -> bytes:
    """A plain navy-header page for login, lock-outs, and error surfaces."""
    header = '<header><div class=shell><nav><a class=brand-top href="/app"><img src="/assets/coastline-college-logo-white.png" alt="Coastline College"></a><span class=nav-note>Accessibility Hub</span></nav></div></header>'
    return _html_page(title, f"{header}<main class=simple>{inner}</main>")


def _session_token(settings: ServiceSettings, actor: str = ACTOR_ID, display: str = "") -> str:
    session = {"actor": actor, "tenant": TENANT_ID, "exp": int(time.time()) + 28800}
    if display:
        session["display"] = display
    payload = base64.urlsafe_b64encode(json.dumps(session).encode()).decode().rstrip("=")
    signature = hmac.new((settings.session_secret or "").encode(), payload.encode(), sha256).hexdigest()
    return f"{payload}.{signature}"


def _session_data(environ: dict[str, Any], settings: ServiceSettings) -> dict[str, Any] | None:
    if not settings.login_ready:
        return None
    cookies = {part.split("=", 1)[0].strip(): part.split("=", 1)[1] for part in environ.get("HTTP_COOKIE", "").split(";") if "=" in part}
    token = cookies.get("hub_session", "")
    try:
        payload, signature = token.rsplit(".", 1)
        expected = hmac.new((settings.session_secret or "").encode(), payload.encode(), sha256).hexdigest()
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if hmac.compare_digest(signature, expected) and data.get("tenant") == TENANT_ID and int(data["exp"]) > time.time():
            return data
    except Exception:
        pass
    return None


def _authenticated(environ: dict[str, Any], settings: ServiceSettings) -> bool:
    return _session_data(environ, settings) is not None


def _response(start_response: Callable, status: str, body: bytes, headers: list[tuple[str, str]] | None = None) -> list[bytes]:
    base = [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store"), ("X-Frame-Options", "DENY"), ("Referrer-Policy", "no-referrer"), ("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")]
    start_response(status, base + (headers or []))
    return [body]


def _redirect(start_response: Callable, location: str, headers: list[tuple[str, str]] | None = None) -> list[bytes]:
    start_response("303 See Other", [("Location", location), ("Content-Length", "0"), ("Cache-Control", "no-store")] + (headers or []))
    return [b""]


def _form(environ: dict[str, Any]) -> dict[str, str]:
    # A malformed or hostile Content-Length must not crash the handler or defeat
    # the read cap. Clamp to [0, 50_000]; a non-integer header reads nothing.
    try:
        declared = int(environ.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        declared = 0
    size = min(max(declared, 0), 50_000)
    values = parse_qs(environ["wsgi.input"].read(size).decode("utf-8", "replace"))
    return {key: value[-1] for key, value in values.items()}


def _lane_rank(signal: dict[str, Any]) -> int:
    lane = signal.get("lane")
    return LANE_ORDER.index(lane) if lane in LANE_ORDER else len(LANE_ORDER)


def _signals(result: dict[str, Any] | None, job_state: str = "queued") -> str:
    if not result:
        if job_state == "failed":
            return "<p class=\"small\">This assessment did not complete, so no signals are shown. The document record is unchanged. Remove this record and start a new synthetic review, or check the service logs for the recorded error code.</p>"
        return "<p class=\"small\">Assessment is queued. This page refreshes automatically while it runs.</p>"
    cards = []
    for signal in sorted(result.get("signals", []), key=_lane_rank):
        lane = signal["lane"]
        icon, label = LANE_PRESENTATION.get(lane, LANE_PRESENTATION["not_assessed"])
        context = " <span class=tag>educator context</span>" if signal.get("educator_context") else ""
        cards.append(f"<article class=\"signal {escape(lane)}\"><div><span class=\"chip\"><span aria-hidden=true>{icon}</span>{escape(label)}</span></div><div><div class=signal-heading><span class=signal-icon aria-hidden=true>{icon}</span><h3>{escape(signal['title'])}</h3></div><p>{escape(signal.get('evidence') or '')}</p><p><strong>Next:</strong> {escape(signal.get('next_action') or '')}{context}</p></div></article>")
    notes = result.get("completeness") or []
    strip = ""
    if notes:
        items = "".join(f"<li>{escape(note)}</li>" for note in notes)
        strip = f"<details class=completeness><summary>Review completeness</summary><p class=small>Some checks were not part of this review. That says nothing about the document itself.</p><ul>{items}</ul></details>"
    return "".join(cards) + "<p class=small>Each signal stands on its own. The workspace does not create an overall result.</p>" + strip


def _structure_fix(document_id: str, blocks: list[str]) -> str:
    if not blocks:
        return (
            "<details><summary>Build tags from your confirmed structure</summary>"
            "<p class=small>Tag building needs extractable text in this copy. If this is a scan, add a text layer first, then build tags on the new version.</p></details>"
        )
    rows = []
    for index, text in enumerate(blocks[:MAX_FORM_BLOCKS]):
        preview = text.strip()
        if len(preview) > 90:
            preview = preview[:90].rstrip() + "…"
        options = "".join(
            f"<option value={value}{' selected' if value == ('h1' if index == 0 else 'p') else ''}>{label}</option>"
            for value, label in STRUCTURE_ROLES
        )
        rows.append(
            f"<div class=block-row><label for=role_{index}>Block {index + 1}</label>"
            f"<select id=role_{index} name=role_{index}>{options}</select>"
            f"<span class=block-preview>{escape(preview)}</span></div>"
        )
    count = len(blocks[:MAX_FORM_BLOCKS])
    return (
        "<details><summary>Build tags from your confirmed structure</summary>"
        "<p class=small>Confirm what each block is. Reading order follows the page order shown here.</p>"
        f"<form method=post action=\"/documents/{escape(document_id)}/remediate/structure\">"
        f"<input type=hidden name=block_count value={count}>"
        + "".join(rows)
        + "<label><input type=checkbox name=confirmed value=yes required> I confirm these roles and this reading order.</label>"
        "<div class=actions><button class=secondary>Build tags and recheck</button></div></form></details>"
    )


def _guided_structure_roles(form: dict[str, str]) -> dict[str, str]:
    try:
        count = int(form.get("block_count", ""))
    except (TypeError, ValueError):
        raise RemediationError("The structure form was incomplete. Return to the document and try again.")
    count = max(0, min(count, MAX_FORM_BLOCKS))
    return {str(index): form.get(f"role_{index}", "p") for index in range(count)}


def create_app(settings: ServiceSettings | None = None, repository: StagingRepository | None = None, worker: AssessmentWorker | None = None):
    settings = settings or ServiceSettings.from_environ()
    repository = repository or StagingRepository(settings.data_dir)
    worker = worker or AssessmentWorker(repository)
    worker.start()

    def _ocr_in_lineage(document: dict[str, Any]) -> bool:
        current: dict[str, Any] | None = document
        seen: set[str] = set()
        while current is not None and current["id"] not in seen:
            seen.add(current["id"])
            if any(row["kind"] == "ocr" for row in repository.remediations(TENANT_ID, current["id"])):
                return True
            parent_id = current.get("parent_document_id")
            current = repository.document(TENANT_ID, parent_id) if parent_id else None
        return False

    def app(environ: dict[str, Any], start_response: Callable):
        path, method = environ.get("PATH_INFO", "/"), environ.get("REQUEST_METHOD", "GET")
        if path == "/assets/coastline-college-logo-white.png" and method == "GET":
            asset = Path(__file__).resolve().parents[1] / "assets" / "coastline-college-logo-white.png"
            if asset.is_file():
                payload = asset.read_bytes()
                start_response("200 OK", [("Content-Type", "image/png"), ("Content-Length", str(len(payload))), ("Cache-Control", "public, max-age=86400"), ("X-Content-Type-Options", "nosniff")])
                return [payload]
            start_response("404 Not Found", [("Content-Length", "0")])
            return [b""]
        if path in {"/favicon.ico", "/assets/favicon.svg"} and method == "GET":
            asset = Path(__file__).resolve().parents[1] / "assets" / "favicon.svg"
            payload = asset.read_bytes() if asset.is_file() else _FALLBACK_FAVICON
            start_response("200 OK", [("Content-Type", "image/svg+xml"), ("Content-Length", str(len(payload))), ("Cache-Control", "public, max-age=86400"), ("X-Content-Type-Options", "nosniff")])
            return [payload]
        if path == "/healthz":
            payload = json.dumps(settings.health_payload()).encode()
            start_response("200 OK", [("Content-Type", "application/json"), ("Content-Length", str(len(payload))), ("Cache-Control", "no-store")])
            return [payload]
        if path == "/logout" and method == "POST":
            expired = "hub_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0" + ("; Secure" if settings.environment == "staging" else "")
            return _redirect(start_response, "/login?signed-out=1", [("Set-Cookie", expired)])
        if path == "/login" and method == "GET":
            if settings.login_ready:
                note = "<p class=small>You are signed out.</p>" if "signed-out=1" in environ.get("QUERY_STRING", "") else ""
                sso = ""
                if settings.environment == "development":
                    # Honest stub: development-only, one click, no directory contacted.
                    sso = ('<form method=post action="/login/sso"><div class=actions><button>Sign in with your Coastline Microsoft account</button></div></form>'
                           '<p class=sso-caption>Demo sign-in — no Microsoft account is contacted.</p>'
                           '<div class=login-divider aria-hidden=true>or</div>')
                return _response(start_response, "200 OK", _simple_page("Sign in — Accessibility Hub", f"<div class=login><section class=panel><p class=eyebrow>Access</p><h2>Enter the staging workspace</h2>{note}{sso}<p>Enter your access code to continue.</p><form method=post><label for=code>Access code</label><input id=code name=code type=password autocomplete=current-password required><div class=actions><button class={'secondary' if sso else 'primary'}>Continue</button></div></form></section></div>"))
            return _response(start_response, "503 Service Unavailable", _simple_page("Access setup required", "<div class=login><section class=locked><h2>Access setup is incomplete</h2><p>This service remains closed until a staging access code and session secret are configured.</p></section></div>"))
        if path == "/login" and method == "POST":
            code = _form(environ).get("code", "")
            if settings.login_ready and hmac.compare_digest(code, settings.access_code or ""):
                cookie = f"hub_session={_session_token(settings)}; HttpOnly; SameSite=Lax; Path=/" + ("; Secure" if settings.environment == "staging" else "")
                return _redirect(start_response, "/app", [("Set-Cookie", cookie)])
            return _response(start_response, "401 Unauthorized", _simple_page("Sign in — Accessibility Hub", "<div class=login><section class=locked><h2>That code did not open the workspace.</h2><p><a href=\"/login\">Try again</a></p></section></div>"))
        if path == "/login/sso" and method == "POST":
            # Development-only stub SSO. Hosted staging keeps the access-code
            # form exclusively; there this route does not exist.
            if settings.environment != "development" or not settings.login_ready:
                return _response(start_response, "404 Not Found", _simple_page("Not found", "<div class=shell><h1>Page not found</h1><p class=lead><a href=\"/login\">Return to sign in</a></p></div>"))
            cookie = f"hub_session={_session_token(settings, actor=SSO_ACTOR, display=SSO_DISPLAY)}; HttpOnly; SameSite=Lax; Path=/"
            return _redirect(start_response, "/app", [("Set-Cookie", cookie)])
        session = _session_data(environ, settings)
        signed_in = session is not None
        persona = (session or {}).get("display") or ""
        actor = (session or {}).get("actor") or ACTOR_ID
        dev = settings.environment == "development"
        if not settings.public_access and not signed_in:
            return _redirect(start_response, "/login")
        if path in {"/", "/app"} and method == "GET":
            documents = repository.list_documents(TENANT_ID)
            by_id = {d["id"]: d for d in documents}

            def _root_of(doc: dict[str, Any]) -> dict[str, Any]:
                seen: set[str] = set()
                while doc.get("parent_document_id") in by_id and doc["id"] not in seen:
                    seen.add(doc["id"])
                    doc = by_id[doc["parent_document_id"]]
                return doc

            def _depth_of(doc: dict[str, Any]) -> int:
                depth, seen = 1, set()
                while doc.get("parent_document_id") in by_id and doc["id"] not in seen:
                    seen.add(doc["id"])
                    doc = by_id[doc["parent_document_id"]]
                    depth += 1
                return depth

            lineages: dict[str, dict[str, Any]] = {}
            for doc in documents:  # created_at DESC → first doc seen per lineage is its newest version.
                root = _root_of(doc)
                entry = lineages.setdefault(root["id"], {"root": root, "latest": doc, "count": 0})
                entry["count"] += 1
            rows = ""
            for entry in lineages.values():
                latest, root = entry["latest"], entry["root"]
                version = max(_split_version(latest["filename"])[1], _depth_of(latest))
                display = _split_version(root["filename"])[0] + ".pdf"
                state = STATE_LABELS.get(latest.get("job_state") or "queued", "Review queued")
                versions_note = f"<span>{entry['count']} versions</span>" if entry["count"] > 1 else ""
                rows += f"<li><a href=\"/documents/{escape(latest['id'])}\"><strong>{escape(display)}</strong></a><div class=meta><span class=tag>v{version}</span><span class=tag>{escape(state)}</span>{versions_note}<span>{escape(_when(latest['created_at']))}</span></div></li>"
            rows = rows or "<li class=empty-state>No review has started yet. Begin with the card above.</li>"
            educator_session = dev and settings.synthetic_intake_ready and actor == SSO_ACTOR
            if educator_session:
                # Development only, and only for the demo educator sign-in:
                # real local upload, with the samples demoted to a secondary
                # "or try a sample" row. Access-code sessions keep the classic
                # synthetic-only workspace in every environment, so the smoke
                # boundary checks hold verbatim against a dev instance.
                hero = '''<section class="panel hero-card" aria-labelledby=start-heading><div class=hero-copy><p class=eyebrow>1 · Review</p><h2 id=start-heading>Upload your course material</h2><p class=lead>Choose a PDF from your computer (up to 50 MB). It stays on this machine, and the review starts right away.</p>
                <form method=post action="/documents/upload" enctype="multipart/form-data"><label for=upload-file>Course material (PDF)</label><input id=upload-file type=file name=file accept="application/pdf,.pdf" required><div class=actions><button>Upload and review <span aria-hidden=true>→</span></button></div></form>
                <div class=sample-row><p>Or try a sample:</p><form method=post action="/documents/synthetic"><button class=secondary name=fixture value=handout>Try the course handout</button></form><form method=post action="/documents/synthetic"><button class=secondary name=fixture value=scan>Try the scanned sample</button></form></div></div></section>'''
                status_pill = "Local development workspace"
            elif settings.synthetic_intake_ready:
                primary_action = '<form method=post action="/documents/synthetic"><button name=fixture value=handout>Start a sample review <span aria-hidden=true>→</span></button></form>'
                secondary_action = '<form method=post action="/documents/synthetic"><button class=secondary name=fixture value=scan>Try the scanned sample</button></form>'
                # Honest note per session: a development access-code session
                # could switch to the demo educator sign-in; hosted staging
                # accepts no real documents at all.
                upload_note = ("<strong>Real-document upload opens with the demo educator sign-in.</strong><br>This access-code session reviews only the bundled synthetic samples. Sign out and use the demo sign-in to upload a local PDF."
                               if dev else
                               "<strong>Real-document upload is not available in this environment.</strong><br>Real, institutional, and public uploads are not accepted — only the bundled synthetic samples.")
                hero = f'''<section class="panel hero-card" aria-labelledby=start-heading><div class=hero-copy><p class=eyebrow>1 · Review</p><h2 id=start-heading>Choose a sample</h2><p class=lead>Use the course handout for metadata and structure signals, or the scanned handout to review an OCR text layer.</p><div class=actions>{primary_action}{secondary_action}</div><div class=upload-note><span aria-hidden=true>🔒</span><div>{upload_note}</div></div></div></section>'''
                status_pill = "Safe sample workspace"
            else:
                locked = '<div class=locked><h3>Hosted controls are not connected</h3><p>Private storage, scan gate, isolated worker, tenant authorization, lifecycle, and audit integrations must be configured before a hosted process can begin.</p></div>'
                hero = f'''<section class="panel hero-card" aria-labelledby=start-heading><div class=hero-copy><p class=eyebrow>1 · Review</p><h2 id=start-heading>Choose a sample</h2><p class=lead>Use the course handout for metadata and structure signals, or the scanned handout to review an OCR text layer.</p><div class=actions>{locked}</div><div class=upload-note><span aria-hidden=true>🔒</span><div><strong>Real-document upload is not available in this environment.</strong><br>Real, institutional, and public uploads are not accepted — only the bundled synthetic samples.</div></div></div></section>'''
                status_pill = "Safe sample workspace"
            content = f'''<div class=workspace-inner><header class=page-header><div class=page-header-copy><p class=eyebrow>Accessibility Hub</p><h1>See what to improve. Keep what already works.</h1><p class=lead>{'Upload a handout, review clear signals, make one intentional change, then verify the new version.' if educator_session else 'Start with a supplied handout, review clear signals, make one intentional change, then verify the new version.'}</p></div><span class=top-status><span class=status-dot aria-hidden=true></span>{status_pill}</span></header>
            {hero}
            <section aria-labelledby=recent-heading><div class=section-heading><div><p class=eyebrow>Workspace</p><h2 id=recent-heading>Document records</h2></div><p class=small>One row per document. Improved copies appear as new versions of the same row.</p></div><ul class=queue>{rows}</ul></section></div>'''
            return _response(start_response, "200 OK", _html_page("Accessibility Hub staging", _app_shell("add", content, signed_in, dev, persona)))
        if path == "/documents/upload" and method == "POST" and settings.environment == "development" and actor == SSO_ACTOR:
            # Development-only real upload, and only for the demo educator
            # session established by the stub SSO. In staging — and for
            # access-code sessions anywhere — this branch is never entered, so
            # the request falls through to the document-id lookup below and
            # 404s: the route does not exist outside the educator dev session.
            if not settings.synthetic_intake_ready:
                return _response(start_response, "503 Service Unavailable", _simple_page("Accessibility Hub", "<div class=shell><section class=locked><h2>This workspace is not ready to accept an upload.</h2><p>Configure the access code and session secret first.</p></section></div>"))
            try:
                declared = int(environ.get("CONTENT_LENGTH") or 0)
            except (TypeError, ValueError):
                declared = 0
            if declared > UPLOAD_READ_CAP:
                return _response(start_response, "413 Request Entity Too Large", _simple_page("Upload too large", "<div class=shell><section class=locked><h2>This PDF exceeds the 50 MB review limit.</h2><p><a href=\"/app\">Back to the workspace</a></p></section></div>"))
            part = _multipart_file(environ, "file")
            message = None
            if part is None:
                message = "Choose a PDF file to upload."
            else:
                from local_reviewer import UploadValidationError, validate_pdf_upload
                raw_name, payload = part
                try:
                    # Validate the name the client actually sent, THEN sanitize
                    # for storage — never the other way around.
                    validate_pdf_upload(raw_name.strip(), payload)
                    if not payload:
                        raise UploadValidationError("This file is empty.")
                except UploadValidationError as error:
                    message = str(error)
                filename = _safe_upload_name(raw_name)
            if message is not None:
                return _response(start_response, "400 Bad Request", _simple_page("Upload needs a closer look", f"<div class=shell><section class=locked><h2>This file was not uploaded.</h2><p>{escape(message)}</p><p><a href=\"/app\">Back to the workspace</a></p></section></div>"))
            item = repository.create_document(TENANT_ID, filename, "educator_upload", payload)
            job_id = repository.enqueue(item["id"])
            repository.audit(TENANT_ID, actor, "educator_document_uploaded", item["id"], {"job_id": job_id, "source": item["source_kind"], "bytes": len(payload)})
            return _redirect(start_response, f"/documents/{item['id']}")
        if path == "/documents/synthetic" and method == "POST":
            if not settings.synthetic_intake_ready:
                return _response(start_response, "503 Service Unavailable", _simple_page("Accessibility Hub", "<div class=shell><section class=locked><h2>This staging service is not ready to create a document record.</h2><p>Configure the required private-service controls first.</p></section></div>"))
            fixture = _form(environ).get("fixture", "handout")
            fixtures = {
                "handout": ("coastline-synthetic-course-handout.pdf", synthetic_handout_pdf),
                "scan": ("coastline-synthetic-scanned-handout.pdf", synthetic_scan_pdf),
            }
            if fixture not in fixtures:
                return _response(start_response, "400 Bad Request", _simple_page("Choose a sample", "<div class=shell><section class=locked><h2>Choose one of the supplied samples.</h2><p><a href=\"/app\">Back to the workspace</a></p></section></div>"))
            filename, factory = fixtures[fixture]
            item = repository.create_document(TENANT_ID, filename, "bundled_synthetic_fixture", factory())
            job_id = repository.enqueue(item["id"])
            repository.audit(TENANT_ID, actor, "synthetic_document_created", item["id"], {"job_id": job_id, "source": item["source_kind"]})
            return _redirect(start_response, f"/documents/{item['id']}")
        if path.startswith("/documents/"):
            pieces = path.strip("/").split("/")
            document_id = pieces[1] if len(pieces) > 1 else ""
            document = repository.document(TENANT_ID, document_id)
            if document is None:
                return _response(start_response, "404 Not Found", _simple_page("Not found", "<div class=shell><h1>Document not found</h1><p class=lead><a href=\"/app\">Return to the workspace</a></p></div>"))
            if len(pieces) == 2 and method == "GET":
                job = repository.latest_job(TENANT_ID, document_id)
                result = job.get("result") if job else None
                job_state = job["state"] if job else "queued"
                terminal = job_state in {"succeeded", "failed"}
                is_recheck = bool(document.get("parent_document_id"))
                # A slow vanilla refresh keeps this JavaScript-free page useful
                # while the assessment runs; it stops once the job is terminal.
                refresh_head = "" if terminal else "<meta http-equiv=\"refresh\" content=\"5\">"
                remediation_rows = repository.remediations(TENANT_ID, document_id)
                provenance_items = []
                for row in remediation_rows:
                    detail = row.get("provenance") or {}
                    source_hash = str(detail.get("source_sha256") or "").removeprefix("sha256:")[:10]
                    result_hash = str(detail.get("remediated_sha256") or detail.get("result_sha256") or "").removeprefix("sha256:")[:10]
                    hashes = f" · <span class=mono>{escape(source_hash)}… → {escape(result_hash)}…</span>" if source_hash and result_hash else ""
                    label = REMEDIATION_LABELS.get(row["kind"], row["kind"])
                    provenance_items.append(f"<li><strong>{escape(label)}</strong> <span class=tag>{escape(row['kind'])}</span> · {escape(_when(row['created_at']))}{hashes}</li>")
                provenance = "".join(provenance_items) or "<li>No recheck has been applied to this version.</li>"
                cleanup = f"<details><summary>Remove this synthetic record</summary><p>This removes this version and any rechecked copies from the local staging store.</p><form method=post action=\"/documents/{escape(document_id)}/delete\"><label><input type=checkbox name=confirmed value=yes required> I want to remove these synthetic records.</label><div class=actions><button class=secondary>Remove records</button></div></form></details>"
                if not terminal:
                    current_step = "check" if is_recheck else "review"
                    is_upload = document["source_kind"] == "educator_upload"
                    phase_label = "Checking your improved copy" if is_recheck else ("Reviewing your document" if is_upload else "Reviewing the sample")
                    prepared_step = "<strong>Upload received</strong>Stays on this machine" if is_upload else "<strong>Sample prepared</strong>Bundled content only"
                    progress = f'''<div class=workspace-inner><header class=page-header><div class=page-header-copy><p class=eyebrow><a href="/app">Workspace</a> / review</p><h1>{escape(phase_label)}</h1><p class=lead>{escape(document['filename'])}</p></div><span class=top-status><span class=status-dot aria-hidden=true></span>In progress</span></header><section class="panel progress-card" role=status aria-live=polite aria-atomic=true><div class=progress-orb aria-hidden=true></div><p class=eyebrow>Deterministic review</p><h2>Looking for useful accessibility signals…</h2><p>This usually takes a few seconds. This page checks again every five seconds.</p><ol class=progress-list><li>{prepared_step}</li><li class=active><strong>Reviewing signals</strong>Metadata, structure, and text</li><li><strong>Building next steps</strong>Plain-language guidance</li></ol><div class=actions><a class="button secondary" href="/documents/{escape(document_id)}">Refresh now</a></div><p class=small>Review first — the Fix Lab opens once this review completes.</p></section>{_sponsored_card()}</div>'''
                    return _response(start_response, "200 OK", _html_page("Review in progress — Accessibility Hub", _app_shell(current_step, progress, signed_in, dev, persona), refresh_head))
                resolved_count = 0
                if is_recheck and result:
                    parent_job = repository.latest_job(TENANT_ID, document["parent_document_id"])
                    parent_result = (parent_job or {}).get("result") or {}
                    before = {item.get("rule_id"): item.get("lane") for item in parent_result.get("signals", [])}
                    resolved_count = sum(1 for item in result.get("signals", []) if item.get("lane") == "verified_signal" and before.get(item.get("rule_id")) not in {None, "verified_signal"})
                completion = ""
                if is_recheck and job_state == "succeeded":
                    parent_doc = repository.document(TENANT_ID, document["parent_document_id"]) if document.get("parent_document_id") else None
                    original_word = "document" if (parent_doc or {}).get("source_kind") == "educator_upload" else "sample"
                    if resolved_count:
                        completion_line = f"{resolved_count} accessibility signal{'s are' if resolved_count != 1 else ' is'} now verified in the recheck. The original {original_word} remains unchanged."
                    else:
                        completion_line = f"Compare the lanes with the previous version to see what changed. The original {original_word} remains unchanged."
                    completion = f'''<div class=completion role=status><span class=completion-mark aria-hidden=true>✓</span><div><h2>Your improved copy is ready</h2><p>{completion_line}</p></div></div>'''
                header_title = "Recheck complete" if is_recheck else "Review findings"
                header_lead = "See what changed, then explore the remaining signals." if is_recheck else "Read each signal, decide what to improve, and verify the new version without losing the record of what changed."
                state_label = STATE_LABELS.get(job_state, "Review queued")
                source_label = SOURCE_LABELS.get(document["source_kind"], document["source_kind"])
                counts = _lane_counts(result)
                summary_row = _summary_chips(counts) if job_state == "succeeded" and result else ""
                produce_card = ""
                if dev and job_state == "succeeded" and result and (is_recheck or counts["needs_attention"] == 0):
                    badge = (
                        '<div class=seal-badge role=img aria-label="Reviewed &amp; improved with Coastline College Accessibility Hub — a review record, not a certification">'
                        '<span>Reviewed &amp; improved</span><strong>Coastline College Accessibility Hub</strong>'
                        f'<span class=seal-fineprint>{escape(datetime.now().strftime("%b %d, %Y"))}</span>'
                        f'<span class=seal-fineprint>{escape(document["sha256"][:10])}…</span></div>'
                    )
                    if _seal_available():
                        produce_action = f'<div class=actions><a class=button href="/documents/{escape(document_id)}/produced">Download the reviewed copy <span aria-hidden=true>↓</span></a></div>'
                    else:
                        produce_action = '<div class=actions><button disabled aria-disabled=true>Producing is not available yet</button></div><p class=small>The review-summary sealer is not installed in this environment. Everything above still works.</p>'
                    produce_card = f'''<section class="panel produce-card" aria-labelledby=produce-heading><div class=produce-grid>{badge}<div class=produce-copy><p class=eyebrow>Produce</p><h2 id=produce-heading>Produce your document</h2><p>Download this version with one added "Review summary" page: the review date, a short evidence hash, where findings landed, and the fixes applied. Nothing else in the document changes.</p><p class=small>A review record, not a certification.</p>{produce_action}</div></div></section>'''
                findings = f'''<section class=panel aria-labelledby=findings-heading><p class=eyebrow>{'4 · Verify' if is_recheck else '2 · Understand'}</p><h2 id=findings-heading>Signals and next actions</h2>{_signals(result, job_state)}<div class=advanced><details><summary>Remediation provenance</summary><ul class=queue>{provenance}</ul></details></div></section>'''
                if not is_recheck and job_state == "succeeded":
                    text_layer_open = bool(result) and any(
                        signal.get("rule_id") == "PDF.TEXT_LAYER" and signal.get("lane") in {"needs_attention", "review_recommended"}
                        for signal in result.get("signals", [])
                    )
                    ocr_action = ""
                    if "scanned" in document["filename"] and (text_layer_open or not result) and not _ocr_in_lineage(document):
                        ocr_action = f"<details><summary>Add a text layer from this scan</summary><p>Review the generated text against the scan before relying on it.</p><form method=post action=\"/documents/{escape(document_id)}/remediate/ocr\"><label><input type=checkbox name=confirmed value=yes required> I will review the generated text against the page image.</label><div class=actions><button class=secondary>Apply text layer and recheck</button></div></form></details>"
                    try:
                        blocks = extract_blocks(repository.document_bytes(TENANT_ID, document_id))
                    except Exception:
                        blocks = []
                    suggested = _suggested_title(document["filename"], document["source_kind"])
                    metadata_defects = {s.get("rule_id") for s in (result or {}).get("signals", []) if s.get("lane") in {"needs_attention", "review_recommended"}} & {"PDF.METADATA.TITLE", "PDF.METADATA.LANGUAGE"}
                    one_click = ""
                    if metadata_defects:
                        one_click = f'''<form method=post action="/documents/{escape(document_id)}/remediate/metadata"><input type=hidden name=title value="{escape(suggested)}"><input type=hidden name=language value="en-US"><div class=actions><button>Apply suggested fixes and recheck <span aria-hidden=true>→</span></button></div></form><p class=small>One click sets the title to “{escape(suggested)}” and the language to English (US) in a new copy, then rechecks it.</p><div class=login-divider aria-hidden=true>or</div>'''
                    fixlab = f'''<aside class=fixlab aria-labelledby=fix-heading><p class=eyebrow>3 · Improve</p><h2 id=fix-heading>Fix the clearest issues</h2><p>Add a meaningful title and primary language, then run the check again on a copy.</p>{one_click}<form method=post action="/documents/{escape(document_id)}/remediate/metadata"><label for=document-title>Document title</label><input id=document-title name=title value="{escape(suggested)}" required><label for=document-language>Primary language</label><input id=document-language name=language value="en-US" required><div class=actions><button class={'secondary' if one_click else 'primary'}>Apply and recheck <span aria-hidden=true>→</span></button></div></form><div class=advanced>{_structure_fix(document_id, blocks)}{ocr_action}{cleanup}</div><p class=small>Each recheck creates a new version and keeps the source record intact.</p></aside>'''
                else:
                    parent_link = f'<a class="button secondary" href="/documents/{escape(document["parent_document_id"])}">View original sample</a>' if is_recheck else '<a class="button secondary" href="/app">Start another sample</a>'
                    fixlab = f'''<aside class=fixlab><p class=eyebrow>Next step</p><h2>{'Compare the result' if is_recheck else 'Try another sample'}</h2><p>{'The rechecked copy is stored as a separate version of the same lineage.' if is_recheck else 'This assessment did not complete, so no fixes were applied.'}</p><div class=actions>{parent_link}<a class="button secondary" href="/app">Workspace</a></div><div class=advanced>{cleanup}</div></aside>'''
                content = f'''<div class=workspace-inner><header class=page-header><div class=page-header-copy><p class=eyebrow><a href="/app">Workspace</a> / {escape('recheck' if is_recheck else 'document')}</p><h1>{header_title}</h1><p class=lead>{header_lead}</p><div class=meta><span class=tag>{escape(source_label)}</span><span class=tag>{escape(state_label)}</span><span>{escape(document['filename'])}</span><span class=mono>{escape(document['sha256'][:16])}…</span></div></div><span class=top-status><span class=status-dot aria-hidden=true></span>{'Local workspace' if dev else 'Synthetic demo only'}</span></header>{completion}{summary_row}{produce_card}<div class=document-layout>{findings}{fixlab}</div></div>'''
                return _response(start_response, "200 OK", _html_page("Document review — Accessibility Hub", _app_shell("check" if is_recheck else "improve", content, signed_in, dev, persona), refresh_head))
            if len(pieces) == 3 and pieces[2] == "produced" and method == "GET":
                # Development-only, auth-gated (we are already behind the login
                # wall here). Applies nothing new: seals the CURRENT version's
                # bytes with one appended Review summary page and serves it.
                if settings.environment != "development":
                    return _response(start_response, "404 Not Found", _simple_page("Not found", "<div class=shell><h1>Page not found</h1><p class=lead><a href=\"/app\">Return to the workspace</a></p></div>"))
                job = repository.latest_job(TENANT_ID, document_id)
                if not job or job["state"] != "succeeded" or not job.get("result"):
                    return _redirect(start_response, f"/documents/{document_id}")
                # Mirror the produce-card eligibility exactly: a first review
                # that still has needs-attention signals cannot be produced by
                # visiting the URL directly.
                if not (bool(document.get("parent_document_id")) or _lane_counts(job["result"])["needs_attention"] == 0):
                    return _response(start_response, "409 Conflict", _simple_page("Not ready to produce", f"<div class=shell><section class=locked><h2>This version is not ready to produce.</h2><p>Some signals still need attention. Apply the suggested fixes and recheck, then produce the improved copy.</p><p><a href=\"/documents/{escape(document_id)}\">Return to the document</a></p></section></div>"))
                try:
                    from tina.seal import append_review_summary
                except Exception:
                    return _response(start_response, "503 Service Unavailable", _simple_page("Producing unavailable", f"<div class=shell><section class=locked><h2>Producing is not available yet.</h2><p>The review-summary sealer is not installed in this environment. The review itself is unaffected.</p><p><a href=\"/documents/{escape(document_id)}\">Return to the document</a></p></section></div>"))
                applied_fixes: list[str] = []
                node: dict[str, Any] | None = document
                seen_ids: set[str] = set()
                while node is not None and node["id"] not in seen_ids:
                    seen_ids.add(node["id"])
                    for row in repository.remediations(TENANT_ID, node["id"]):
                        if row["kind"] != "seal":
                            applied_fixes.append(REMEDIATION_LABELS.get(row["kind"], row["kind"]))
                    parent_id = node.get("parent_document_id")
                    node = repository.document(TENANT_ID, parent_id) if parent_id else None
                result = job["result"]
                summary = {
                    "lanes": _lane_counts(result),
                    "applied_fixes": applied_fixes,
                    "verified": [s.get("title") or "" for s in result.get("signals", []) if s.get("lane") == "verified_signal"],
                }
                try:
                    source = repository.document_bytes(TENANT_ID, document_id)
                    sealed, seal_provenance = append_review_summary(document["filename"], source, summary, repo_now()[:10])
                except RemediationError as error:
                    return _response(start_response, "400 Bad Request", _simple_page("Producing needs a closer look", f"<div class=shell><section class=locked><h2>This copy was not produced.</h2><p>{escape(str(error))}</p><p><a href=\"/documents/{escape(document_id)}\">Return to the document</a></p></section></div>"))
                except Exception:
                    return _response(start_response, "500 Internal Server Error", _simple_page("Producing did not complete", f"<div class=shell><section class=locked><h2>This copy was not produced.</h2><p>Something went wrong while adding the review summary page. The document record is unchanged.</p><p><a href=\"/documents/{escape(document_id)}\">Return to the document</a></p></section></div>"))
                if not any(row["kind"] == "seal" for row in repository.remediations(TENANT_ID, document_id)):
                    repository.record_remediation(document_id, document_id, "seal", seal_provenance)
                    repository.audit(TENANT_ID, actor, "review_summary_produced", document_id, {
                        "source_sha256": seal_provenance.get("source_sha256"),
                        "result_sha256": seal_provenance.get("result_sha256"),
                    })
                safe_base = re.sub(r"[^A-Za-z0-9._ ()-]+", "-", _split_version(document["filename"])[0]).strip(" .-") or "document"
                start_response("200 OK", [
                    ("Content-Type", "application/pdf"),
                    ("Content-Disposition", f'attachment; filename="{safe_base}.sealed.pdf"'),
                    ("Content-Length", str(len(sealed))),
                    ("Cache-Control", "no-store"),
                    ("X-Content-Type-Options", "nosniff"),
                ])
                return [sealed]
            if len(pieces) == 3 and pieces[2] == "delete" and method == "POST":
                if _form(environ).get("confirmed") != "yes":
                    return _response(start_response, "400 Bad Request", _simple_page("Removal needs confirmation", f"<div class=shell><section class=locked><h2>This record is still here.</h2><p><a href=\"/documents/{escape(document_id)}\">Return to the document</a></p></section></div>"))
                deleted = repository.delete_document_lineage(TENANT_ID, document_id)
                repository.audit(TENANT_ID, actor, "synthetic_document_deleted", document_id, {"deleted_document_count": deleted})
                return _redirect(start_response, "/app")
            if len(pieces) == 4 and pieces[2] == "remediate" and method == "POST":
                kind, form = pieces[3], _form(environ)
                try:
                    source = repository.document_bytes(TENANT_ID, document_id)
                    if kind == "metadata":
                        fixed, provenance = MetadataRemediation.with_builtin_tools().apply(document["filename"], source, title=form.get("title"), language=form.get("language"))
                    elif kind == "structure":
                        if form.get("confirmed") != "yes":
                            raise RemediationError("Confirm the structure roles and reading order before building tags.")
                        if "roles" in form or "order" in form:
                            roles = json.loads(form.get("roles", "{}"))
                            order = json.loads(form.get("order", "[]")) or None
                        else:
                            roles = _guided_structure_roles(form)
                            order = None  # Reading order defaults to the page order shown in the form.
                        fixed, provenance = StructureRemediation.with_builtin_tools().apply(document["filename"], source, confirmed_roles=roles, reading_order=order)
                    elif kind == "ocr":
                        if form.get("confirmed") != "yes":
                            raise RemediationError("Confirm that you will review generated text before adding a text layer.")
                        fixed, provenance = OcrRemediation.with_builtin_tools().apply(document["filename"], source)
                    else:
                        return _response(start_response, "404 Not Found", _simple_page("Not found", "<div class=shell><h1>Action not found</h1><p class=lead><a href=\"/app\">Return to the workspace</a></p></div>"))
                    child = repository.create_document(TENANT_ID, _next_version_name(document["filename"]), "synthetic_remediated_copy", fixed, parent_document_id=document_id)
                    repository.record_remediation(child["id"], document_id, kind, provenance)
                    job_id = repository.enqueue(child["id"], kind="recheck")
                    repository.audit(TENANT_ID, actor, "remediation_applied", child["id"], {"parent": document_id, "kind": kind, "job_id": job_id, "provenance": provenance})
                    return _redirect(start_response, f"/documents/{child['id']}")
                except json.JSONDecodeError:
                    message = "The confirmed structure could not be read. Use the role menus on the document page, then try again."
                except RemediationError as error:
                    message = str(error)
                except ValueError:
                    message = "Something in this request could not be read. Return to the document and try again."
                return _response(start_response, "400 Bad Request", _simple_page("Repair needs a closer look", f"<div class=shell><section class=locked><h2>This change was not applied.</h2><p>{escape(message)}</p><p><a href=\"/documents/{escape(document_id)}\">Return to the document</a></p></section></div>"))
        return _response(start_response, "404 Not Found", _simple_page("Not found", "<div class=shell><h1>Page not found</h1><p class=lead><a href=\"/app\">Return to the workspace</a></p></div>"))
    return app
