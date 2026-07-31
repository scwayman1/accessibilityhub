"""Dormant background process for a provisioned-but-locked worker service."""
from __future__ import annotations

import signal
import threading

from service.real_intake.deploy_check import verify_locked_deploy


POLL_SECONDS = 30


def run() -> None:
    """Stay alive without queues, storage, parsing, models, or network calls."""
    stop = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    verify_locked_deploy()
    print("real-intake-worker: locked")
    while not stop.wait(POLL_SECONDS):
        # Reassert code/config invariants even though Render environment values
        # are normally immutable for the lifetime of a running instance.
        verify_locked_deploy()


if __name__ == "__main__":
    run()
