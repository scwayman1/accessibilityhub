"""Run the private staging service locally with an explicit synthetic access guard."""
from __future__ import annotations

import os
from wsgiref.simple_server import make_server

from service.app import create_app
from service.settings import ServiceSettings


def resolve_port(environ: dict[str, str] | None = None) -> int:
    """Port contract: PORT wins, then HUB_PORT, then the 8787 default."""
    values = environ if environ is not None else os.environ
    for name in ("PORT", "HUB_PORT"):
        raw = (values.get(name) or "").strip()
        if raw:
            try:
                return int(raw)
            except ValueError:
                raise SystemExit(f"{name} must be an integer port number, got {raw!r}.")
    return 8787


def main() -> None:
    settings = ServiceSettings.from_environ()
    port = resolve_port()
    with make_server("127.0.0.1", port, create_app(settings)) as server:
        print(f"Accessibility Hub staging service listening on http://127.0.0.1:{port}")
        server.serve_forever()


if __name__ == "__main__":
    main()
