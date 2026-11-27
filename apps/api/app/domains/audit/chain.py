"""The canonical framing and hashing of one audit row (mirror of `audit_framing_v1`).

Migration 0017 defines the framing in SQL, because the append trigger needs it at
INSERT time and must chain rows written by raw SQL too. This module is the same
definition in Python, so that a verifier can recompute a hash without trusting
the database's own function -- which is the point of an independent check: if
somebody rewrote `audit_hash_v1`, `db`-mode verification would happily agree with
them, and only a second implementation catches it.

The two must produce identical bytes. `tests/test_audit_chain_framing.py`
compares them against `tests/fixtures/audit_chain_v1.json`, which pins the exact
framing of twenty rows. Do not regenerate that fixture to make a failing test
pass: a change in it is either a bug here or a deliberate new framing version.

The layout is

    civicpulse.audit.v1|prev:<hex>|tenant:<f>|seq:<f>|occurred_at_us:<f>|actor:<f>
    |action:<f>|entity_type:<f>|entity_id:<f>|before:<f>|after:<f>|request_id:<f>
    |ip:<f>|user_agent:<f>

where a field is `~` for NULL, or `N:<value>` with N the octet length of the
value. The length prefix is what makes the encoding injective: without it,
`action='a|b'` would frame like `action='a'` alongside `ip='b'`, and one row
could be made to look like another.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

DOMAIN_TAG = "civicpulse.audit.v1"
HASH_SIZE = 32
#: `prev_hash` of the first event in a chain.
GENESIS_HASH = b"\x00" * HASH_SIZE
#: The fields of the framing, in order, as the `row` mapping spells them.
FIELDS = (
    "tenant_id",
    "chain_seq",
    "occurred_at",
    "actor_id",
    "action",
    "entity_type",
    "entity_id",
    "before_text",
    "after_text",
    "request_id",
    "ip",
    "user_agent",
)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_MICROSECOND = timedelta(microseconds=1)
_NULL = "~"


def micros(moment: datetime) -> int:
    """Whole microseconds since the Unix epoch.

    `int(moment.timestamp() * 1_000_000)` would be wrong: `timestamp()` returns a
    float and loses the last digits. Integer division of a timedelta is exact, and
    it matches `(extract(epoch from ...) * 1000000)::bigint` in SQL.
    """
    if moment.tzinfo is None:
        raise ValueError("occurred_at must be timezone-aware")
    return (moment.astimezone(UTC) - _EPOCH) // _ONE_MICROSECOND


def field(value: str | None) -> str:
    """One length-prefixed field, or the NULL token."""
    if value is None:
        return _NULL
    return f"{len(value.encode('utf-8'))}:{value}"


def framing(row: Mapping[str, Any]) -> bytes:
    """The exact bytes that are hashed for one row.

    `row` carries the values as the database renders them, which means
    `before_text` / `after_text` are Postgres's `jsonb::text` output and not a
    re-serialisation: jsonb normalises key order at storage time, so its
    rendering is stable for a value and any change to the value changes it.
    """
    missing = [name for name in FIELDS if name not in row]
    if missing:
        raise KeyError(f"framing needs every column; missing {', '.join(missing)}")

    prev = row["prev_hash"]
    if not isinstance(prev, bytes | bytearray) or len(prev) != HASH_SIZE:
        raise ValueError("prev_hash must be 32 bytes")

    tenant = row["tenant_id"]
    actor = row["actor_id"]
    parts = [
        DOMAIN_TAG,
        "prev:" + bytes(prev).hex(),
        "tenant:" + (str(tenant) if tenant else _NULL),
        "seq:" + str(row["chain_seq"]),
        "occurred_at_us:" + str(micros(row["occurred_at"])),
        "actor:" + (str(actor) if actor else _NULL),
        "action:" + field(row["action"]),
        "entity_type:" + field(row["entity_type"]),
        "entity_id:" + field(row["entity_id"]),
        "before:" + field(row["before_text"]),
        "after:" + field(row["after_text"]),
        "request_id:" + field(row["request_id"]),
        "ip:" + field(row["ip"]),
        "user_agent:" + field(row["user_agent"]),
    ]
    return "|".join(parts).encode("utf-8")


def hash_row(row: Mapping[str, Any]) -> bytes:
    """The SHA-256 a stored row must carry (`audit_hash_v1`)."""
    return hashlib.sha256(framing(row)).digest()


def hex_hash(value: bytes) -> str:
    """The form API responses and CLI lines use."""
    return value.hex()
