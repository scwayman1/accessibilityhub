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
WORKFLOW_STEPS = (("add", "1", "Add material"), ("review", "2", "Review"), ("improve", "3", "Improve"), ("check", "4", "Check again"))
LANE_PRESENTATION = {
    "needs_attention": ("!", "Needs attention"),
    "review_recommended": ("?", "Review recommended"),
    "verified_signal": ("✓", "Verified signal"),
    "not_assessed": ("–", "Not assessed"),
}


def _workflow_rail(current: str) -> str:
    items = "".join(
        f"<li class={'current' if key == current else 'upcoming'}><span class=step-number>{number}</span><span>{label}</span></li>"
        for key, number, label in WORKFLOW_STEPS
    )
    return f"<nav class=workflow-rail aria-label=\"Workspace rhythm\"><ol>{items}</ol></nav>"


def _html_page(title: str, body: str) -> bytes:
    css = """
    :root { --navy:#003764; --ink:#081922; --ink-soft:#123143; --porcelain:#f7f3eb; --paper:#fffdf8; --line:#d7dedb; --sky:#6bc4e8; --blue:#3cb4e5; --ocean:#006f8f; --copper:#af7653; --muted:#5a7078; --success:#276a55; --attention:#a65329; }
    * { box-sizing:border-box } body { margin:0; color:var(--ink); background:var(--porcelain); font:15px/1.55 Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; } a { color:inherit } :focus-visible { outline:3px solid var(--sky); outline-offset:3px } .shell { width:min(1240px,calc(100% - 48px)); margin:auto; }
    header { background:var(--ink); color:white; border-bottom:3px solid var(--sky); } nav { min-height:72px; display:flex; align-items:center; justify-content:space-between; gap:24px; } .brand { display:block; width:188px; line-height:0; } .brand img { display:block; width:100%; height:auto; } .nav-note { color:#d8edf5; font-size:11px; font-weight:800; letter-spacing:.13em; text-transform:uppercase; }
    main { padding:28px 0 72px } h1,h2,h3 { margin:0; letter-spacing:-.03em } h1,h2 { font-family:Georgia,"Times New Roman",serif; font-weight:500; line-height:1.04 } h1 { max-width:780px; font-size:clamp(40px,5vw,62px) } h2 { font-size:27px } h3 { font-size:15px } .eyebrow { margin:0 0 9px; color:var(--ocean); font-size:10px; font-weight:850; letter-spacing:.15em; text-transform:uppercase; } .lead { max-width:690px; margin:15px 0 0; color:#45616b; font-size:16px; }
    .hero { position:relative; overflow:hidden; padding:40px 42px; color:white; background:linear-gradient(120deg,#003764,#005477); box-shadow:0 20px 42px rgba(0,55,100,.16); } .hero:after { content:""; position:absolute; width:310px; height:310px; border:1px solid rgba(107,196,232,.42); border-radius:50%; right:-105px; top:-172px; } .hero>* { position:relative; z-index:1 } .hero .eyebrow { color:#bceafa } .hero .lead { color:#e1f2f8; }
    .workflow-rail { margin-top:18px; padding:11px 16px; color:#d8e9f1; background:var(--ink); border-left:4px solid var(--sky); } .workflow-rail ol { display:flex; gap:8px; margin:0; padding:0; list-style:none; } .workflow-rail li { display:flex; align-items:center; gap:8px; padding:5px 11px; color:#aabec8; font-size:12px; font-weight:750; white-space:nowrap; } .workflow-rail li.current { color:white; background:var(--ink-soft); } .step-number { display:grid; place-items:center; width:19px; height:19px; color:#bdeafa; border:1px solid #588196; border-radius:50%; font-size:10px; } .workflow-rail li.current .step-number { color:var(--ink); border-color:var(--sky); background:var(--sky); }
    .workspace { display:grid; grid-template-columns:330px minmax(0,1fr); gap:18px; margin-top:18px } .panel { padding:24px; border:1px solid var(--line); background:var(--paper); box-shadow:0 10px 24px rgba(25,50,58,.06); } .panel p { margin:7px 0 0; color:var(--muted); font-size:13px; } .rail { color:white; border-color:var(--ink); background:var(--ink); box-shadow:none; } .rail .eyebrow { color:var(--sky) } .rail h2, .rail h3 { color:white } .rail p, .rail .small { color:#c2d3da } .rail input, .rail textarea { color:var(--ink); background:#fffefa; } .rail .tag { color:#dff4fa; border-color:#46798e; background:#15384a; }
    .queue { margin:15px 0; padding:0; list-style:none } .queue li { padding:13px 0; border-bottom:1px solid #dde4e2 } .queue li:last-child { border-bottom:0 } .queue a { font-weight:800; text-decoration-color:var(--sky); text-decoration-thickness:2px; text-underline-offset:4px } .rail .queue li { border-color:#284a5a } .meta { display:flex; flex-wrap:wrap; gap:8px; margin-top:9px; color:#62777c; font-size:12px } .tag { display:inline-block; padding:4px 7px; color:var(--navy); border:1px solid #b8d5df; background:#eef8fb; font:10px ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:.05em; text-transform:uppercase }
    button { min-height:42px; padding:0 15px; border:1px solid var(--ocean); border-radius:2px; background:var(--ocean); color:white; font-weight:800; cursor:pointer; } button:hover { border-color:#00546d; background:#00546d } button.secondary { color:var(--navy); border-color:#9fc9d8; background:#f4fafb; } button.secondary:hover { background:#e2f3f8 } form { margin:0 } label { display:block; margin:13px 0 5px; font-size:13px; font-weight:750 } input,textarea { width:100%; padding:10px; color:var(--ink); border:1px solid #bdcbc9; border-radius:2px; background:#fffefa; font:14px Inter,ui-sans-serif,sans-serif; } textarea { min-height:88px; font:12px ui-monospace,SFMono-Regular,Menlo,monospace; }
    .actions { display:flex; flex-wrap:wrap; gap:9px; align-items:center; margin-top:18px } .details { margin-top:20px } details { margin:12px 0; padding:14px; border:1px solid #d9e1df; background:#fbfaf5; } summary { cursor:pointer; font-weight:800; } .small { font-size:12px; color:var(--muted) }
    .signal { display:grid; grid-template-columns:142px 1fr; gap:18px; padding:18px 0; border-bottom:1px solid #dbe3e1 } .signal:last-child { border-bottom:0 } .signal-heading { display:flex; align-items:center; gap:8px; } .signal-icon { display:grid; place-items:center; width:22px; height:22px; border:1px solid currentColor; border-radius:50%; font-weight:900; line-height:1; } .chip { display:inline-flex; align-items:center; gap:5px; width:max-content; max-width:100%; padding:4px 7px; border:1px solid currentColor; border-radius:999px; font-size:10px; font-weight:850; letter-spacing:.06em; line-height:1.1; text-transform:uppercase; } .needs_attention .chip,.needs_attention .signal-icon { color:var(--attention) } .review_recommended .chip,.review_recommended .signal-icon { color:var(--ocean) } .verified_signal .chip,.verified_signal .signal-icon { color:var(--success) } .not_assessed .chip,.not_assessed .signal-icon { color:#62757b } .signal p { margin:5px 0 0; color:var(--muted); font-size:13px }
    .fixlab { margin-top:21px; padding:19px; border-top:3px solid var(--copper); background:#f8eee6; } .fixlab > p { margin-bottom:5px } .fixlab details { background:#fffaf4 } .rail .fixlab { color:var(--ink); background:#f8eee6 } .rail .fixlab .eyebrow { color:#8a5031 } .rail .fixlab h2,.rail .fixlab p { color:var(--ink) } .locked { padding:24px; border-left:4px solid var(--copper); background:#fff4e5 } .login { width:min(470px,100%); margin:42px auto } .login .panel { padding:32px; }
    @media(max-width:800px) { .shell { width:min(100% - 30px,1240px) } nav { min-height:66px } .brand { width:165px } .workflow-rail { overflow:auto } .workspace { grid-template-columns:1fr } .hero { padding:30px } .signal { grid-template-columns:1fr; gap:9px } .nav-note { display:none } }
    """
    return f"""<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{escape(title)}</title><style>{css}</style></head><body><header><div class=\"shell\"><nav><a class=\"brand\" href=\"/app\"><img src=\"/assets/coastline-college-logo-white.png\" alt=\"Coastline College\"></a><span class=\"nav-note\">Accessibility Hub</span></nav></div></header>{body}</body></html>""".encode()


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
    size = min(int(environ.get("CONTENT_LENGTH") or 0), 50_000)
    values = parse_qs(environ["wsgi.input"].read(size).decode("utf-8", "replace"))
    return {key: value[-1] for key, value in values.items()}


