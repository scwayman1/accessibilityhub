"""Pilot hardening: rate limits, server-side sign-out, HSTS, and request logs."""
import io
import logging
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode

from service.app import create_app
from service.hardening import RateLimiter, client_address
from service.repository import StagingRepository
from service.settings import ServiceSettings
from service.worker import AssessmentWorker


class RateLimiterTests(unittest.TestCase):
    def test_window_allows_limit_then_blocks_until_it_slides(self):
        now = [0.0]
        limiter = RateLimiter(limit=2, window=10, clock=lambda: now[0])
        self.assertIsNone(limiter.hit("a"))
        self.assertIsNone(limiter.hit("a"))
        self.assertGreaterEqual(limiter.hit("a"), 1.0)
        self.assertIsNone(limiter.hit("b"))  # keys are independent
        now[0] = 10.5
        self.assertIsNone(limiter.hit("a"))

    def test_client_address_trusts_only_the_proxy_appended_hop(self):
        environ = {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "6.6.6.6, 203.0.113.9"}
        self.assertEqual(client_address(environ, trust_proxy=True), "203.0.113.9")
        self.assertEqual(client_address(environ, trust_proxy=False), "10.0.0.1")


class ServiceHardeningTests(unittest.TestCase):
    def make(self, environment="development"):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        settings = ServiceSettings(environment, Path(self.temp.name), "synthetic-only-code", "s" * 48, (),
                                   allow_hosted_synthetic=True)
        repository = StagingRepository(settings.data_dir)
        worker = AssessmentWorker(repository)
        self.addCleanup(worker.stop)
        self.app = create_app(settings, repository, worker)

    def request(self, path, method="GET", form=None, cookie="", remote="198.51.100.7"):
        body = urlencode(form or {}).encode()
        captured = {}

        def start_response(status, headers):
            captured["status"], captured["headers"] = status, headers

        b"".join(self.app({
            "REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "",
            "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": "application/x-www-form-urlencoded",
            "wsgi.input": io.BytesIO(body), "HTTP_COOKIE": cookie, "REMOTE_ADDR": remote,
        }, start_response))
        return captured["status"], dict(captured["headers"])

    def test_sign_in_attempts_are_rate_limited_per_client(self):
        self.make()
        statuses = [self.request("/login", "POST", {"code": "wrong"})[0][:3] for _ in range(11)]
        self.assertEqual(statuses[:10], ["401"] * 10)
        self.assertEqual(statuses[10], "429")
        status, headers = self.request("/login", "POST", {"code": "wrong"})
        self.assertIn("Retry-After", headers)
        # A different client is unaffected.
        self.assertTrue(self.request("/login", "POST", {"code": "synthetic-only-code"}, remote="192.0.2.1")[0].startswith("303"))

    def test_sign_out_revokes_the_session_on_the_server(self):
        self.make()
        status, headers = self.request("/login", "POST", {"code": "synthetic-only-code"})
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertTrue(self.request("/app", cookie=cookie)[0].startswith("200"))
        self.request("/logout", "POST", cookie=cookie)
        # Replaying the old cookie after sign-out no longer opens the workspace.
        status, headers = self.request("/app", cookie=cookie)
        self.assertTrue(status.startswith("303"))
        self.assertEqual(headers["Location"], "/login")

    def test_hosted_responses_carry_hsts_and_development_does_not(self):
        self.make("staging")
        _, headers = self.request("/login")
        self.assertEqual(headers.get("Strict-Transport-Security"), "max-age=31536000; includeSubDomains")
        self.make("development")
        _, headers = self.request("/login")
        self.assertNotIn("Strict-Transport-Security", headers)

    def test_request_log_lines_carry_no_query_strings_or_form_values(self):
        self.make()
        with self.assertLogs("hub.request", level=logging.INFO) as logs:
            self.request("/login", "POST", {"code": "super-secret-code"})
        line = logs.output[-1]
        self.assertIn('"path": "/login"', line)
        self.assertIn('"status": "401"', line)
        self.assertNotIn("super-secret-code", line)


if __name__ == "__main__":
    unittest.main()


