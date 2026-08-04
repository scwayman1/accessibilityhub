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
from service.repository import StagingRepository
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
SOURCE_LABELS = {"bundled_synthetic_fixture": "Supplied sample", "synthetic_remediated_copy": "Improved copy"}
REMEDIATION_LABELS = {"metadata": "Title & language", "structure": "Tag structure", "ocr": "Text layer (OCR)"}
STRUCTURE_ROLES = (("h1", "Heading level 1"), ("h2", "Heading level 2"), ("h3", "Heading level 3"), ("p", "Paragraph"), ("li", "List item"))
MAX_FORM_BLOCKS = 80

_VERSION_PATTERN = re.compile(r"^(?P<base>.+)\.v(?P<version>\d+)$")

_FALLBACK_FAVICON = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    b'<rect width="64" height="64" rx="14" fill="#003764"/>'
    b'<path d="M17 34 L28 45 L47 21" fill="none" stroke="#6bc4e8" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/></svg>'
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


def _workflow_rail(current: str) -> str:
    current_index = next((index for index, (key, _, _) in enumerate(WORKFLOW_STEPS) if key == current), 0)
    items = []
    for index, (key, number, label) in enumerate(WORKFLOW_STEPS):
        state = "current" if key == current else ("complete" if index < current_index else "upcoming")
        marker = "✓" if state == "complete" else number
        aria = ' aria-current="step"' if state == "current" else ""
        items.append(f'<li class="{state}"{aria}><span class=step-number aria-hidden=true>{marker}</span><span>{label}</span></li>')
    return f'<nav class=workflow-rail aria-label="Review workflow"><p class=nav-label>Review workflow</p><ol>{"".join(items)}</ol></nav>'


def _app_shell(current: str, content: str, signed_in: bool = False) -> str:
    signout = '<form class=signout method=post action="/logout"><button>Sign out</button></form>' if signed_in else ""
    return f'''<a class=skip-link href="#main-content">Skip to main content</a><div class=app-shell>
    <aside class=sidebar><a class=brand href="/app"><img src="/assets/coastline-college-logo-white.png" alt="Coastline College"></a>
    <div class=product-lockup><span>Accessibility Hub</span><strong>Staging workspace</strong></div>
    {_workflow_rail(current)}
    {signout}
    <div class=sidebar-note><span class=status-dot aria-hidden=true></span><div><strong>Synthetic demo only</strong><p>Real-document upload is unavailable.</p></div></div></aside>
    <main id=main-content class=main-workspace tabindex="-1">{content}</main></div>'''


