"""The framing and its Python mirror must be the same function.

`audit_framing_v1` lives in Postgres (the append trigger needs it), and
`app.domains.audit.chain` mirrors it (an independent verifier must not trust the
database's own hash). A one-byte disagreement between them makes every chain
unverifiable, so the fixture in tests/fixtures/audit_chain_v1.json pins the exact
framing and hash of sample rows and both implementations are checked against it.
"""

from __future__ import annotations

import json
import pathlib
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domains.audit import chain

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "audit_chain_v1.json"
GENESIS = bytes(32)

FRAMING_SQL = text(
    """
    SELECT audit_framing_v1(:prev, :tenant, :seq, :occurred, :actor, :action,
                            :entity_type, :entity_id, :before, :after,
                            :request_id, :ip, :user_agent) AS framing,
           encode(audit_hash_v1(:prev, :tenant, :seq, :occurred, :actor, :action,
                                :entity_type, :entity_id, :before, :after,
                                :request_id, :ip, :user_agent), 'hex') AS digest
    """
)


@pytest.fixture(scope="module")
def rows() -> list[dict[str, Any]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["rows"]


def _py_row(inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "prev_hash": bytes.fromhex(inputs["prev_hash"]),
        "tenant_id": uuid.UUID(inputs["tenant_id"]) if inputs["tenant_id"] else None,
        "chain_seq": inputs["chain_seq"],
        "occurred_at": datetime.fromisoformat(inputs["occurred_at"]),
        "actor_id": uuid.UUID(inputs["actor_id"]) if inputs["actor_id"] else None,
        "action": inputs["action"],
        "entity_type": inputs["entity_type"],
        "entity_id": inputs["entity_id"],
        "before_text": inputs["before_text"],
        "after_text": inputs["after_text"],
        "request_id": inputs["request_id"],
        "ip": inputs["ip"],
        "user_agent": inputs["user_agent"],
    }


def _sql_params(py_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "prev": py_row["prev_hash"],
        "tenant": py_row["tenant_id"],
        "seq": py_row["chain_seq"],
        "occurred": py_row["occurred_at"],
        "actor": py_row["actor_id"],
        "action": py_row["action"],
        "entity_type": py_row["entity_type"],
        "entity_id": py_row["entity_id"],
        # The column is jsonb; the canonical text is what gets framed.
        "before": py_row["before_text"],
        "after": py_row["after_text"],
        "request_id": py_row["request_id"],
        "ip": py_row["ip"],
        "user_agent": py_row["user_agent"],
    }


def test_the_fixture_covers_the_interesting_shapes(rows: list[dict[str, Any]]) -> None:
    inputs = [row["inputs"] for row in rows]
    assert len(rows) >= 19
    assert any(i["tenant_id"] is None for i in inputs), "the platform chain"
    assert any(i["before_text"] is None for i in inputs), "a null payload"
    assert any(i["before_text"] is None for i in inputs), "a null payload"
    # An empty string is a JSON string, so its canonical jsonb text is `""`.
    assert any(i["before_text"] == '""' for i in inputs), "an empty payload"
    assert any("|" in (i["action"] or "") for i in inputs), "a delimiter in a field"
    assert any("\u092e" in (i["action"] or "") for i in inputs), "a multi-byte field"
    assert any(len(i["user_agent"] or "") == 400 for i in inputs), "a maximum-length field"


def test_python_reproduces_every_pinned_framing(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        py_row = _py_row(row["inputs"])
        assert chain.framing(py_row).decode() == row["framing"], row["inputs"]["chain_seq"]
        assert chain.hash_row(py_row).hex() == row["hash"], row["inputs"]["chain_seq"]


async def test_sql_reproduces_every_pinned_framing(
    owner_engine: AsyncEngine, rows: list[dict[str, Any]]
) -> None:
    async with owner_engine.connect() as conn:
        for row in rows:
            result = (await conn.execute(FRAMING_SQL, _sql_params(_py_row(row["inputs"])))).one()
            assert result.framing == row["framing"], row["inputs"]["chain_seq"]
            assert result.digest == row["hash"], row["inputs"]["chain_seq"]


async def test_the_two_implementations_agree_on_a_live_row(
    owner_engine: AsyncEngine,
) -> None:
    """Not just on the fixture: on a row the trigger actually chained."""
    async with owner_engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    "INSERT INTO audit_events "
                    "(tenant_id, action, entity_type, before, after, request_id) "
                    "VALUES (NULL, 'framing.live', 'test', '{\"a\": 1}'::jsonb, "
                    "'{\"b\": [1, 2]}'::jsonb, 'req-live') "
                    "RETURNING tenant_id, chain_seq, prev_hash, hash, occurred_at, actor_id, "
                    "action, entity_type, entity_id, before::text AS before_text, "
                    "after::text AS after_text, request_id, ip, user_agent"
                )
            )
        ).one()

    assert row.hash == chain.hash_row(dict(row._mapping)), (
        f"row {row.chain_seq} does not recompute in Python"
    )
    assert row.before_text == '{"a": 1}', "the canonical jsonb text is what is framed"


