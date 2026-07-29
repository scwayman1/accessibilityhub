"""Run the private staging service locally with an explicit synthetic access guard."""
from __future__ import annotations

import os
from wsgiref.simple_server import make_server

from service.app import create_app
from service.settings import ServiceSettings


if __name__ == "__main__":
    settings = ServiceSettings.from_environ()
    port = int(os.environ.get("PORT", "8787"))
    with make_server("127.0.0.1", port, create_app(settings)) as server:
        print(f"Accessibility Hub staging service listening on http://127.0.0.1:{port}")
        server.serve_forever()
