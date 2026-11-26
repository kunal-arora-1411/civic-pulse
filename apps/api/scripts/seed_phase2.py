"""Phase 2 development seed: places, rules, configs and matching examples.

Called from scripts/seed.py after the Phase 1 seed. Everything is SYNTHETIC.

* Severity rules for the five categories.
* Schools and hospitals near some seeded issues, so the severity raise
  and the priority factor show up in the data.
* The default matching and priority configuration, stored explicitly.
* Embeddings for every seeded photo, with the vision model this process
  has, which must be the AI worker's: in the compose stack the seed runs
  in the ai-worker container, and it refuses to embed with another model.
* Three duplicate clusters: extra reports a few metres from an open issue
  with a near-identical photo. They go through the real matcher and are
  linked automatically, so their match decisions are genuine.
* Two open review tasks: the same kind of report, twenty metres away,
  which the matcher sends to a person.
* Severity and priority recomputed for every issue.

Idempotent: reports and places have deterministic ids, a report that exists
is not created again (one left pending by an interrupted run is matched),
and configs are only written when missing.
"""

from __future__ import annotations

import hashlib
import io
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from geoalchemy2 import WKTElement
from PIL import Image
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.ai.registry import get_vision_model
from app.core.storage import get_storage
from app.core.tenancy import system_session
from app.domains.ai.analysis import (
    check_faces,
    ensure_embeddings,
    ensure_registered,
    refresh_phashes,
)
from app.domains.ai.models import ModelRegistryEntry, ModelTask
from app.domains.categories.models import Category
from app.domains.config.models import ConfigKey, TenantConfig
from app.domains.config.schemas import MatchingConfig, PriorityConfig
from app.domains.issues.models import ReferenceKind
from app.domains.issues.references import allocate
from app.domains.matching.service import process_report
from app.domains.media.models import MediaAsset, MediaPurpose, MediaStatus
from app.domains.media.processing import process_asset
from app.domains.media.service import object_key
from app.domains.places.models import PlaceOfInterest
from app.domains.priority.service import recompute_tenant
from app.domains.reports.models import MatchingStatus, Report, ReportStatus
from scripts import seed_phase1 as phase1

METERS_PER_DEGREE_LAT = 111_320.0

SEVERITY_RULES: dict[str, dict] = {
    "pothole": {
        "base": "medium",
        "field_rules": [
            {"field": "size", "equals": "large", "set": "high"},
            {"field": "size", "equals": "small", "set": "low"},
        ],
        "near_places": [{"kinds": ["school", "hospital"], "within_m": 150, "raise_by": 1}],
        "report_count_raise": [{"unique_reporters_gte": 3, "raise_by": 1}],
    },
    "waste": {
        "base": "low",
        "field_rules": [{"field": "blocking_road", "equals": True, "set": "medium"}],
        "near_places": [
            {"kinds": ["school", "hospital", "market"], "within_m": 100, "raise_by": 1}
        ],
        "report_count_raise": [{"unique_reporters_gte": 5, "raise_by": 1}],
    },
    "waterlogging": {
        "base": "medium",
        "field_rules": [
            {"field": "depth", "equals": "knee", "set": "high"},
            {"field": "depth", "equals": "waist", "set": "critical"},
        ],
        "near_places": [{"kinds": ["hospital"], "within_m": 200, "raise_by": 1}],
        "report_count_raise": [],
    },
    "streetlight": {
        "base": "low",
        "field_rules": [],
        "near_places": [{"kinds": ["school", "bus_stop"], "within_m": 100, "raise_by": 1}],
        "report_count_raise": [{"unique_reporters_gte": 3, "raise_by": 1}],
    },
    "drainage": {
        "base": "medium",
        "field_rules": [{"field": "cover_missing", "equals": True, "set": "high"}],
        "near_places": [{"kinds": ["school"], "within_m": 150, "raise_by": 2}],
        "report_count_raise": [],
    },
}


@dataclass(frozen=True)
class Place:
    key: str
    kind: str
    name: str
    near_issue: int  # placed close to this planned issue
    offset_m: float


PLACES = [
    Place("school-1", "school", "Synthetic Government School No. 1", 0, 60),
    Place("school-2", "school", "Synthetic Public School, Ward 2", 13, 90),
    Place("hospital-1", "hospital", "Synthetic District Hospital", 7, 120),
    Place("hospital-2", "hospital", "Synthetic Community Health Centre", 24, 40),
    Place("market-1", "market", "Synthetic Vegetable Market", 21, 70),
    Place("bus-stop-1", "bus_stop", "Synthetic Bus Stop, Main Road", 3, 30),
]


