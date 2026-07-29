"""Gunicorn entrypoint for the private staging web service."""
from service.app import create_app

application = create_app()
