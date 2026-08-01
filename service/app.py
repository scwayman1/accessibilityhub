"""WSGI control plane for the private, synthetic-only Accessibility Hub staging slice."""
from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import time
from hashlib import sha256
from html import escape
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

from tina.remedy import MetadataRemediation, RemediationError
from tina.ocr import OcrRemediation
from tina.structure import StructureRemediation

from service.fixtures import synthetic_handout_pdf, synthetic_scan_pdf
from service.repository import StagingRepository
from service.settings import ServiceSettings
from service.worker import AssessmentWorker

TENANT_ID = "coastline-staging"
ACTOR_ID = "staging-educator"
WORKFLOW_STEPS = (("add", "1", "Review"), ("review", "2", "Understand"), ("improve", "3", "Improve"), ("check", "4", "Verify"))
LANE_PRESENTATION = {
    "needs_attention": ("!", "Needs attention"),
    "review_recommended": ("?", "Review recommended"),
    "verified_signal": ("✓", "Verified signal"),
    "not_assessed": ("–", "Not assessed"),
}
SIGNAL_TITLES = {
    "Metadata.Title": "Document title",
    "Metadata.Language": "Document language",
    "Structure.Semantics": "Document structure",
    "Intake.Qpdf Check": "File integrity",
    "Veraunavailable": "PDF/UA validation",
}


def _workflow_rail(current: str) -> str:
    current_index = next((index for index, (key, _, _) in enumerate(WORKFLOW_STEPS) if key == current), 0)
    items = []
    for index, (key, number, label) in enumerate(WORKFLOW_STEPS):
        state = "current" if key == current else ("complete" if index < current_index else "upcoming")
        marker = "✓" if state == "complete" else number
        aria = ' aria-current="step"' if state == "current" else ""
        items.append(f'<li class="{state}"{aria}><span class=step-number aria-hidden=true>{marker}</span><span>{label}</span></li>')
    return f'<nav class=workflow-rail aria-label="Review workflow"><p class=nav-label>Review workflow</p><ol>{"".join(items)}</ol></nav>'


def _app_shell(current: str, content: str) -> str:
    return f'''<a class=skip-link href="#main-content">Skip to main content</a><div class=app-shell>
    <aside class=sidebar><a class=brand href="/app"><img src="/assets/coastline-college-logo-white.png" alt="Coastline College"></a>
    <div class=product-lockup><span>Accessibility Hub</span><strong>Demo workspace</strong></div>
    {_workflow_rail(current)}
    <div class=sidebar-note><span class=status-dot aria-hidden=true></span><div><strong>Synthetic demo only</strong><p>Real-document upload is unavailable.</p></div></div></aside>
    <main id=main-content class=main-workspace tabindex="-1">{content}</main></div>'''


