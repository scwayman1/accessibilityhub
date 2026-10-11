"""Gunicorn entrypoint for the private staging web service."""
import logging

from service.app import create_app

# One structured line per request (service/hardening.py) on stderr, which
# Render collects. No content, query strings, or cookies are ever logged.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

application = create_app()