class OwnSurfaceAccessibilityTests(unittest.TestCase):
    """Fixes for the defects our own accessibility conformance report found (ACR-1..4)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        settings = ServiceSettings("development", Path(self.temp.name), "synthetic-only-code", "s" * 48, ())
        repository = StagingRepository(settings.data_dir)
        worker = AssessmentWorker(repository)
        worker.stop()  # keep jobs queued so the in-progress page is observable
        self.app = create_app(settings, repository, worker)
        worker.stop()
        self.cookie = ""

    def request(self, path, method="GET", form=None, extra_cookie=""):
        query = ""
        if "?" in path:
            path, query = path.split("?", 1)
        body = urlencode(form or {}).encode()
        captured = {}

        def start_response(status, headers):
            captured["status"], captured["headers"] = status, dict(headers)

        response = b"".join(self.app({
            "REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query,
            "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": "application/x-www-form-urlencoded",
            "wsgi.input": io.BytesIO(body), "HTTP_COOKIE": "; ".join(c for c in (self.cookie, extra_cookie) if c),
            "REMOTE_ADDR": "198.51.100.9",
        }, start_response))
        return captured["status"], captured["headers"], response

    @staticmethod
    def contrast(hex_a, hex_b="#FFFFFF"):
        def luminance(value):
            value = value.lstrip("#")
            channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
        high, low = sorted((luminance(hex_a), luminance(hex_b)), reverse=True)
        return (high + 0.05) / (low + 0.05)

    def test_form_field_borders_meet_three_to_one(self):
        import re

        for surface, pattern in ((Path("service/app.py"), r"--field:(#[0-9A-Fa-f]{6})"),
                                 (Path("local_reviewer.html"), r"--field:(#[0-9A-Fa-f]{6})")):
            color = re.search(pattern, surface.read_text()).group(1)
            self.assertGreaterEqual(self.contrast(color), 3.0, surface)
            self.assertGreaterEqual(self.contrast(color, "#FAFAF8"), 3.0, surface)
        self.assertIn("input,select,textarea { width:100%; padding:11px 12px; color:var(--ink); border:1px solid var(--field)",
                      Path("service/app.py").read_text())

    def start_review(self):
        _, headers, _ = self.request("/login", "POST", {"code": "synthetic-only-code"})
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]
        _, headers, _ = self.request("/documents/synthetic", "POST", {"fixture": "handout"})
        return headers["Location"]

    def test_automatic_updates_can_be_paused_and_resumed(self):
        location = self.start_review()
        _, _, page = self.request(location)
        self.assertIn(b'http-equiv="refresh"', page)
        self.assertIn(f'href="{location}?updates=off">Pause automatic updates'.encode(), page)
        _, _, paused = self.request(location + "?updates=off")
        self.assertNotIn(b'http-equiv="refresh"', paused)
        self.assertIn(b"Automatic updates are paused", paused)
        self.assertIn(f'href="{location}">Resume automatic updates'.encode(), paused)

    def test_animations_can_be_paused_on_every_page(self):
        location = self.start_review()
        _, _, page = self.request(location)
        self.assertIn(b'action="/preferences/motion"', page)
        status, headers, _ = self.request("/preferences/motion", "POST", {"state": "paused", "next": location})
        self.assertTrue(status.startswith("303"))
        self.assertEqual(headers["Location"], location)
        motion = headers["Set-Cookie"].split(";", 1)[0]
        self.assertEqual(motion, "hub_motion=paused")
        _, headers, paused = self.request(location, extra_cookie=motion)
        self.assertIn(b"<style id=motion-paused>", paused)
        self.assertEqual(int(headers["Content-Length"]), len(paused))
        self.assertIn(b"Play animations", paused)
        _, _, other = self.request("/app", extra_cookie=motion)
        self.assertIn(b"<style id=motion-paused>", other)

    def test_motion_preference_redirect_stays_on_this_site(self):
        for target in ("https://evil.example/", "//evil.example", "javascript:alert(1)", ""):
            _, headers, _ = self.request("/preferences/motion", "POST", {"state": "paused", "next": target})
            self.assertEqual(headers["Location"], "/app", target)

    def test_sessions_last_twenty_hours(self):
        import base64
        import json as _json
        import time as _time

        _, headers, _ = self.request("/login", "POST", {"code": "synthetic-only-code"})
        token = headers["Set-Cookie"].split(";", 1)[0].split("=", 1)[1]
        payload = token.rsplit(".", 1)[0]
        data = _json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        self.assertGreaterEqual(data["exp"] - _time.time(), 20 * 3600 - 60)

    def test_workbench_fix_fields_have_visible_labels_and_a_pause_control(self):
        source = Path("local_reviewer.html").read_text()
        self.assertIn("lab.textContent='Description for link '", source)
        self.assertIn("altLabel.textContent='Description for figure '", source)
        self.assertIn("attestLabel.textContent='Describe the decision you made'", source)
        self.assertNotIn("setAttribute('aria-label','Accessible description for link", source)
        self.assertIn('id="pauseMotion"', source)
        self.assertIn("html.motion-paused *", source)


class SsoPlaceholderTests(unittest.TestCase):
    def make(self, provider):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        settings = ServiceSettings.from_environ({
            "HUB_ENV": "staging", "HUB_DATA_DIR": self.temp.name, "HUB_STAGING_ACCESS_CODE": "code",
            "HUB_SESSION_SECRET": "s" * 48, "HUB_SSO_PROVIDER": provider,
        })
        repository = StagingRepository(settings.data_dir)
        worker = AssessmentWorker(repository)
        self.addCleanup(worker.stop)
        self.app = create_app(settings, repository, worker)
        return settings

    def request(self, path, method="GET"):
        captured = {}

        def start_response(status, headers):
            captured["status"] = status

        body = b"".join(self.app({
            "REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "", "CONTENT_LENGTH": "0",
            "wsgi.input": io.BytesIO(b""), "HTTP_COOKIE": "", "REMOTE_ADDR": "203.0.113.5",
        }, start_response))
        return captured["status"], body

    def test_entra_placeholder_is_visible_disabled_and_never_a_route(self):
        settings = self.make("Entra")
        self.assertEqual(settings.sso_provider, "entra")
        status, page = self.request("/login")
        self.assertIn(b"Sign in with your Coastline Microsoft account", page)
        self.assertIn(b"disabled", page)
        self.assertIn(b"being connected with Coastline IT", page)
        self.assertNotIn(b'action="/login/sso"', page)
        self.assertLess(page.index(b"Coastline Microsoft account"), page.index(b"Access code"))
        self.assertIn(b"<button class=primary>Continue</button>", page)
        self.assertTrue(self.request("/login/sso", "POST")[0].startswith("404"))

    def test_unknown_or_unset_provider_shows_nothing(self):
        for value in ("", "okta"):
            settings = self.make(value)
            self.assertEqual(settings.sso_provider, "")
            self.assertNotIn(b"Microsoft", self.request("/login")[1])
