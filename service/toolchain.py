"""Read-only toolchain detection shared by /healthz, demo_up.sh, and the bench.

Reports what document tooling is actually present in this environment — a
version string when a tool answers, None when it does not. Detection never
changes review behavior: the checker and the bench make their own calls and
disclose unavailable tools through the existing Review-completeness machinery.
"""
from __future__ import annotations

import functools
import shutil
import subprocess

# The pinned container check_pdf.py would use if a Docker daemon were running.
_VERAPDF_CONTAINER_NOTE = (
    "no verapdf binary is installed and the pinned veraPDF container cannot run "
    "(no working Docker daemon), so full-standard validator checks are disclosed "
    "as not run"
)


def _first_line(command: list[str]) -> str | None:
    """First stdout/stderr line of a --version style probe, or None."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    text = (result.stdout or result.stderr).strip()
    return text.splitlines()[0].strip() if text else None


def _docker_daemon_running() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                                capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


@functools.lru_cache(maxsize=1)
def toolchain_versions() -> dict[str, str | None]:
    """{tool: version-line-or-None} for the document toolchain, cached per process."""
    verapdf = _first_line(["verapdf", "--version"])
    if verapdf is None and _docker_daemon_running():
        verapdf = "containerized (pinned image via Docker)"
    return {
        "qpdf": _first_line(["qpdf", "--version"]),
        "tesseract": _first_line(["tesseract", "--version"]),
        # poppler-utils page rasterizer: powers the real before/after page-1
        # thumbnails. Absent, those surfaces fall back to an honest schematic.
        "pdftoppm": _first_line(["pdftoppm", "-v"]),
        "verapdf": verapdf,
    }


def verapdf_unavailable_reason() -> str | None:
    """Plain-language reason veraPDF cannot run here, or None when it can."""
    if toolchain_versions()["verapdf"] is not None:
        return None
    return _VERAPDF_CONTAINER_NOTE


def status_lines() -> list[str]:
    """Human-readable status block, one line per tool, always honest."""
    versions = toolchain_versions()
    lines = ["Toolchain status:"]
    for name in ("qpdf", "tesseract"):
        version = versions[name]
        lines.append(f"  {name:<10} {version if version else 'not detected — its checks are disclosed as not run'}")
    pdftoppm = versions["pdftoppm"]
    lines.append(f"  {'pdftoppm':<10} {pdftoppm if pdftoppm else 'not detected — page thumbnails fall back to a labeled schematic'}")
    if versions["verapdf"]:
        lines.append(f"  {'veraPDF':<10} {versions['verapdf']}")
    else:
        lines.append(f"  {'veraPDF':<10} unavailable — {verapdf_unavailable_reason()}")
    return lines


def print_status() -> None:
    print("\n".join(status_lines()))


if __name__ == "__main__":
    print_status()