def _signals(result: dict[str, Any] | None) -> str:
    if not result:
        return "<p class=\"small\">Assessment is queued. This page refreshes while it runs.</p><script>setTimeout(()=>location.reload(),700)</script>"
    cards = []
    for signal in result.get("signals", []):
        lane = signal["lane"]
        icon, label = LANE_PRESENTATION.get(lane, LANE_PRESENTATION["not_assessed"])
        context = " <span class=tag>educator context</span>" if signal.get("educator_context") else ""
        cards.append(f"<article class=\"signal {escape(lane)}\"><div><span class=\"chip\"><span aria-hidden=true>{icon}</span>{escape(label)}</span></div><div><div class=signal-heading><span class=signal-icon aria-hidden=true>{icon}</span><h3>{escape(signal['title'])}</h3></div><p>{escape(signal.get('evidence') or '')}</p><p><strong>Next:</strong> {escape(signal.get('next_action') or '')}{context}</p></div></article>")
    return "".join(cards) + "<p class=small>Each signal stands on its own. The workspace does not create an overall result.</p>"


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
        if not _authenticated(environ, settings):
            return _redirect(start_response, "/login")
        if path in {"/", "/app"} and method == "GET":
            documents = repository.list_documents(TENANT_ID)
            rows = "".join(f"<li><a href=\"/documents/{escape(d['id'])}\"><strong>{escape(d['filename'])}</strong></a><div class=meta><span class=tag>{escape(d.get('job_state') or 'queued')}</span><span>{escape(d['created_at'][:19])}</span></div></li>" for d in documents) or "<li>No synthetic assessment has started yet.</li>"
            intake = "<form method=post action=\"/documents/synthetic\"><button name=fixture value=handout>Review a course handout</button><button class=secondary name=fixture value=scan>Review a scanned handout</button></form>" if settings.synthetic_intake_ready else "<div class=locked><h3>Hosted controls are not connected</h3><p>Private storage, scan gate, isolated worker, tenant authorization, lifecycle, and audit integrations must be configured before a hosted process can begin.</p></div>"
            body = f"<main><div class=shell><section class=hero><p class=eyebrow>Accessibility Hub</p><h1>See what to improve. Keep what already works.</h1><p class=lead>Start with a supplied handout, review clear signals, make one intentional change, then check the new version.</p></section>{_workflow_rail('add')}<section class=workspace><aside class=\"panel rail\"><p class=eyebrow>1 · Add material</p><h2>Choose a sample</h2><p>Use the course handout for metadata and structure signals, or the scanned handout to review an OCR text layer.</p><div class=actions>{intake}</div><p class=small>Real, institutional, and public uploads are not accepted in this environment.</p></aside><section class=panel><p class=eyebrow>Workspace</p><h2>Document records</h2><ul class=queue>{rows}</ul></section></section></div></main>"
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
                return _response(start_response, "400 Bad Request", _html_page("Choose a sample", "<main><div class=shell><section class=locked><h2>Choose one of the supplied samples.</h2></section></div></main>"))
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
                remediation_rows = repository.remediations(TENANT_ID, document_id)
                provenance = "".join(f"<li><strong>{escape(r['kind'])}</strong> · {escape(r['created_at'][:19])}</li>" for r in remediation_rows) or "<li>No recheck has been applied to this version.</li>"
                cleanup = f"<details><summary>Remove this synthetic record</summary><p>This removes this version and any rechecked copies from the local staging store.</p><form method=post action=\"/documents/{escape(document_id)}/delete\"><label><input type=checkbox name=confirmed value=yes required> I want to remove these synthetic records.</label><div class=actions><button class=secondary>Remove records</button></div></form></details>"
                ocr_action = f"<details><summary>Add a text layer from this scan</summary><p>Review the generated text against the scan before relying on it.</p><form method=post action=\"/documents/{escape(document_id)}/remediate/ocr\"><label><input type=checkbox name=confirmed value=yes required> I will review the generated text against the page image.</label><div class=actions><button class=secondary>Apply text layer and recheck</button></div></form></details>" if "scanned" in document["filename"] else ""
                body = f"<main><div class=shell><p class=eyebrow><a href=\"/app\">Workspace</a> / document</p><h1>{escape(document['filename'])}</h1><p class=lead>Read each signal, decide what to improve, and check the new version without losing the record of what changed.</p>{_workflow_rail('review')}<section class=workspace><aside class=\"panel rail\"><p class=eyebrow>Document record</p><h2>Assessment {escape(job['state'] if job else 'queued')}</h2><div class=meta><span class=tag>{escape(document['source_kind'])}</span><span>{escape(document['sha256'][:16])}…</span></div><section class=fixlab><p class=eyebrow>3 · Improve</p><h2>Fix Lab</h2><p>Apply a change, then check the new version.</p><details open><summary>Update title and language</summary><form method=post action=\"/documents/{escape(document_id)}/remediate/metadata\"><label>Document title</label><input name=title value=\"Week 3 Course Handout\" required><label>Primary language</label><input name=language value=\"en-US\" required><div class=actions><button>Apply and recheck</button></div></form></details><details><summary>Build tags from your confirmed structure</summary><p>Confirm roles and reading order before this copy is changed.</p><form method=post action=\"/documents/{escape(document_id)}/remediate/structure\"><label>Confirmed roles (JSON)</label><textarea name=roles>{{\"0\":\"h1\",\"1\":\"p\"}}</textarea><label>Confirmed reading order (JSON)</label><textarea name=order>[0,1,2,3,4,5]</textarea><label><input type=checkbox name=confirmed value=yes required> I confirm these roles and this reading order.</label><div class=actions><button class=secondary>Build tags and recheck</button></div></form></details>{ocr_action}{cleanup}</section><p class=small>Each recheck creates a new version and keeps the source record intact.</p></aside><section class=panel><p class=eyebrow>2 · Review</p><h2>Signals and next actions</h2>{_signals(result)}<div class=details><details><summary>4 · Check again — remediation provenance</summary><ul class=queue>{provenance}</ul></details></div></section></section></div></main>"
                return _response(start_response, "200 OK", _html_page("Document review — Accessibility Hub", body))
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
