"""Malware scanning of uploads with ClamAV (P6-07).

Talks to clamd's INSTREAM command over plain TCP, so there's no client
library to depend on: the command, then the file in length-prefixed chunks,
then a zero-length chunk, and one reply line back.

Scanning is off unless CLAMAV_HOST is set. When it is set, an unreachable
or misbehaving scanner is an error, never a pass: an upload that can't be
scanned isn't accepted (the caller answers 503 and the upload stays pending,
so completing it again later works).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import log_fields

logger = logging.getLogger(__name__)

CHUNK_SIZE = 64 * 1024
MAX_REPLY_BYTES = 4096


class ScannerUnavailable(Exception):
    """The scanner couldn't give a verdict."""


@dataclass(frozen=True, slots=True)
class ScanResult:
    clean: bool
    signature: str | None = None


def parse_reply(reply: bytes) -> ScanResult:
    """Interpret clamd's reply to INSTREAM, e.g. `stream: OK`."""
    text = reply.rstrip(b"\0\n").decode("utf-8", errors="replace").strip()
    if text.endswith(" FOUND"):
        signature = text.removeprefix("stream:").removesuffix(" FOUND").strip()
        return ScanResult(clean=False, signature=signature or "unknown")
    if text == "stream: OK":
        return ScanResult(clean=True)
    # "INSTREAM size limit exceeded. ERROR", "... ERROR", or anything else.
    raise ScannerUnavailable(text or "empty reply")


async def scan_bytes(data: bytes, *, host: str, port: int, time_limit: float) -> ScanResult:
    """Send `data` to clamd and return its verdict."""
    try:
        async with asyncio.timeout(time_limit):
            reader, writer = await asyncio.open_connection(host, port)
            try:
                writer.write(b"zINSTREAM\0")
                for start in range(0, len(data), CHUNK_SIZE):
                    chunk = data[start : start + CHUNK_SIZE]
                    writer.write(struct.pack("!I", len(chunk)) + chunk)
                    await writer.drain()
                writer.write(struct.pack("!I", 0))
                await writer.drain()
                reply = await reader.read(MAX_REPLY_BYTES)
            finally:
                writer.close()
                with contextlib.suppress(OSError):
                    await writer.wait_closed()
    except (OSError, TimeoutError) as exc:
        raise ScannerUnavailable(repr(exc)) from exc
    return parse_reply(reply)


async def scan_upload(data: bytes, *, media_id: str) -> ScanResult:
    """Scan with the configured clamd; clean without asking when disabled."""
    settings = get_settings()
    if not settings.clamav_host:
        return ScanResult(clean=True)
    try:
        result = await scan_bytes(
            data,
            host=settings.clamav_host,
            port=settings.clamav_port,
            time_limit=settings.clamav_timeout_seconds,
        )
    except ScannerUnavailable as exc:
        logger.error(
            "malware scanner unavailable", extra=log_fields(media_id=media_id, error=str(exc))
        )
        raise
    if not result.clean:
        logger.warning(
            "malware found in upload",
            extra=log_fields(media_id=media_id, signature=result.signature),
        )
    return result
