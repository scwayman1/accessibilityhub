"""Bounded ClamAV INSTREAM client for a private service endpoint."""
from __future__ import annotations

import re
import socket
import struct
from dataclasses import dataclass
from typing import BinaryIO, Callable, Protocol

from service.real_intake.clamav import (
    MAX_RESPONSE_BYTES,
    ClamAvVerdict,
    classify_scan_response,
)
from service.real_intake.upload_gate import UploadPolicy


PRIVATE_ENDPOINT = re.compile(
    r"^(?P<host>[a-z][a-z0-9-]{0,62}):(?P<port>[1-9][0-9]{0,4})$"
)


def parse_private_endpoint(value: str) -> tuple[str, int]:
    """Accept a Render-private service name and port, never a URL or public host."""
    match = PRIVATE_ENDPOINT.fullmatch(value)
    if match is None:
        raise ValueError("ClamAV endpoint must be private-service-name:port")
    port = int(match.group("port"))
    if port > 65_535:
        raise ValueError("ClamAV endpoint port is invalid")
    return match.group("host"), port


class ClamdSocket(Protocol):
    def sendall(self, data: bytes) -> None: ...
    def recv(self, size: int) -> bytes: ...
    def close(self) -> None: ...


SocketFactory = Callable[[tuple[str, int], float], ClamdSocket]


@dataclass(frozen=True)
class ClamdScanResult:
    verdict: ClamAvVerdict
    bytes_streamed: int


def _default_socket_factory(address: tuple[str, int], timeout: float) -> ClamdSocket:
    return socket.create_connection(address, timeout=timeout)


def _read_complete_response(connection: ClamdSocket) -> bytes:
    """Read one newline-terminated clamd response, bounded including framing."""
    response = bytearray()
    while len(response) <= MAX_RESPONSE_BYTES:
        chunk = connection.recv(MAX_RESPONSE_BYTES + 1 - len(response))
        if not chunk:
            return b""
        response.extend(chunk)
        if b"\n" in chunk:
            if response.count(b"\n") != 1 or not response.endswith(b"\n"):
                return b""
            return bytes(response[:-1])
    return b""


def scan_stream(
    *,
    endpoint: str,
    stream: BinaryIO,
    timeout_seconds: float = 30.0,
    chunk_bytes: int = 64 * 1024,
    max_bytes: int = UploadPolicy().max_bytes,
    socket_factory: SocketFactory = _default_socket_factory,
) -> ClamdScanResult:
    """Stream a bounded object using newline-framed clamd INSTREAM."""
    if timeout_seconds <= 0 or timeout_seconds > 120:
        raise ValueError("ClamAV timeout must be between 0 and 120 seconds")
    if chunk_bytes <= 0 or chunk_bytes > 1024 * 1024:
        raise ValueError("ClamAV chunk size must be between 1 byte and 1 MiB")
    if max_bytes <= 0 or max_bytes > UploadPolicy().max_bytes:
        raise ValueError("ClamAV stream cap exceeds upload policy")
    address = parse_private_endpoint(endpoint)
    total = 0
    try:
        connection = socket_factory(address, timeout_seconds)
    except (OSError, TimeoutError):
        return ClamdScanResult(
            verdict=classify_scan_response(b""),
            bytes_streamed=0,
        )
    try:
        connection.sendall(b"nINSTREAM\n")
        while True:
            chunk = stream.read(min(chunk_bytes, max_bytes - total + 1))
            if not chunk:
                break
            if not isinstance(chunk, bytes):
                raise ValueError("ClamAV input stream must return bytes")
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("ClamAV stream exceeds upload policy")
            connection.sendall(struct.pack("!I", len(chunk)))
            connection.sendall(chunk)
        connection.sendall(struct.pack("!I", 0))
        response = _read_complete_response(connection)
        return ClamdScanResult(
            verdict=classify_scan_response(response),
            bytes_streamed=total,
        )
    except (OSError, TimeoutError):
        return ClamdScanResult(
            verdict=classify_scan_response(b""),
            bytes_streamed=total,
        )
    finally:
        try:
            connection.close()
        except OSError:
            pass
