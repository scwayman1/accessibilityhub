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
