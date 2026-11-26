"""Re-embed every photo for one vision model, alongside the old embeddings.

    python scripts/reindex_embeddings.py --model-id <id> [--tenant <uuid>]
        [--batch-size 50] [--max-per-second 5] [--dry-run] [--inline]

Embeddings are keyed by (media_id, model_id), so a new model's vectors sit
next to the old model's and matching keeps using whichever model it is
configured for until it is switched (docs/runbooks/switch-vision-model.md).

Resumable: only photos with no embedding for the target model are picked,
in id order, so an interrupted run simply starts again where it stopped.
Rate-limited: batches of --batch-size, at most --max-per-second photos.

By default each photo is sent to the `ai` queue as the usual analyze_media
task, which only the ai-worker consumes; the embedding is made by whatever
model that worker has deployed, so --model-id must name it. --inline embeds
in this process instead (run it inside the ai-worker container), and
refuses if this process's model isn't the target. Listing photos across
tenants needs RLS lifted, which is done explicitly with system_session().
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy import text

import app.models  # noqa: F401  (every mapper configured)
from app.core.tenancy import system_session

logger = logging.getLogger("reindex_embeddings")

Embedder = Callable[[uuid.UUID, list[uuid.UUID]], Awaitable[None]]

_PENDING = text(
    """
    SELECT m.id, m.tenant_id FROM media_assets m
    WHERE m.status IN ('processing', 'ready')
      AND m.id > :after
      AND (CAST(:tenant AS uuid) IS NULL OR m.tenant_id = CAST(:tenant AS uuid))
      AND NOT EXISTS (
        SELECT 1 FROM media_embeddings e
        WHERE e.media_id = m.id AND e.model_id = :model
      )
    ORDER BY m.id
    LIMIT :limit
    """
)


@dataclass
class Result:
    seen: int = 0
    batches: int = 0
    per_tenant: dict[uuid.UUID, int] = field(default_factory=lambda: defaultdict(int))


async def pending_batch(
    model_id: str, after: uuid.UUID, limit: int, tenant: uuid.UUID | None
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    async with system_session(reason="reindex embeddings: list photos") as db:
        rows = await db.execute(
            _PENDING,
            {"after": after, "tenant": tenant, "model": model_id, "limit": limit},
        )
        return [(r.id, r.tenant_id) for r in rows]


def queue_embedder() -> Embedder:
    from app.jobs import ANALYZE_MEDIA
    from app.worker import celery_app

    async def send(tenant_id: uuid.UUID, media_ids: list[uuid.UUID]) -> None:
        for media_id in media_ids:  # routed to the `ai` queue by task_routes
            celery_app.send_task(ANALYZE_MEDIA, args=[str(media_id), str(tenant_id)])

    return send


def inline_embedder(model_id: str) -> Embedder:
    from app.domains.ai.analysis import ensure_embeddings, vision_model

    deployed = vision_model().model_id
    if deployed != model_id:
        raise SystemExit(f"this process has model {deployed}, not {model_id}; refusing")

    async def embed(tenant_id: uuid.UUID, media_ids: list[uuid.UUID]) -> None:
        await ensure_embeddings(tenant_id, media_ids)

    return embed


async def reindex(
    model_id: str,
    *,
    embedder: Embedder | None,
    batch_size: int = 50,
    max_per_second: float = 0,
    tenant: uuid.UUID | None = None,
    dry_run: bool = False,
) -> Result:
    """Walk the photos lacking an embedding for model_id in id order and
    hand each batch to the embedder (grouped by tenant). With dry_run the
    embedder is never called and nothing is written."""
    result = Result()
    after = uuid.UUID(int=0)
    started = time.monotonic()
    while True:
        batch = await pending_batch(model_id, after, batch_size, tenant)
        if not batch:
            break
        after = batch[-1][0]
        result.batches += 1
        by_tenant: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for media_id, tenant_id in batch:
            by_tenant[tenant_id].append(media_id)
        for tenant_id, ids in by_tenant.items():
            result.per_tenant[tenant_id] += len(ids)
            if not dry_run and embedder is not None:
                await embedder(tenant_id, ids)
        result.seen += len(batch)
        logger.info("batch %d: %d photos (total %d)", result.batches, len(batch), result.seen)
        if max_per_second > 0 and not dry_run:
            ahead = result.seen / max_per_second - (time.monotonic() - started)
            if ahead > 0:
                await asyncio.sleep(ahead)
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "Re-embed photos").splitlines()[0])
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--tenant", type=uuid.UUID)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--max-per-second", type=float, default=5.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--inline", action="store_true", help="embed in this process")
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    embedder = None
    if not args.dry_run:
        embedder = inline_embedder(args.model_id) if args.inline else queue_embedder()
    result = asyncio.run(
        reindex(
            args.model_id,
            embedder=embedder,
            batch_size=args.batch_size,
            max_per_second=args.max_per_second,
            tenant=args.tenant,
            dry_run=args.dry_run,
        )
    )
    verb = "would embed" if args.dry_run else ("embedded" if args.inline else "queued")
    print(f"{verb} {result.seen} photos in {result.batches} batches for {args.model_id}")
    for tenant_id, count in result.per_tenant.items():
        print(f"  tenant {tenant_id}: {count}")


if __name__ == "__main__":
    main()
