"""Separate, locked-by-default entrypoint for a future Render web service."""
from service.real_intake.app import create_app

application = create_app()