@dataclass(frozen=True)
class Extra:
    """A synthetic report placed relative to a seeded issue."""

    key: str
    issue: int  # index of the seeded issue it describes
    north_m: float
    reporter: int  # 0: the seeded citizen, 1 and 2: the extra citizens
    hours_later: int


# Open issues (STATUS_CYCLE positions 0-4 are `reported`). A few metres away
# with a near-identical photo: linked automatically.
CLUSTERS = [
    Extra("cluster-0a", 0, 3.0, 1, 5),
    Extra("cluster-0b", 0, -2.0, 2, 30),
    Extra("cluster-11a", 11, 2.5, 1, 8),
    Extra("cluster-22a", 22, 1.5, 0, 4),  # the same citizen again: no new reporter
    Extra("cluster-22b", 22, 3.5, 2, 20),
]
# Twenty metres away with a near-identical photo: sent to review.
REVIEWS = [
    Extra("review-33", 33, 20.0, 1, 6),
    Extra("review-44", 44, 21.0, 2, 9),
]


def _moved(lng: float, lat: float, north_m: float, east_m: float = 0.0) -> tuple[float, float]:
    dlat = north_m / METERS_PER_DEGREE_LAT
    dlng = east_m / (METERS_PER_DEGREE_LAT * math.cos(math.radians(lat)))
    return round(lng + dlng, 7), round(lat + dlat, 7)


def near_identical(data: bytes, n: int) -> bytes:
    """Another shot of the same scene: slightly brighter, a little noise."""
    image = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.float64)
    rng = np.random.default_rng(n)
    image = image * (1.0 + 0.015 * (n % 3 + 1)) + rng.normal(0, 2.0, image.shape)
    buffer = io.BytesIO()
    Image.fromarray(np.clip(image, 0, 255).astype(np.uint8)).save(buffer, "JPEG", quality=82)
    return buffer.getvalue()


async def check_vision_model() -> None:
    """Refuse to seed with another vision model than the AI worker's.

    Seeded photos are embedded, and embeddings are only ever compared
    within one model, so with any other model no new report could match a
    seeded issue. Registers this process's model if none is yet.
    """
    model = get_vision_model()
    async with system_session(reason="development seed: vision model") as db:
        active = await db.scalar(
            select(ModelRegistryEntry.id)
            .where(ModelRegistryEntry.task == ModelTask.EMBEDDING)
            .order_by(ModelRegistryEntry.deployed_at.desc(), ModelRegistryEntry.id)
            .limit(1)
        )
        if active is not None and active != model.model_id:
            raise SystemExit(
                f"The AI worker runs {active}, but this process would embed the seeded "
                f"photos with {model.model_id}. Run the seed in the ai-worker container:\n"
                "  docker compose -f infra/docker-compose.yml exec -T ai-worker "
                "python scripts/seed.py"
            )
        await ensure_registered(db, model)


async def seed_rules_places_configs(
    tenant_id: uuid.UUID, wards: dict[uuid.UUID, tuple[float, float, float, float]]
) -> int:
    planned = phase1.plan(wards)
    async with system_session(reason="development seed: phase 2 config") as db:
        for code, rules in SEVERITY_RULES.items():
            category = await db.scalar(
                select(Category).where(Category.tenant_id == tenant_id, Category.code == code)
            )
            if category is not None:
                category.severity_rules = rules
        for place in PLACES:
            issue = planned[place.near_issue]
            lng, lat = _moved(issue.lng, issue.lat, place.offset_m, place.offset_m / 2)
            values = {
                "kind": place.kind,
                "name": place.name,
                "geom": WKTElement(f"POINT({lng} {lat})", srid=4326),
            }
            await db.execute(
                pg_insert(PlaceOfInterest)
                .values(id=phase1.seed_id(f"place/{place.key}", 0), tenant_id=tenant_id, **values)
                .on_conflict_do_update(index_elements=[PlaceOfInterest.id], set_=values)
            )
        for key, config in (
            (ConfigKey.MATCHING, MatchingConfig()),
            (ConfigKey.PRIORITY, PriorityConfig()),
        ):
            await db.execute(
                pg_insert(TenantConfig)
                .values(tenant_id=tenant_id, key=key.value, value=config.model_dump(mode="json"))
                .on_conflict_do_nothing(constraint="pk_tenant_configs")
            )
    return len(PLACES)