def _html_page(title: str, body: str, head: str = "") -> bytes:
    css = """
    :root { --navy:#003764; --navy-deep:#002a4d; --ink:#102a3a; --muted:#5a6f7c; --canvas:#f5f8fb; --surface:#fff; --line:#dbe5ec; --line-strong:#c7d5df; --cyan:#3cb4e5; --cyan-soft:#eaf7fc; --teal:#005f7a; --success:#18794e; --success-soft:#eaf7f0; --attention:#9c3d23; --attention-soft:#fff1ec; --warning:#8a5a00; --shadow:0 12px 32px rgba(0,55,100,.08); }
    * { box-sizing:border-box } html { background:var(--canvas) } body { margin:0; color:var(--ink); background:var(--canvas); font:16px/1.55 Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; } a { color:inherit } button,input,textarea { font:inherit } :focus-visible { outline:0; box-shadow:0 0 0 2px #fff,0 0 0 5px var(--teal) } .skip-link { position:fixed; z-index:50; top:10px; left:10px; padding:10px 14px; color:white; background:var(--teal); transform:translateY(-160%); } .skip-link:focus { transform:none; }
    h1,h2,h3 { margin:0; color:var(--ink); letter-spacing:-.025em; overflow-wrap:anywhere } h1 { max-width:760px; font-size:clamp(34px,4.2vw,56px); line-height:1.05; font-weight:760 } h2 { font-size:24px; line-height:1.15 } h3 { font-size:16px; line-height:1.25 } p { margin:0; overflow-wrap:anywhere } .eyebrow { margin:0 0 8px; color:var(--teal); font-size:11px; font-weight:850; letter-spacing:.14em; text-transform:uppercase; } .lead { max-width:690px; margin-top:14px; color:var(--muted); font-size:17px; } .small { color:var(--muted); font-size:12px; }
    .app-shell { min-height:100vh; display:grid; grid-template-columns:248px minmax(0,1fr) } .sidebar { position:sticky; top:0; min-width:0; height:100vh; display:flex; flex-direction:column; padding:28px 20px 20px; color:white; background:var(--navy); overflow:auto } .brand { display:block; width:176px; max-width:100%; line-height:0 } .brand img { display:block; width:100%; height:auto } .product-lockup { margin:27px 8px 22px; padding-top:20px; border-top:1px solid rgba(255,255,255,.18) } .product-lockup span,.product-lockup strong { display:block } .product-lockup span { color:#b8e6f7; font-size:11px; font-weight:800; letter-spacing:.14em; text-transform:uppercase } .product-lockup strong { margin-top:3px; color:white; font-size:18px }
    .workflow-rail { min-height:0 } .nav-label { margin:0 10px 8px; color:#9ec6d8; font-size:10px; font-weight:800; letter-spacing:.12em; text-transform:uppercase } .workflow-rail ol { display:grid; gap:4px; margin:0; padding:0; list-style:none } .workflow-rail li { position:relative; display:flex; align-items:center; gap:11px; min-height:46px; padding:8px 10px; color:#b9cfda; border-radius:8px; font-size:13px; font-weight:700 } .workflow-rail li.current { color:white; background:rgba(255,255,255,.1) } .workflow-rail li.current:before { content:""; position:absolute; left:-20px; width:4px; height:26px; border-radius:0 3px 3px 0; background:var(--cyan) } .workflow-rail li.complete { color:#d9edf4 } .step-number { flex:0 0 auto; display:grid; place-items:center; width:24px; height:24px; color:#c7e5f1; border:1px solid #5e8da2; border-radius:7px; font-size:11px } .workflow-rail li.current .step-number { color:var(--navy-deep); border-color:var(--cyan); background:var(--cyan) } .workflow-rail li.complete .step-number { color:white; border-color:#3e8a78; background:#27735f }
    .sidebar-note { display:flex; gap:10px; align-items:flex-start; margin-top:auto; padding:15px; color:#d8ebf3; border:1px solid rgba(255,255,255,.15); border-radius:10px; background:rgba(0,0,0,.1) } .sidebar-note>div { min-width:0 } .sidebar-note strong { display:block; color:white; font-size:12px } .sidebar-note p { margin-top:2px; color:#bdd3dd; font-size:11px; line-height:1.4 } .status-dot { flex:0 0 auto; width:8px; height:8px; margin-top:5px; border-radius:50%; background:var(--cyan); box-shadow:0 0 0 4px rgba(60,180,229,.16) }
    .main-workspace { min-width:0; padding:36px clamp(22px,4vw,64px) 72px } .workspace-inner { width:min(1120px,100%); margin:0 auto } .page-header { display:flex; justify-content:space-between; align-items:flex-start; gap:24px; margin-bottom:28px } .page-header-copy { min-width:0 } .top-status { display:inline-flex; align-items:center; gap:8px; min-height:30px; padding:5px 10px; color:var(--teal); border:1px solid #b8dce9; border-radius:999px; background:var(--cyan-soft); font-size:11px; font-weight:800; white-space:nowrap }
    .panel { padding:26px; border:1px solid var(--line); border-radius:14px; background:var(--surface); box-shadow:var(--shadow) } .panel.flat { box-shadow:none } .panel p { margin-top:7px; color:var(--muted) } .hero-card { position:relative; overflow:hidden; display:grid; grid-template-columns:minmax(0,1.3fr) minmax(260px,.7fr); gap:34px; align-items:center; padding:38px; border-top:4px solid var(--cyan) } .hero-card:after { content:""; position:absolute; right:-72px; bottom:-100px; width:230px; height:230px; border:44px solid var(--cyan-soft); border-radius:50%; opacity:.75 } .hero-copy,.sample-visual { position:relative; z-index:1 } .hero-card h1 { font-size:clamp(35px,4vw,52px) } .sample-visual { min-height:210px; display:grid; place-items:center } .paper-stack { position:relative; width:180px; height:196px } .paper { position:absolute; inset:0; padding:26px 22px; border:1px solid var(--line-strong); border-radius:10px; background:white; box-shadow:0 18px 36px rgba(0,55,100,.12); transform:rotate(3deg) } .paper:before,.paper:after { content:""; display:block; height:8px; margin-bottom:13px; border-radius:3px; background:#dce8ee } .paper:before { width:72%; background:var(--navy) } .paper:after { width:88% } .paper-lines { display:grid; gap:10px; margin-top:26px } .paper-lines span { display:block; height:6px; border-radius:3px; background:#e6eef3 } .paper-lines span:nth-child(2) { width:76% } .paper-lines span:nth-child(3) { width:89% } .paper-check { position:absolute; right:-14px; bottom:18px; display:grid; place-items:center; width:50px; height:50px; color:white; border:5px solid white; border-radius:50%; background:var(--success); box-shadow:0 8px 20px rgba(24,121,78,.25); font-size:22px; font-weight:900 }
    .actions { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-top:20px } button,.button { max-width:100%; min-height:46px; display:inline-flex; align-items:center; justify-content:center; gap:8px; padding:10px 18px; color:white; border:1px solid var(--teal); border-radius:9px; background:var(--teal); font-weight:800; text-align:center; white-space:normal; text-decoration:none; cursor:pointer; transition:transform .14s ease,box-shadow .14s ease,background .14s ease } button:hover,.button:hover { background:#004c63; box-shadow:0 8px 18px rgba(0,95,122,.18); transform:translateY(-1px) } button.secondary,.button.secondary { color:var(--navy); border-color:#bfd1dc; background:white } button.secondary:hover,.button.secondary:hover { background:#f3f8fb } button.tertiary { min-height:40px; padding:0 12px; color:var(--teal); border-color:transparent; background:transparent } button.tertiary:hover { background:var(--cyan-soft); box-shadow:none } button[disabled] { color:#71828d; border-color:#dbe4e9; background:#edf2f5; cursor:not-allowed; transform:none; box-shadow:none }
    .choice-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; margin-top:22px } .sample-card { padding:22px 24px; border:1px solid var(--line); border-radius:14px; background:white; box-shadow:0 8px 24px rgba(0,55,100,.05) } .sample-card-head { display:flex; gap:14px; align-items:flex-start } .sample-icon { flex:0 0 auto; display:grid; place-items:center; width:44px; height:44px; color:var(--teal); border-radius:10px; background:var(--cyan-soft); font-size:20px; font-weight:900 } .sample-card h2 { font-size:20px } .sample-card p { margin-top:6px; color:var(--muted); font-size:13px } .sample-card form { margin-top:18px } .upload-note { display:flex; gap:10px; align-items:flex-start; margin-top:18px; padding:14px 16px; color:#4e6471; border:1px dashed #b9cbd6; border-radius:10px; background:#f8fafc; font-size:12px } .upload-note strong { color:var(--ink) }
    .section-heading { display:flex; justify-content:space-between; gap:18px; align-items:end; margin:36px 0 14px } .section-heading h2 { font-size:21px } .queue { display:grid; gap:10px; min-width:0; margin:0; padding:0; list-style:none } .queue li { min-width:0; padding:0 } .record-link { min-width:0; display:flex; justify-content:space-between; gap:20px; align-items:center; padding:15px 17px; color:inherit; border:1px solid var(--line); border-radius:10px; background:white; text-decoration:none; transition:border-color .14s ease,transform .14s ease,box-shadow .14s ease } .record-link>div { min-width:0 } .record-link:hover { border-color:#9cccdc; box-shadow:0 8px 20px rgba(0,55,100,.07); transform:translateY(-1px) } .record-link strong { display:block; max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap } .record-link .record-meta { flex:0 0 auto; display:flex; gap:8px; align-items:center } .empty-state { padding:24px; color:var(--muted); border:1px dashed var(--line-strong); border-radius:10px; background:white; text-align:center }
    .meta { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; color:#627985; font-size:12px } .tag { display:inline-flex; align-items:center; padding:4px 8px; color:var(--navy); border:1px solid #bfdbe5; border-radius:999px; background:#eef8fb; font-size:10px; font-weight:850; letter-spacing:.05em; text-transform:uppercase }
    .document-layout { display:grid; grid-template-columns:minmax(0,1fr) 340px; gap:20px; align-items:start } .document-layout.single { grid-template-columns:1fr } .summary-row { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin:18px 0 6px } .summary-stat { padding:13px 14px; border:1px solid var(--line); border-radius:10px; background:#f9fbfc } .summary-stat strong { display:block; font-size:20px } .summary-stat span { color:var(--muted); font-size:11px } .signal { display:grid; grid-template-columns:152px minmax(0,1fr); gap:18px; padding:20px 0; border-bottom:1px solid var(--line) } .signal:last-of-type { border-bottom:0 } .signal-heading { display:flex; align-items:center; gap:9px } .signal-icon { flex:0 0 auto; display:grid; place-items:center; width:25px; height:25px; border:1px solid currentColor; border-radius:8px; font-weight:900; line-height:1 } .chip { display:inline-flex; align-items:center; gap:5px; width:max-content; max-width:100%; padding:5px 8px; border:1px solid currentColor; border-radius:999px; font-size:10px; font-weight:850; letter-spacing:.055em; line-height:1.1; text-transform:uppercase } .needs_attention .chip,.needs_attention .signal-icon { color:var(--attention) } .review_recommended .chip,.review_recommended .signal-icon { color:var(--teal) } .verified_signal .chip,.verified_signal .signal-icon { color:var(--success) } .not_assessed .chip,.not_assessed .signal-icon { color:#60727e } .signal p { margin-top:5px; color:var(--muted); font-size:13px }
    .fixlab { position:sticky; top:24px; padding:24px; border:1px solid #b9dbe7; border-top:4px solid var(--cyan); border-radius:14px; background:white; box-shadow:var(--shadow) } .fixlab h2 { font-size:22px } .fixlab p { margin-top:7px; color:var(--muted); font-size:13px } label { display:block; margin:15px 0 6px; color:var(--ink); font-size:13px; font-weight:760 } input,textarea { width:100%; padding:11px 12px; color:var(--ink); border:1px solid #b9cbd6; border-radius:8px; background:white } input[type=checkbox] { width:auto; margin-right:7px } textarea { min-height:88px; font:12px ui-monospace,SFMono-Regular,Menlo,monospace } details { margin-top:12px; padding:13px 14px; border:1px solid var(--line); border-radius:9px; background:#f9fbfc } summary { color:var(--ink); cursor:pointer; font-weight:760 } .advanced { margin-top:18px }
    .progress-card { max-width:760px; margin:34px auto; padding:38px; text-align:center } .progress-orb { position:relative; display:grid; place-items:center; width:72px; height:72px; margin:0 auto 20px; border:8px solid var(--cyan-soft); border-top-color:var(--cyan); border-radius:50%; animation:spin 1.1s linear infinite } .progress-orb:after { content:""; width:26px; height:34px; border:2px solid var(--teal); border-radius:5px; background:white } .progress-list { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin:26px 0 0; padding:0; list-style:none; text-align:left } .progress-list li { padding:13px; color:var(--muted); border:1px solid var(--line); border-radius:9px; background:#f9fbfc; font-size:12px } .progress-list li strong { display:block; color:var(--ink); font-size:13px } .progress-list li.active { border-color:#9cd3e7; background:var(--cyan-soft) } .completion { display:flex; gap:14px; align-items:flex-start; margin-bottom:20px; padding:20px 22px; color:#175d40; border:1px solid #a8d7c0; border-radius:13px; background:var(--success-soft) } .completion-mark { flex:0 0 auto; display:grid; place-items:center; width:36px; height:36px; color:white; border-radius:10px; background:var(--success); font-weight:900 } .completion h2 { color:#175d40; font-size:21px } .completion p { margin-top:4px; color:#376e59 } .locked { padding:24px; color:#72321e; border-left:4px solid var(--attention); border-radius:8px; background:var(--attention-soft) } .login { width:min(470px,calc(100% - 30px)); margin:56px auto } .login .panel { padding:32px }
    .eyebrow,.small,.product-lockup span,.nav-label,.workflow-rail li,.step-number,.sidebar-note strong,.sidebar-note p,.top-status,.sample-card p,.upload-note,.meta,.tag,.summary-stat span,.chip,.signal p,.fixlab p,label,textarea,.progress-list li,.progress-list li strong { font-size:14px }
    @keyframes spin { to { transform:rotate(360deg) } }
    @media(max-width:900px) { .app-shell { grid-template-columns:1fr } .sidebar { position:static; width:100%; height:auto; padding:18px 20px; overflow-x:hidden } .brand { width:150px } .product-lockup { display:none } .workflow-rail { width:100%; max-width:100%; margin-top:18px; overflow-x:auto } .workflow-rail .nav-label { display:none } .workflow-rail ol { display:flex; min-width:max-content } .workflow-rail li { min-height:42px; padding:7px 10px } .workflow-rail li.current:before { left:10px; right:10px; bottom:-1px; width:auto; height:3px; border-radius:3px 3px 0 0 } .sidebar-note { margin-top:14px; padding:10px 12px } .main-workspace { padding-top:26px } .document-layout { grid-template-columns:1fr } .fixlab { position:static } }
    @media(max-width:680px) { .main-workspace { padding:22px 15px 56px } .page-header { display:block } .top-status { margin-top:14px; white-space:normal } .hero-card { grid-template-columns:1fr; padding:26px 22px } .sample-visual { display:none } .choice-grid { grid-template-columns:1fr } .panel,.sample-card { padding:21px } .section-heading { align-items:start; flex-direction:column } .record-link { align-items:flex-start; flex-direction:column; overflow:hidden } .record-link>div,.record-link strong { width:100%; max-width:100% } .record-link .record-meta { width:100%; justify-content:space-between } .summary-row { grid-template-columns:1fr } .signal { grid-template-columns:1fr; gap:9px } .progress-card { padding:28px 20px } .progress-list { grid-template-columns:1fr } }
    @media(prefers-reduced-motion:reduce) { *,*:before,*:after { scroll-behavior:auto!important; animation-duration:.01ms!important; animation-iteration-count:1!important; transition-duration:.01ms!important } }
    """
    return f"""<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><meta name=\"theme-color\" content=\"#003764\"><title>{escape(title)}</title>{head}<style>{css}</style></head><body>{body}</body></html>""".encode()


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