def _html_page(title: str, body: str, head: str = "") -> bytes:
    css = """
    :root { --navy:#003764; --navy-deep:#002a4d; --sky:#6bc4e8; --ink:#102a3a; --muted:#5a6f7c; --canvas:#f5f8fb; --surface:#fff; --line:#dbe5ec; --line-strong:#c7d5df; --cyan:#3cb4e5; --cyan-soft:#eaf7fc; --teal:#005f7a; --copper:#af7653; --success:#18794e; --success-soft:#eaf7f0; --attention:#9c3d23; --attention-soft:#fff1ec; --shadow:0 12px 32px rgba(0,55,100,.08); }
    * { box-sizing:border-box } html { background:var(--canvas) } body { margin:0; color:var(--ink); background:var(--canvas); font:16px/1.55 Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; } a { color:inherit } button,input,textarea,select { font:inherit } :focus-visible { outline:0; box-shadow:0 0 0 2px #fff,0 0 0 5px var(--teal) } .skip-link { position:fixed; z-index:50; top:10px; left:10px; padding:10px 14px; color:white; background:var(--teal); transform:translateY(-160%); } .skip-link:focus { transform:none; }
    h1,h2,h3 { margin:0; color:var(--ink); letter-spacing:-.025em; overflow-wrap:anywhere } h1 { max-width:760px; font-size:clamp(32px,4vw,52px); line-height:1.05; font-weight:760 } h2 { font-size:24px; line-height:1.15 } h3 { font-size:16px; line-height:1.25 } p { margin:0; overflow-wrap:anywhere } .eyebrow { margin:0 0 8px; color:var(--teal); font-size:11px; font-weight:850; letter-spacing:.14em; text-transform:uppercase; } .lead { max-width:690px; margin-top:14px; color:var(--muted); font-size:17px; } .small { color:var(--muted); font-size:12px; }
    header { background:var(--navy); color:white; border-bottom:3px solid var(--sky); } .shell { width:min(1240px,calc(100% - 48px)); margin:auto; } header nav { min-height:72px; display:flex; align-items:center; justify-content:space-between; gap:24px; } .brand-top { display:flex; align-items:center; gap:14px; text-decoration:none; } .brand-top img { display:block; width:188px; height:auto; } .nav-note { color:#d8edf5; font-size:11px; font-weight:800; letter-spacing:.13em; text-transform:uppercase; }
    .app-shell { min-height:100vh; display:grid; grid-template-columns:248px minmax(0,1fr) } .sidebar { position:sticky; top:0; min-width:0; height:100vh; display:flex; flex-direction:column; padding:28px 20px 20px; color:white; background:var(--navy); overflow:auto } .brand { display:block; width:176px; max-width:100%; line-height:0 } .brand img { display:block; width:100%; height:auto } .product-lockup { margin:27px 8px 22px; padding-top:20px; border-top:1px solid rgba(255,255,255,.18) } .product-lockup span,.product-lockup strong { display:block } .product-lockup span { color:#b8e6f7; font-size:11px; font-weight:800; letter-spacing:.14em; text-transform:uppercase } .product-lockup strong { margin-top:3px; color:white; font-size:18px }
    .workflow-rail { min-height:0 } .nav-label { margin:0 10px 8px; color:#9ec6d8; font-size:10px; font-weight:800; letter-spacing:.12em; text-transform:uppercase } .workflow-rail ol { display:grid; gap:4px; margin:0; padding:0; list-style:none } .workflow-rail li { position:relative; display:flex; align-items:center; gap:11px; min-height:46px; padding:8px 10px; color:#b9cfda; border-radius:8px; font-size:13px; font-weight:700 } .workflow-rail li.current { color:white; background:rgba(255,255,255,.1) } .workflow-rail li.current:before { content:""; position:absolute; left:-20px; width:4px; height:26px; border-radius:0 3px 3px 0; background:var(--cyan) } .workflow-rail li.complete { color:#d9edf4 } .step-number { flex:0 0 auto; display:grid; place-items:center; width:24px; height:24px; color:#c7e5f1; border:1px solid #5e8da2; border-radius:7px; font-size:11px } .workflow-rail li.current .step-number { color:var(--navy-deep); border-color:var(--cyan); background:var(--cyan) } .workflow-rail li.complete .step-number { color:white; border-color:#3e8a78; background:#27735f }
    .signout { margin:18px 8px 0 } .signout button { min-height:36px; padding:0 13px; color:#d8edf5; border:1px solid #3a6a94; border-radius:7px; background:transparent; font-size:11px; font-weight:800; letter-spacing:.1em; text-transform:uppercase; cursor:pointer } .signout button:hover { border-color:var(--sky); background:#00274a }
    .sidebar-note { display:flex; gap:10px; align-items:flex-start; margin-top:auto; padding:15px; color:#d8ebf3; border:1px solid rgba(255,255,255,.15); border-radius:10px; background:rgba(0,0,0,.1) } .sidebar-note>div { min-width:0 } .sidebar-note strong { display:block; color:white; font-size:12px } .sidebar-note p { margin-top:2px; color:#bdd3dd; font-size:11px; line-height:1.4 } .status-dot { flex:0 0 auto; width:8px; height:8px; margin-top:5px; border-radius:50%; background:var(--cyan); box-shadow:0 0 0 4px rgba(60,180,229,.16) }
    .main-workspace { min-width:0; padding:36px clamp(22px,4vw,64px) 72px } .workspace-inner { width:min(1120px,100%); margin:0 auto } .page-header { display:flex; justify-content:space-between; align-items:flex-start; gap:24px; margin-bottom:28px } .page-header-copy { min-width:0 } .top-status { display:inline-flex; align-items:center; gap:8px; min-height:30px; padding:5px 10px; color:var(--teal); border:1px solid #b8dce9; border-radius:999px; background:var(--cyan-soft); font-size:11px; font-weight:800; white-space:nowrap }
    .panel { padding:26px; border:1px solid var(--line); border-radius:14px; background:var(--surface); box-shadow:var(--shadow) } .panel p { margin-top:7px; color:var(--muted) } .hero-card { position:relative; overflow:hidden; padding:38px; border-top:4px solid var(--cyan) } .hero-card:after { content:""; position:absolute; right:-72px; bottom:-100px; width:230px; height:230px; border:44px solid var(--cyan-soft); border-radius:50%; opacity:.75 } .hero-copy { position:relative; z-index:1 }
    .actions { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-top:20px } button,.button { max-width:100%; min-height:46px; display:inline-flex; align-items:center; justify-content:center; gap:8px; padding:10px 18px; color:white; border:1px solid var(--teal); border-radius:9px; background:var(--teal); font-weight:800; text-align:center; white-space:normal; text-decoration:none; cursor:pointer; transition:transform .14s ease,box-shadow .14s ease,background .14s ease } button:hover,.button:hover { background:#004c63; box-shadow:0 8px 18px rgba(0,95,122,.18); transform:translateY(-1px) } button.secondary,.button.secondary { color:var(--navy); border-color:#bfd1dc; background:white } button.secondary:hover,.button.secondary:hover { background:#f3f8fb }
    .upload-note { display:flex; gap:10px; align-items:flex-start; margin-top:18px; padding:14px 16px; color:#4e6471; border:1px dashed #b9cbd6; border-radius:10px; background:#f8fafc; font-size:12px } .upload-note strong { color:var(--ink) }
    .section-heading { display:flex; justify-content:space-between; gap:18px; align-items:end; margin:36px 0 14px } .section-heading h2 { font-size:21px } .queue { display:grid; gap:10px; min-width:0; margin:15px 0 0; padding:0; list-style:none } .queue li { min-width:0; padding:13px 16px; border:1px solid var(--line); border-radius:10px; background:white } .queue a { font-weight:800; text-decoration-color:var(--sky); text-decoration-thickness:2px; text-underline-offset:4px } .empty-state { color:var(--muted); border-style:dashed; text-align:center }
    .meta { display:flex; flex-wrap:wrap; gap:8px; margin-top:9px; color:#627985; font-size:12px } .tag { display:inline-flex; align-items:center; padding:4px 8px; color:var(--navy); border:1px solid #bfdbe5; border-radius:999px; background:#eef8fb; font-size:10px; font-weight:850; letter-spacing:.05em; text-transform:uppercase } .mono { font:11px ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:0 }
    .document-layout { display:grid; grid-template-columns:minmax(0,1fr) 360px; gap:20px; align-items:start } .signal { display:grid; grid-template-columns:152px minmax(0,1fr); gap:18px; padding:20px 0; border-bottom:1px solid var(--line) } .signal:last-of-type { border-bottom:0 } .signal-heading { display:flex; align-items:center; gap:9px } .signal-icon { flex:0 0 auto; display:grid; place-items:center; width:25px; height:25px; border:1px solid currentColor; border-radius:8px; font-weight:900; line-height:1 } .chip { display:inline-flex; align-items:center; gap:5px; width:max-content; max-width:100%; padding:5px 8px; border:1px solid currentColor; border-radius:999px; font-size:10px; font-weight:850; letter-spacing:.055em; line-height:1.1; text-transform:uppercase } .needs_attention .chip,.needs_attention .signal-icon { color:var(--attention) } .review_recommended .chip,.review_recommended .signal-icon { color:var(--teal) } .verified_signal .chip,.verified_signal .signal-icon { color:var(--success) } .not_assessed .chip,.not_assessed .signal-icon { color:#60727e } .signal p { margin-top:5px; color:var(--muted); font-size:13px }
    .fixlab { position:sticky; top:24px; padding:24px; border:1px solid #b9dbe7; border-top:4px solid var(--copper); border-radius:14px; background:white; box-shadow:var(--shadow) } .fixlab h2 { font-size:22px } .fixlab p { margin-top:7px; color:var(--muted); font-size:13px } label { display:block; margin:15px 0 6px; color:var(--ink); font-size:13px; font-weight:760 } input,select { width:100%; padding:11px 12px; color:var(--ink); border:1px solid #b9cbd6; border-radius:8px; background:white } input[type=checkbox] { width:auto; margin-right:7px } details { margin-top:12px; padding:13px 14px; border:1px solid var(--line); border-radius:9px; background:#f9fbfc } summary { color:var(--ink); cursor:pointer; font-weight:760 } .advanced { margin-top:18px }
    .completeness { border-style:dashed; background:#f7f9f8 } .completeness ul { margin:8px 0 0; padding-left:19px; color:var(--muted); font-size:12px } .completeness li { margin:4px 0 }
    .block-row { margin:10px 0; padding:9px 11px; border:1px solid var(--line); border-radius:8px; background:#f9fbfc } .block-row label { margin:0 0 4px; font-size:11px; letter-spacing:.09em; text-transform:uppercase } .block-row select { min-height:36px; padding:6px 8px; font-size:13px } .block-preview { display:block; margin-top:5px; color:var(--muted); font-size:12px }
    .progress-card { max-width:760px; margin:34px auto; padding:38px; text-align:center } .progress-orb { position:relative; display:grid; place-items:center; width:72px; height:72px; margin:0 auto 20px; border:8px solid var(--cyan-soft); border-top-color:var(--cyan); border-radius:50%; animation:spin 1.1s linear infinite } .progress-orb:after { content:""; width:26px; height:34px; border:2px solid var(--teal); border-radius:5px; background:white } .progress-list { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin:26px 0 0; padding:0; list-style:none; text-align:left } .progress-list li { padding:13px; color:var(--muted); border:1px solid var(--line); border-radius:9px; background:#f9fbfc; font-size:12px } .progress-list li strong { display:block; color:var(--ink); font-size:13px } .progress-list li.active { border-color:#9cd3e7; background:var(--cyan-soft) }
    .completion { display:flex; gap:14px; align-items:flex-start; margin-bottom:20px; padding:20px 22px; color:#175d40; border:1px solid #a8d7c0; border-radius:13px; background:var(--success-soft) } .completion-mark { flex:0 0 auto; display:grid; place-items:center; width:36px; height:36px; color:white; border-radius:10px; background:var(--success); font-weight:900 } .completion h2 { color:#175d40; font-size:21px } .completion p { margin-top:4px; color:#376e59 }
    .locked { padding:24px; color:#72321e; border-left:4px solid var(--attention); border-radius:8px; background:var(--attention-soft) } .login { width:min(470px,calc(100% - 30px)); margin:56px auto } .login .panel { padding:32px } main.simple { padding:28px 0 72px }
    .eyebrow,.small,.product-lockup span,.nav-label,.workflow-rail li,.step-number,.sidebar-note strong,.sidebar-note p,.top-status,.upload-note,.meta,.tag,.chip,.signal p,.fixlab p,label,.completeness,.block-preview,.progress-list li,.progress-list li strong,.mono,.nav-note { font-size:14px }
    @keyframes spin { to { transform:rotate(360deg) } }
    @media(max-width:900px) { .app-shell { grid-template-columns:1fr } .sidebar { position:static; width:100%; height:auto; padding:18px 20px; overflow-x:hidden } .brand { width:150px } .product-lockup { display:none } .workflow-rail { width:100%; max-width:100%; margin-top:18px; overflow-x:auto } .workflow-rail .nav-label { display:none } .workflow-rail ol { display:flex; min-width:max-content } .workflow-rail li { min-height:42px; padding:7px 10px } .workflow-rail li.current:before { left:10px; right:10px; bottom:-1px; width:auto; height:3px; border-radius:3px 3px 0 0 } .sidebar-note { margin-top:14px; padding:10px 12px } .signout { margin:14px 0 0 } .main-workspace { padding-top:26px } .document-layout { grid-template-columns:1fr } .fixlab { position:static } .brand-top img { width:160px } .nav-note { display:none } }
    @media(max-width:680px) { .main-workspace { padding:22px 15px 56px } .page-header { display:block } .top-status { margin-top:14px; white-space:normal } .hero-card { padding:26px 22px } .panel { padding:21px } .section-heading { align-items:start; flex-direction:column } .signal { grid-template-columns:1fr; gap:9px } .progress-card { padding:28px 20px } .progress-list { grid-template-columns:1fr } }
    @media(prefers-reduced-motion:reduce) { *,*:before,*:after { scroll-behavior:auto!important; animation-duration:.01ms!important; animation-iteration-count:1!important; transition-duration:.01ms!important } }
    """
    icon = "<link rel=\"icon\" href=\"/assets/favicon.svg\" type=\"image/svg+xml\">"
    return f"""<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><meta name=\"theme-color\" content=\"#003764\"><title>{escape(title)}</title>{icon}{head}<style>{css}</style></head><body>{body}</body></html>""".encode()