def test_a_shifted_boundary_frames_differently() -> None:
    """Without length prefixes these two rows would hash the same."""
    base = {
        "prev_hash": GENESIS,
        "tenant_id": None,
        "chain_seq": 1,
        "occurred_at": datetime(2026, 1, 1, tzinfo=UTC),
        "actor_id": None,
        "entity_type": "t",
        "entity_id": None,
        "before_text": None,
        "after_text": None,
        "request_id": None,
        "ip": None,
        "user_agent": None,
    }
    shifted = dict(base, action="a|b", ip=None)
    split = dict(base, action="a", ip="b")
    assert chain.framing(shifted) != chain.framing(split)


def test_null_and_empty_are_different() -> None:
    base = {
        "prev_hash": GENESIS,
        "tenant_id": None,
        "chain_seq": 1,
        "occurred_at": datetime(2026, 1, 1, tzinfo=UTC),
        "actor_id": None,
        "action": "a",
        "entity_type": "t",
        "entity_id": None,
        "before_text": None,
        "after_text": None,
        "request_id": None,
        "ip": None,
        "user_agent": None,
    }
    assert chain.framing(base) != chain.framing(dict(base, entity_id=""))
    assert "|entity_id:~|" in chain.framing(base).decode()
    assert "|entity_id:0:|" in chain.framing(dict(base, entity_id="")).decode()


def test_unicode_is_counted_in_octets() -> None:
    row = {
        "prev_hash": GENESIS,
        "tenant_id": None,
        "chain_seq": 1,
        "occurred_at": datetime(2026, 1, 1, tzinfo=UTC),
        "actor_id": None,
        "action": "ab",
        "entity_type": "t",
        "entity_id": "\u092e\u0941",
        "before_text": None,
        "after_text": None,
        "request_id": None,
        "ip": None,
        "user_agent": None,
    }
    # Two Devanagari characters are six UTF-8 bytes, not two.
    assert "|entity_id:6:\u092e\u0941|" in chain.framing(row).decode()


def test_microseconds_are_exact() -> None:
    moment = datetime(2026, 2, 1, 10, 0, 0, 123456, tzinfo=UTC)
    assert chain.micros(moment) == 1_769_940_000_123_456
    assert chain.micros(datetime(1970, 1, 1, tzinfo=UTC)) == 0
    assert chain.micros(datetime(1969, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)) == -1
    # An offset does not change the instant.
    from datetime import timedelta, timezone

    ist = moment.astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert chain.micros(ist) == chain.micros(moment)


def test_a_naive_timestamp_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        chain.micros(datetime(2026, 1, 1))  # noqa: DTZ001 -- the point of the test


def test_a_missing_column_is_named_in_the_error() -> None:
    with pytest.raises(KeyError, match="entity_id"):
        chain.framing({"prev_hash": GENESIS})


def test_a_prev_hash_of_the_wrong_length_is_refused() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        chain.framing(
            {
                "prev_hash": b"short",
                "tenant_id": None,
                "chain_seq": 1,
                "occurred_at": datetime(2026, 1, 1, tzinfo=UTC),
                "actor_id": None,
                "action": "a",
                "entity_type": "t",
                "entity_id": None,
                "before_text": None,
                "after_text": None,
                "request_id": None,
                "ip": None,
                "user_agent": None,
            }
        )
