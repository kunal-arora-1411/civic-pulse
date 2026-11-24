"""The reindex script: resumable, tenant-scoped, dry-run, old vectors kept."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.fake import FAKE_MODEL_ID, make_scene
from scripts.reindex_embeddings import inline_embedder, reindex
from tests.phase1 import City, make_city, ready_media_id


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


async def _photos(client: httpx.AsyncClient, city: City, n: int) -> list[str]:
    return [await ready_media_id(client, city.citizen, make_scene(500 + i)) for i in range(n)]


async def _embedded(engine: AsyncEngine, model_id: str, city: City) -> set[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT media_id::text FROM media_embeddings WHERE model_id = :m AND tenant_id = :t"
            ),
            {"m": model_id, "t": city.tenant.id},
        )
        return {r[0] for r in rows}


async def _reset(engine: AsyncEngine, city: City) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM media_embeddings WHERE tenant_id = :t"), {"t": city.tenant.id}
        )


async def test_reindex_embeds_every_photo_and_resumes(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    ids = await _photos(client, city, 5)
    await _reset(owner_engine, city)

    dry = await reindex(
        FAKE_MODEL_ID, tenant=city.tenant.id, embedder=None, batch_size=2, dry_run=True
    )
    assert dry.seen == 5
    assert dry.batches == 3
    assert await _embedded(owner_engine, FAKE_MODEL_ID, city) == set()

    calls: list[list[uuid.UUID]] = []
    real = inline_embedder(FAKE_MODEL_ID)

    async def stop_after_first(tenant_id: uuid.UUID, media_ids: list[uuid.UUID]) -> None:
        if calls:
            raise RuntimeError("interrupted")
        calls.append(media_ids)
        await real(tenant_id, media_ids)

    with pytest.raises(RuntimeError):
        await reindex(FAKE_MODEL_ID, tenant=city.tenant.id, embedder=stop_after_first, batch_size=2)
    assert len(await _embedded(owner_engine, FAKE_MODEL_ID, city)) == 2

    # The rerun skips what is done and finishes the rest, in id order.
    seen: list[uuid.UUID] = []

    async def record(tenant_id: uuid.UUID, media_ids: list[uuid.UUID]) -> None:
        seen.extend(media_ids)
        await real(tenant_id, media_ids)

    rerun = await reindex(
        FAKE_MODEL_ID, tenant=city.tenant.id, embedder=record, batch_size=2, max_per_second=1000
    )
    assert rerun.seen == 3
    assert seen == sorted(seen)
    assert await _embedded(owner_engine, FAKE_MODEL_ID, city) == set(ids)
    assert (await reindex(FAKE_MODEL_ID, tenant=city.tenant.id, embedder=record)).seen == 0


async def test_new_model_sits_beside_the_old_and_tenant_filter_applies(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    ids = await _photos(client, city, 2)
    await _reset(owner_engine, city)
    await reindex(FAKE_MODEL_ID, tenant=city.tenant.id, embedder=inline_embedder(FAKE_MODEL_ID))

    other_tenant = uuid.uuid4()
    scoped = await reindex("next-model@2", embedder=None, tenant=other_tenant, dry_run=True)
    assert scoped.seen == 0
    pending = await reindex("next-model@2", embedder=None, tenant=city.tenant.id, dry_run=True)
    assert pending.seen == 2  # nothing for the new model yet; old vectors untouched
    assert await _embedded(owner_engine, FAKE_MODEL_ID, city) == set(ids)


def test_inline_refuses_a_model_this_process_does_not_have() -> None:
    with pytest.raises(SystemExit):
        inline_embedder("some-other-model@1")
