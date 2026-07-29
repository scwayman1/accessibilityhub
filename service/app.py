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
from typing import Any, Callable
from urllib.parse import parse_qs

from tina.remedy import MetadataRemediation, RemediationError
from tina.structure import StructureRemediation

from service.fixtures import synthetic_handout_pdf
from service.repository import StagingRepository
from service.settings import ServiceSettings
from service.worker import AssessmentWorker

TENANT_ID = "coastline-staging"
ACTOR_ID = "staging-educator"


def _html_page(title: str, body: str) -> bytes:
    return f"""<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{escape(title)}</title><style>
</style></head><body><header><div class=\"shell\"><nav><a class=\"brand\" href=\"/app\">Coastline <span>Accessibility Hub</span></a><span class=\"nav-note\">Staging workspace</span></nav></div></header>{body}</body></html>""".encode()


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
    base = [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store"), ("X-Frame-Options", "DENY"), ("Referrer-Policy", "no-referrer"), ("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")]
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
        context = " · educator context needed" if signal.get("educator_context") else ""
        cards.append(f"<article class=\"signal {escape(lane)}\"><div class=lane>{escape(lane.replace('_',' '))}{context}</div><div><h3>{escape(signal['title'])}</h3><p>{escape(signal.get('evidence') or '')}</p><p><strong>Next:</strong> {escape(signal.get('next_action') or '')}</p></div></article>")
    return "".join(cards) + "<p class=small>Each signal stands on its own. The workspace does not create an overall result.</p>"


def create_app(settings: ServiceSettings | None = None, repository: StagingRepository | None = None, worker: AssessmentWorker | None = None):
    settings = settings or ServiceSettings.from_environ()
    repository = repository or StagingRepository(settings.data_dir)
    worker = worker or AssessmentWorker(repository)
    worker.start()

    def app(environ: dict[str, Any], start_response: Callable):
        path, method = environ.get("PATH_INFO", "/"), environ.get("REQUEST_METHOD", "GET")
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
            intake = "<form method=post action=\"/documents/synthetic\"><button>Start a synthetic assessment</button></form>" if settings.synthetic_intake_ready else "<div class=locked><h3>Hosted controls are not connected</h3><p>Private storage, scan gate, isolated worker, tenant authorization, lifecycle, and audit integrations must be configured before a hosted process can begin.</p></div>"
            body = f"<main><div class=shell><section class=hero><p class=eyebrow>Private staging workspace</p><h1>Turn a course PDF into a clear next step.</h1><p class=lead>Start with the bundled synthetic handout. The service creates a protected document record, runs a queued deterministic assessment, and keeps the evidence and any recheck together.</p></section><section class=workspace><aside class=panel><p class=eyebrow>Start</p><h2>One controlled input</h2><p>Use the synthetic handout to exercise the real staging flow.</p><div class=actions>{intake}</div><p class=small>Real, institutional, and public uploads are not accepted in this environment.</p></aside><section class=panel><p class=eyebrow>Recent work</p><h2>Document records</h2><ul class=queue>{rows}</ul></section></section></div></main>"
            return _response(start_response, "200 OK", _html_page("Accessibility Hub staging", body))
        if path == "/documents/synthetic" and method == "POST":
            if not settings.synthetic_intake_ready:
                return _response(start_response, "503 Service Unavailable", _html_page("Accessibility Hub", "<main><div class=shell><section class=locked><h2>This staging service is not ready to create a document record.</h2><p>Configure the required private-service controls first.</p></section></div></main>"))
            item = repository.create_document(TENANT_ID, "coastline-synthetic-course-handout.pdf", "bundled_synthetic_fixture", synthetic_handout_pdf())
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
                body = f"<main><div class=shell><p class=eyebrow><a href=\"/app\">Workspace</a> / document</p><h1>{escape(document['filename'])}</h1><p class=lead>Evidence is grouped by what can be acted on now, what needs educator context, what is individually verified, and what this slice did not assess.</p><section class=workspace><aside class=panel><p class=eyebrow>Document record</p><h2>Assessment {escape(job['state'] if job else 'queued')}</h2><div class=meta><span class=tag>{escape(document['source_kind'])}</span><span>{escape(document['sha256'][:16])}…</span></div><div class=details><details open><summary>Apply a metadata repair to a copy</summary><form method=post action=\"/documents/{escape(document_id)}/remediate/metadata\"><label>Document title</label><input name=title value=\"Week 3 Course Handout\" required><label>Primary language</label><input name=language value=\"en-US\" required><div class=actions><button>Apply and recheck</button></div></form></details><details><summary>Build tags from your confirmed structure</summary><p>Confirm roles and reading order before this copy is changed.</p><form method=post action=\"/documents/{escape(document_id)}/remediate/structure\"><label>Confirmed roles (JSON)</label><textarea name=roles>{{\"0\":\"h1\",\"1\":\"p\"}}</textarea><label>Confirmed reading order (JSON)</label><textarea name=order>[0,1,2,3,4,5]</textarea><label><input type=checkbox name=confirmed value=yes required> I confirm these roles and this reading order.</label><div class=actions><button class=secondary>Build tags and recheck</button></div></form></details>{cleanup}</div><p class=small>Rechecks create a new document version; the source record remains unchanged.</p></aside><section class=panel><p class=eyebrow>Assessment evidence</p><h2>Signals and next actions</h2>{_signals(result)}<div class=details><details><summary>Remediation provenance</summary><ul class=queue>{provenance}</ul></details></div></section></section></div></main>"
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