def _signals(result: dict[str, Any] | None, job_state: str = "queued") -> str:
    if not result:
        if job_state == "failed":
            return "<p class=\"small\">This assessment did not complete, so no signals are shown. The document record is unchanged. Remove this record and start a new synthetic review, or check the service logs for the recorded error code.</p>"
        return "<p class=\"small\">Assessment is queued. This page refreshes automatically while it runs.</p>"
    cards: list[tuple[str, str]] = []
    lane_order = {"needs_attention": 0, "review_recommended": 1, "verified_signal": 2, "not_assessed": 3}
    for signal in sorted(result.get("signals", []), key=lambda item: lane_order.get(item.get("lane"), 4)):
        lane = signal["lane"]
        icon, label = LANE_PRESENTATION.get(lane, LANE_PRESENTATION["not_assessed"])
        context = " <span class=tag>educator context</span>" if signal.get("educator_context") else ""
        title = SIGNAL_TITLES.get(signal.get("title", ""), signal.get("title", "Accessibility signal"))
        card = f"<article class=\"signal {escape(lane)}\"><div><span class=\"chip\"><span aria-hidden=true>{icon}</span>{escape(label)}</span></div><div><div class=signal-heading><span class=signal-icon aria-hidden=true>{icon}</span><h3>{escape(title)}</h3></div><p>{escape(signal.get('evidence') or '')}</p><p><strong>Next:</strong> {escape(signal.get('next_action') or '')}{context}</p></div></article>"
        cards.append((lane, card))
    primary = "".join(card for lane, card in cards if lane != "not_assessed")
    deferred = [card for lane, card in cards if lane == "not_assessed"]
    deferred_html = f'<details class=advanced><summary>{len(deferred)} checks need specialist review</summary>{"".join(deferred)}</details>' if deferred else ""
    return primary + deferred_html + "<p class=small>Each signal stands on its own. This demo does not create an overall score or certification.</p>"