def _simple_page(title: str, inner: str) -> bytes:
    """A plain navy-header page for login, lock-outs, and error surfaces."""
    header = '<header><div class=shell><nav><a class=brand-top href="/app"><img src="/assets/coastline-college-logo-white.png" alt="Coastline College"></a><span class=nav-note>Accessibility Hub</span></nav></div></header>'
    return _html_page(title, f"{header}<main class=simple>{inner}</main>")


def _session_token(settings: ServiceSettings) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"actor": ACTOR_ID, "tenant": TENANT_ID, "exp": int(time.time()) + 28800}).encode()).decode().rstrip("=")
    signature = hmac.new((settings.session_secret or "").encode(), payload.encode(), sha256).hexdigest()
    return f"{payload}.{signature}"


def _authenticated(environ: dict[str, Any], settings: ServiceSettings) -> bool:
    if not settings.login_ready:
        return False
    cookies = {part.split("=", 1)[0].strip(): part.split("=", 1)[1] for part in environ.get("HTTP_COOKIE", "").split(";") if "=" in part}
    token = cookies.get("hub_session", "")
    try:
        payload, signature = token.rsplit(".", 1)
        expected = hmac.new((settings.session_secret or "").encode(), payload.encode(), sha256).hexdigest()
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return hmac.compare_digest(signature, expected) and data.get("tenant") == TENANT_ID and int(data["exp"]) > time.time()
    except Exception:
        return False


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
                return _response(start_response, "200 OK", _simple_page("Sign in — Accessibility Hub", f"<div class=login><section class=panel><p class=eyebrow>Access</p><h2>Enter the staging workspace</h2>{note}<p>Enter your access code to continue.</p><form method=post><label for=code>Access code</label><input id=code name=code type=password autocomplete=current-password required><div class=actions><button>Continue</button></div></form></section></div>"))
            return _response(start_response, "503 Service Unavailable", _simple_page("Access setup required", "<div class=login><section class=locked><h2>Access setup is incomplete</h2><p>This service remains closed until a staging access code and session secret are configured.</p></section></div>"))
        if path == "/login" and method == "POST":
            code = _form(environ).get("code", "")
            if settings.login_ready and hmac.compare_digest(code, settings.access_code or ""):
                cookie = f"hub_session={_session_token(settings)}; HttpOnly; SameSite=Lax; Path=/" + ("; Secure" if settings.environment == "staging" else "")
                return _redirect(start_response, "/app", [("Set-Cookie", cookie)])
            return _response(start_response, "401 Unauthorized", _simple_page("Sign in — Accessibility Hub", "<div class=login><section class=locked><h2>That code did not open the workspace.</h2><p><a href=\"/login\">Try again</a></p></section></div>"))
        signed_in = _authenticated(environ, settings)
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
            rows = rows or "<li class=empty-state>No sample review has started yet. Begin with the course handout above.</li>"
            if settings.synthetic_intake_ready:
                primary_action = '<form method=post action="/documents/synthetic"><button name=fixture value=handout>Start a sample review <span aria-hidden=true>→</span></button></form>'
                secondary_action = '<form method=post action="/documents/synthetic"><button class=secondary name=fixture value=scan>Try the scanned sample</button></form>'
            else:
                primary_action = secondary_action = '<div class=locked><h3>Hosted controls are not connected</h3><p>Private storage, scan gate, isolated worker, tenant authorization, lifecycle, and audit integrations must be configured before a hosted process can begin.</p></div>'
            content = f'''<div class=workspace-inner><header class=page-header><div class=page-header-copy><p class=eyebrow>Accessibility Hub</p><h1>See what to improve. Keep what already works.</h1><p class=lead>Start with a supplied handout, review clear signals, make one intentional change, then verify the new version.</p></div><span class=top-status><span class=status-dot aria-hidden=true></span>Safe sample workspace</span></header>
            <section class="panel hero-card" aria-labelledby=start-heading><div class=hero-copy><p class=eyebrow>1 · Review</p><h2 id=start-heading>Choose a sample</h2><p class=lead>Use the course handout for metadata and structure signals, or the scanned handout to review an OCR text layer.</p><div class=actions>{primary_action}{secondary_action}</div><div class=upload-note><span aria-hidden=true>🔒</span><div><strong>Real-document upload is not available in this environment.</strong><br>Real, institutional, and public uploads are not accepted — only the bundled synthetic samples.</div></div></div></section>
            <section aria-labelledby=recent-heading><div class=section-heading><div><p class=eyebrow>Workspace</p><h2 id=recent-heading>Document records</h2></div><p class=small>One row per document. Improved copies appear as new versions of the same row.</p></div><ul class=queue>{rows}</ul></section></div>'''
            return _response(start_response, "200 OK", _html_page("Accessibility Hub staging", _app_shell("add", content, signed_in)))
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
            repository.audit(TENANT_ID, ACTOR_ID, "synthetic_document_created", item["id"], {"job_id": job_id, "source": item["source_kind"]})
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
                    result_hash = str(detail.get("remediated_sha256") or "").removeprefix("sha256:")[:10]
                    hashes = f" · <span class=mono>{escape(source_hash)}… → {escape(result_hash)}…</span>" if source_hash and result_hash else ""
                    label = REMEDIATION_LABELS.get(row["kind"], row["kind"])
                    provenance_items.append(f"<li><strong>{escape(label)}</strong> <span class=tag>{escape(row['kind'])}</span> · {escape(_when(row['created_at']))}{hashes}</li>")
                provenance = "".join(provenance_items) or "<li>No recheck has been applied to this version.</li>"
                cleanup = f"<details><summary>Remove this synthetic record</summary><p>This removes this version and any rechecked copies from the local staging store.</p><form method=post action=\"/documents/{escape(document_id)}/delete\"><label><input type=checkbox name=confirmed value=yes required> I want to remove these synthetic records.</label><div class=actions><button class=secondary>Remove records</button></div></form></details>"
                if not terminal:
                    current_step = "check" if is_recheck else "review"
                    phase_label = "Checking your improved copy" if is_recheck else "Reviewing the sample"
                    progress = f'''<div class=workspace-inner><header class=page-header><div class=page-header-copy><p class=eyebrow><a href="/app">Workspace</a> / review</p><h1>{escape(phase_label)}</h1><p class=lead>{escape(document['filename'])}</p></div><span class=top-status><span class=status-dot aria-hidden=true></span>In progress</span></header><section class="panel progress-card" role=status aria-live=polite aria-atomic=true><div class=progress-orb aria-hidden=true></div><p class=eyebrow>Deterministic review</p><h2>Looking for useful accessibility signals…</h2><p>This usually takes a few seconds. This page checks again every five seconds.</p><ol class=progress-list><li><strong>Sample prepared</strong>Bundled content only</li><li class=active><strong>Reviewing signals</strong>Metadata, structure, and text</li><li><strong>Building next steps</strong>Plain-language guidance</li></ol><div class=actions><a class="button secondary" href="/documents/{escape(document_id)}">Refresh now</a></div><p class=small>Review first — the Fix Lab opens once this review completes.</p></section></div>'''
                    return _response(start_response, "200 OK", _html_page("Review in progress — Accessibility Hub", _app_shell(current_step, progress, signed_in), refresh_head))
                resolved_count = 0
                if is_recheck and result:
                    parent_job = repository.latest_job(TENANT_ID, document["parent_document_id"])
                    parent_result = (parent_job or {}).get("result") or {}
                    before = {item.get("rule_id"): item.get("lane") for item in parent_result.get("signals", [])}
                    resolved_count = sum(1 for item in result.get("signals", []) if item.get("lane") == "verified_signal" and before.get(item.get("rule_id")) not in {None, "verified_signal"})
                completion = ""
                if is_recheck and job_state == "succeeded":
                    if resolved_count:
                        completion_line = f"{resolved_count} accessibility signal{'s are' if resolved_count != 1 else ' is'} now verified in the recheck. The original sample remains unchanged."
                    else:
                        completion_line = "Compare the lanes with the previous version to see what changed. The original sample remains unchanged."
                    completion = f'''<div class=completion role=status><span class=completion-mark aria-hidden=true>✓</span><div><h2>Your improved copy is ready</h2><p>{completion_line}</p></div></div>'''
                header_title = "Recheck complete" if is_recheck else "Review findings"
                header_lead = "See what changed, then explore the remaining signals." if is_recheck else "Read each signal, decide what to improve, and verify the new version without losing the record of what changed."
                state_label = STATE_LABELS.get(job_state, "Review queued")
                source_label = SOURCE_LABELS.get(document["source_kind"], document["source_kind"])
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
                    fixlab = f'''<aside class=fixlab aria-labelledby=fix-heading><p class=eyebrow>3 · Improve</p><h2 id=fix-heading>Fix the clearest issues</h2><p>Add a meaningful title and primary language, then run the check again on a copy.</p><form method=post action="/documents/{escape(document_id)}/remediate/metadata"><label for=document-title>Document title</label><input id=document-title name=title value="Week 3 Course Handout" required><label for=document-language>Primary language</label><input id=document-language name=language value="en-US" required><div class=actions><button>Apply and recheck <span aria-hidden=true>→</span></button></div></form><div class=advanced>{_structure_fix(document_id, blocks)}{ocr_action}{cleanup}</div><p class=small>Each recheck creates a new version and keeps the source record intact.</p></aside>'''
                else:
                    parent_link = f'<a class="button secondary" href="/documents/{escape(document["parent_document_id"])}">View original sample</a>' if is_recheck else '<a class="button secondary" href="/app">Start another sample</a>'
                    fixlab = f'''<aside class=fixlab><p class=eyebrow>Next step</p><h2>{'Compare the result' if is_recheck else 'Try another sample'}</h2><p>{'The rechecked copy is stored as a separate version of the same lineage.' if is_recheck else 'This assessment did not complete, so no fixes were applied.'}</p><div class=actions>{parent_link}<a class="button secondary" href="/app">Workspace</a></div><div class=advanced>{cleanup}</div></aside>'''
                content = f'''<div class=workspace-inner><header class=page-header><div class=page-header-copy><p class=eyebrow><a href="/app">Workspace</a> / {escape('recheck' if is_recheck else 'document')}</p><h1>{header_title}</h1><p class=lead>{header_lead}</p><div class=meta><span class=tag>{escape(source_label)}</span><span class=tag>{escape(state_label)}</span><span>{escape(document['filename'])}</span><span class=mono>{escape(document['sha256'][:16])}…</span></div></div><span class=top-status><span class=status-dot aria-hidden=true></span>Synthetic demo only</span></header>{completion}<div class=document-layout>{findings}{fixlab}</div></div>'''
                return _response(start_response, "200 OK", _html_page("Document review — Accessibility Hub", _app_shell("check" if is_recheck else "improve", content, signed_in), refresh_head))
            if len(pieces) == 3 and pieces[2] == "delete" and method == "POST":
                if _form(environ).get("confirmed") != "yes":
                    return _response(start_response, "400 Bad Request", _simple_page("Removal needs confirmation", f"<div class=shell><section class=locked><h2>This record is still here.</h2><p><a href=\"/documents/{escape(document_id)}\">Return to the document</a></p></section></div>"))
                deleted = repository.delete_document_lineage(TENANT_ID, document_id)
                repository.audit(TENANT_ID, ACTOR_ID, "synthetic_document_deleted", document_id, {"deleted_document_count": deleted})
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
                    repository.audit(TENANT_ID, ACTOR_ID, "remediation_applied", child["id"], {"parent": document_id, "kind": kind, "job_id": job_id, "provenance": provenance})
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