async def _ensure_extra(
    tenant_id: uuid.UUID,
    extra: Extra,
    planned: list[phase1.PlannedIssue],
    categories: dict[str, uuid.UUID],
    ward_ids: list[uuid.UUID],
    reporters: list[uuid.UUID],
) -> uuid.UUID:
    """Create the report (pending, with its photo) unless it exists."""
    report_id = phase1.seed_id(f"report/{extra.key}", 0)
    media_id = phase1.seed_id(f"media/{extra.key}", 0)
    issue = planned[extra.issue]
    created_at = issue.created_at + timedelta(hours=extra.hours_later)
    base = phase1.photo_bytes(issue.index, issue.category.code)
    data = near_identical(base, int(hashlib.sha256(extra.key.encode()).hexdigest(), 16) % 97 + 1)
    checksum = hashlib.sha256(data).hexdigest()
    key = object_key(tenant_id, media_id, "original.jpg")
    async with system_session(reason="development seed: matching examples") as db:
        existing = await db.get(MediaAsset, media_id)
        if (
            existing is not None
            and existing.checksum_sha256 == checksum
            and existing.status == MediaStatus.READY
        ):
            return report_id
        await get_storage().write(key, data, content_type="image/jpeg")
        values = {
            "status": MediaStatus.PROCESSING,
            "content_type": "image/jpeg",
            "declared_size_bytes": len(data),
            "size_bytes": len(data),
            "checksum_sha256": checksum,
            "storage_key": key,
            "width": 1200,
            "height": 900,
            "upload_expires_at": created_at,
            "verified_at": created_at,
            # Stale copies from the previous bytes; cleared so they are remade.
            "processed_at": None,
            "faces_checked_at": None,
            "thumb_key": None,
            "display_key": None,
        }
        if existing is not None:
            # The photo set changed underneath us: same asset, new bytes.
            await db.execute(update(MediaAsset).where(MediaAsset.id == media_id).values(**values))
        else:
            db.add(
                MediaAsset(
                    id=media_id,
                    tenant_id=tenant_id,
                    owner_id=reporters[extra.reporter],
                    purpose=MediaPurpose.REPORT_EVIDENCE,
                    created_at=created_at,
                    **values,
                )
            )
            await db.flush()
        if await db.scalar(select(Report.id).where(Report.id == report_id)) is None:
            lng, lat = _moved(issue.lng, issue.lat, extra.north_m)
            location = WKTElement(f"POINT({lng} {lat})", srid=4326)
            db.add(
                Report(
                    id=report_id,
                    tenant_id=tenant_id,
                    reference=await allocate(db, tenant_id, ReferenceKind.REPORT),
                    reporter_id=reporters[extra.reporter],
                    category_id=categories[issue.category.code],
                    issue_id=None,
                    matching_status=MatchingStatus.PENDING,
                    status=ReportStatus.ACCEPTED,
                    description=f"{issue.description} (another report)",
                    details={},
                    location=location,
                    location_accuracy_m=8.0,
                    location_source="gps",
                    address_text=issue.address,
                    ward_id=ward_ids[issue.index % len(ward_ids)],
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            await db.flush()
        media = await db.get(MediaAsset, media_id)
        assert media is not None
        media.report_id = report_id
        media.position = 0
    await process_asset(media_id, tenant_id)
    await check_faces(media_id, tenant_id)
    return report_id


async def _state(report_id: uuid.UUID) -> tuple[str, datetime]:
    async with system_session(reason="development seed: report state") as db:
        report = await db.get(Report, report_id)
        assert report is not None
        return report.matching_status, report.created_at


async def seed_matching_examples(
    *,
    tenant_id: uuid.UUID,
    categories: dict[str, uuid.UUID],
    wards: dict[uuid.UUID, tuple[float, float, float, float]],
    reporters: list[uuid.UUID],
) -> dict[str, int]:
    planned = phase1.plan(wards)
    ward_ids = list(wards)
    # Every seeded photo gets an embedding, so new reports can match them.
    async with system_session(reason="development seed: photo ids") as db:
        seeded_media = [
            phase1.seed_id("media", issue.index)
            for issue in planned
            if await db.get(MediaAsset, phase1.seed_id("media", issue.index)) is not None
        ]
    # A database seeded before the real pHash existed holds difference
    # hashes; bring those rows up to date before anything is matched.
    await refresh_phashes(tenant_id)
    await ensure_embeddings(tenant_id, seeded_media)

    outcomes: dict[str, int] = {}
    for extra in [*CLUSTERS, *REVIEWS]:
        report_id = await _ensure_extra(tenant_id, extra, planned, categories, ward_ids, reporters)
        status, created_at = await _state(report_id)
        if status == MatchingStatus.PENDING:
            await process_report(report_id, tenant_id, now=created_at + timedelta(minutes=1))
            status, _ = await _state(report_id)
        outcomes[status] = outcomes.get(status, 0) + 1
    await recompute_tenant(tenant_id)
    return outcomes