def _signal_summary(result: dict[str, Any] | None) -> str:
    signals = result.get("signals", []) if result else []
    counts = {lane: sum(1 for item in signals if item.get("lane") == lane) for lane in LANE_PRESENTATION}
    return f'''<div class=summary-row aria-label="Finding summary">
    <div class=summary-stat><strong>{counts['needs_attention']}</strong><span>Needs attention</span></div>
    <div class=summary-stat><strong>{counts['review_recommended']}</strong><span>Review recommended</span></div>
    <div class=summary-stat><strong>{counts['verified_signal']}</strong><span>Verified signals</span></div></div>'''


def create_app(settings: ServiceSettings | None = None, repository: StagingRepository | None = None, worker: AssessmentWorker | None = None):
    settings = settings or ServiceSettings.from_environ()
    repository = repository or StagingRepository(settings.data_dir)
    worker = worker or AssessmentWorker(repository)
    worker.start()

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
        if path == "/healthz":
            payload = json.dumps(settings.health_payload()).encode()
            start_response("200 OK", [("Content-Type", "application/json"), ("Content-Length", str(len(payload))), ("Cache-Control", "no-store")])
            return [payload]
        if path == "/login" and method == "GET":
            if settings.login_ready:
                return _response(start_response, "200 OK", _html_page("Sign in — Accessibility Hub", "<main><div class=login><section class=panel><p class=eyebrow>Access</p><h2>Enter the staging workspace</h2><p>Enter your access code to continue.</p><form method=post><label for=code>Access code</label><input id=code name=code type=password autocomplete=current-password required><div class=actions><button>Continue</button></div></form></section></div></main>"))
            return _response(start_response, "503 Service Unavailable", _html_page("Access setup required", "<main><div class=login><section class=locked><h2>Access setup is incomplete</h2><p>This service remains closed until a staging access code and session secret are configured.</p></section></div></main>"))
        if path == "/login" and method == "POST":
            code = _form(environ).get("code", "")
            if settings.login_ready and hmac.compare_digest(code, settings.access_code or ""):
                cookie = f"hub_session={_session_token(settings)}; HttpOnly; SameSite=Lax; Path=/" + ("; Secure" if settings.environment == "staging" else "")
                return _redirect(start_response, "/app", [("Set-Cookie", cookie)])
            return _response(start_response, "401 Unauthorized", _html_page("Sign in — Accessibility Hub", "<main><div class=login><section class=locked><h2>That code did not open the workspace.</h2><p><a href=\"/login\">Try again</a></p></section></div></main>"))
        if not settings.public_access and not _authenticated(environ, settings):
            return _redirect(start_response, "/login")
        if path in {"/", "/app"} and method == "GET":
            documents = repository.list_documents(TENANT_ID)
            rows = "".join(
                f'''<li><a class=record-link href="/documents/{escape(d['id'])}"><div><strong>{escape(d['filename'])}</strong><span class=small>{'Rechecked sample' if d.get('parent_document_id') else 'Bundled sample document'}</span></div><span class=record-meta><span class=tag>{escape(d.get('job_state') or 'queued')}</span><span class=small>{escape(d['created_at'][:10])}</span></span></a></li>'''
                for d in documents[:6]
            ) or '<li class=empty-state>No sample reviews yet. Start with the course handout above.</li>'
            if settings.synthetic_intake_ready:
                primary_action = '<form method=post action="/documents/synthetic"><button name=fixture value=handout>Start a sample review <span aria-hidden=true>→</span></button></form>'
                secondary_action = '<form method=post action="/documents/synthetic"><button class=secondary name=fixture value=scan>Try the scanned sample</button></form>'
            else:
                primary_action = secondary_action = '<div class=locked><h3>Demo samples are temporarily unavailable</h3><p>The required hosted demo controls have not been enabled.</p></div>'
            content = f'''<div class=workspace-inner><header class=page-header><div class=page-header-copy><p class=eyebrow>Accessibility Hub</p><h1>Make every document easier to use.</h1><p class=lead>Choose a bundled sample, review clear accessibility findings, make one improvement, and see the recheck.</p></div><span class=top-status><span class=status-dot aria-hidden=true></span>Safe sample workspace</span></header>
            <section class="panel hero-card" aria-labelledby=start-heading><div class=hero-copy><p class=eyebrow>Start here</p><h2 id=start-heading>Review a sample course handout</h2><p class=lead>We will run a deterministic accessibility check and turn the results into plain-language next steps.</p><div class=actions>{primary_action}</div><div class=upload-note><span aria-hidden=true>🔒</span><div><strong>Private document upload is not available yet.</strong><br>Today’s demo uses generated sample content only—never institutional or personal documents.</div></div></div><div class=sample-visual aria-hidden=true><div class=paper-stack><div class=paper><div class=paper-lines><span></span><span></span><span></span></div></div><span class=paper-check>✓</span></div></div></section>
            <div class=choice-grid><section class=sample-card><div class=sample-card-head><span class=sample-icon aria-hidden=true>⌁</span><div><p class=eyebrow>Alternate sample</p><h2>Try a scanned handout</h2><p>See how a missing text layer changes the review.</p><div class=actions>{secondary_action}</div></div></div></section><section class=sample-card><div class=sample-card-head><span class=sample-icon aria-hidden=true>🔒</span><div><p class=eyebrow>Coming later</p><h2>Private document review</h2><p>Real-document intake will stay closed until its dedicated security controls are provisioned and verified.</p></div></div></section></div>
            <section aria-labelledby=recent-heading><div class=section-heading><div><p class=eyebrow>Your workspace</p><h2 id=recent-heading>Recent sample reviews</h2></div><p class=small>Generated demo records only</p></div><ul class=queue>{rows}</ul></section></div>'''
            body = _app_shell("add", content)
            return _response(start_response, "200 OK", _html_page("Accessibility Hub staging", body))
        if path == "/documents/synthetic" and method == "POST":
            if not settings.synthetic_intake_ready:
                return _response(start_response, "503 Service Unavailable", _html_page("Accessibility Hub", "<main><div class=shell><section class=locked><h2>This staging service is not ready to create a document record.</h2><p>Configure the required private-service controls first.</p></section></div></main>"))
            fixture = _form(environ).get("fixture", "handout")
            fixtures = {
                "handout": ("coastline-synthetic-course-handout.pdf", synthetic_handout_pdf),
                "scan": ("coastline-synthetic-scanned-handout.pdf", synthetic_scan_pdf),
            }
            if fixture not in fixtures:
                content = '<div class=workspace-inner><section class=locked><h2>Choose one of the supplied samples.</h2><p><a class="button secondary" href="/app">Back to samples</a></p></section></div>'
                return _response(start_response, "400 Bad Request", _html_page("Choose a sample", _app_shell("add", content)))
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
                return _response(start_response, "404 Not Found", _html_page("Not found", "<main><div class=shell><h1>Document not found</h1></div></main>"))
            if len(pieces) == 2 and method == "GET":
                job = repository.latest_job(TENANT_ID, document_id)
                result = job.get("result") if job else None
                job_state = job["state"] if job else "queued"
                is_recheck = bool(document.get("parent_document_id"))
                # A slow refresh keeps this JavaScript-free page useful while
                # leaving a clear manual refresh action for assistive technology.
                refresh_head = "<meta http-equiv=\"refresh\" content=\"5\">" if job_state in {"queued", "running"} else ""
                remediation_rows = repository.remediations(TENANT_ID, document_id)
                provenance = "".join(f"<li><strong>{escape(r['kind'])}</strong> · {escape(r['created_at'][:19])}</li>" for r in remediation_rows) or "<li>No recheck has been applied to this version.</li>"
                cleanup = f'''<details><summary>Remove this synthetic record</summary><p>This removes this version and any rechecked copies from the demo store.</p><form method=post action="/documents/{escape(document_id)}/delete"><label><input type=checkbox name=confirmed value=yes required> I want to remove these synthetic records.</label><div class=actions><button class=secondary>Remove records</button></div></form></details>'''
                ocr_action = f'''<details><summary>Add a text layer from this scan</summary><p>Review the generated text against the scan before relying on it.</p><form method=post action="/documents/{escape(document_id)}/remediate/ocr"><label><input type=checkbox name=confirmed value=yes required> I will review the generated text against the page image.</label><div class=actions><button class=secondary>Apply text layer and recheck</button></div></form></details>''' if "scanned" in document["filename"] else ""
                if job_state in {"queued", "running"}:
                    current_step = "check" if is_recheck else "review"
                    phase_label = "Checking your improved copy" if is_recheck else "Reviewing the sample"
                    progress = f'''<div class=workspace-inner><header class=page-header><div class=page-header-copy><p class=eyebrow><a href="/app">Sample workspace</a> / Review</p><h1>{escape(phase_label)}</h1><p class=lead>{escape(document['filename'])}</p></div><span class=top-status><span class=status-dot aria-hidden=true></span>In progress</span></header><section class="panel progress-card" role=status aria-live=polite aria-atomic=true><div class=progress-orb aria-hidden=true></div><p class=eyebrow>Deterministic review</p><h2>Looking for useful accessibility signals…</h2><p>This usually takes a few seconds. This page checks again every five seconds.</p><ol class=progress-list><li><strong>Sample prepared</strong>Bundled content only</li><li class=active><strong>Reviewing signals</strong>Metadata, structure, and text</li><li><strong>Building next steps</strong>Plain-language guidance</li></ol><div class=actions><a class="button secondary" href="/documents/{escape(document_id)}">Refresh now</a></div></section></div>'''
                    body = _app_shell(current_step, progress)
                    return _response(start_response, "200 OK", _html_page("Review in progress — Accessibility Hub", body, refresh_head))

                resolved_count = 0
                if is_recheck and result:
                    parent_job = repository.latest_job(TENANT_ID, document["parent_document_id"])
                    parent_result = (parent_job or {}).get("result") or {}
                    before = {item.get("rule_id"): item.get("lane") for item in parent_result.get("signals", [])}
                    resolved_count = sum(1 for item in result.get("signals", []) if item.get("lane") == "verified_signal" and before.get(item.get("rule_id")) not in {None, "verified_signal"})
                completion = f'''<div class=completion role=status><span class=completion-mark aria-hidden=true>✓</span><div><h2>Your improved copy is ready</h2><p>{resolved_count or 'The'} accessibility signal{'s are' if resolved_count != 1 else ' is'} now verified in the recheck. The original sample remains unchanged.</p></div></div>''' if is_recheck and job_state == "succeeded" else ""
                header_title = "Recheck complete" if is_recheck else "Review findings"
                header_lead = "See what changed, then explore the remaining signals." if is_recheck else "Start with the clearest fixes. Every finding includes evidence and a next action."
                findings = f'''<section class=panel aria-labelledby=findings-heading><p class=eyebrow>{'4 · Check again' if is_recheck else '2 · Review'}</p><h2 id=findings-heading>Signals and next actions</h2>{_signal_summary(result)}{_signals(result, job_state)}<div class=advanced><details><summary>Review history and provenance</summary><ul class=queue>{provenance}</ul></details></div></section>'''
                if not is_recheck and job_state == "succeeded":
                    fixlab = f'''<aside class=fixlab aria-labelledby=fix-heading><p class=eyebrow>3 · Improve</p><h2 id=fix-heading>Fix the clearest issues</h2><p>Add a meaningful title and primary language, then run the check again.</p><form method=post action="/documents/{escape(document_id)}/remediate/metadata"><label for=document-title>Document title</label><input id=document-title name=title value="Week 3 Course Handout" required><label for=document-language>Primary language</label><input id=document-language name=language value="en-US" required><div class=actions><button>Apply and recheck <span aria-hidden=true>→</span></button></div></form><div class=advanced><details><summary>Advanced sample controls</summary><p>These expert controls are optional for the guided demo.</p><details><summary>Build tags from confirmed structure</summary><form method=post action="/documents/{escape(document_id)}/remediate/structure"><label for=confirmed-roles>Confirmed roles (JSON)</label><textarea id=confirmed-roles name=roles>{{"0":"h1","1":"p"}}</textarea><label for=confirmed-order>Confirmed reading order (JSON)</label><textarea id=confirmed-order name=order>[0,1,2,3,4,5]</textarea><label><input type=checkbox name=confirmed value=yes required> I confirm these roles and this reading order.</label><div class=actions><button class=secondary>Build tags and recheck</button></div></form></details>{ocr_action}{cleanup}</details></div><p class=small>Each recheck creates a new sample version and preserves its provenance.</p></aside>'''
                else:
                    parent_link = f'<a class="button secondary" href="/documents/{escape(document["parent_document_id"])}">View original sample</a>' if is_recheck else '<a class="button secondary" href="/app">Start another sample</a>'
                    fixlab = f'''<aside class=fixlab><p class=eyebrow>Next step</p><h2>{'Compare the result' if is_recheck else 'Try another sample'}</h2><p>{'The rechecked copy is stored as a separate demo version.' if is_recheck else 'This assessment did not complete, so no fixes were applied.'}</p><div class=actions>{parent_link}<a class="button secondary" href="/app">Sample workspace</a></div><div class=advanced>{cleanup}</div></aside>'''
                content = f'''<div class=workspace-inner><header class=page-header><div class=page-header-copy><p class=eyebrow><a href="/app">Sample workspace</a> / {escape('Recheck' if is_recheck else 'Findings')}</p><h1>{header_title}</h1><p class=lead>{header_lead}</p><div class=meta><span class=tag>{escape('Rechecked sample' if is_recheck else 'Bundled sample')}</span><span>{escape(document['filename'])}</span></div></div><span class=top-status><span class=status-dot aria-hidden=true></span>Synthetic demo only</span></header>{completion}<div class=document-layout>{findings}{fixlab}</div></div>'''
                body = _app_shell("check" if is_recheck else "improve", content)
                return _response(start_response, "200 OK", _html_page("Document review — Accessibility Hub", body, refresh_head))
            if len(pieces) == 3 and pieces[2] == "delete" and method == "POST":
                if _form(environ).get("confirmed") != "yes":
                    return _response(start_response, "400 Bad Request", _html_page("Removal needs confirmation", f"<main><div class=shell><section class=locked><h2>This record is still here.</h2><p><a href=\"/documents/{escape(document_id)}\">Return to the document</a></p></section></div></main>"))
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
                        roles = json.loads(form.get("roles", "{}")); order = json.loads(form.get("order", "[]"))
                        fixed, provenance = StructureRemediation.with_builtin_tools().apply(document["filename"], source, confirmed_roles=roles, reading_order=order)
                    elif kind == "ocr":
                        if form.get("confirmed") != "yes":
                            raise RemediationError("Confirm that you will review generated text before adding a text layer.")
                        fixed, provenance = OcrRemediation.with_builtin_tools().apply(document["filename"], source)
                    else:
                        return _response(start_response, "404 Not Found", _html_page("Not found", "<main><div class=shell><h1>Action not found</h1></div></main>"))
                    child = repository.create_document(TENANT_ID, document["filename"].replace(".pdf", ".rechecked.pdf"), "synthetic_remediated_copy", fixed, parent_document_id=document_id)
                    repository.record_remediation(child["id"], document_id, kind, provenance)
                    job_id = repository.enqueue(child["id"], kind="recheck")
                    repository.audit(TENANT_ID, ACTOR_ID, "remediation_applied", child["id"], {"parent": document_id, "kind": kind, "job_id": job_id, "provenance": provenance})
                    return _redirect(start_response, f"/documents/{child['id']}")
                except (RemediationError, ValueError, json.JSONDecodeError) as error:
                    return _response(start_response, "400 Bad Request", _html_page("Repair needs a closer look", f"<main><div class=shell><section class=locked><h2>This change was not applied.</h2><p>{escape(str(error))}</p><p><a href=\"/documents/{escape(document_id)}\">Return to the document</a></p></section></div></main>"))
        return _response(start_response, "404 Not Found", _html_page("Not found", "<main><div class=shell><h1>Page not found</h1></div></main>"))
    return app
