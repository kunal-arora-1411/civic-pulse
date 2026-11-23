"""Phase 1 development seed: categories and ~60 synthetic issues.

Called from scripts/seed.py. Everything here is SYNTHETIC: placeholder
photos are flat colours with "SYNTHETIC" written on them, descriptions and
addresses are invented, and every report comes from the seeded citizen.

Idempotent: categories are upserted by code, and each synthetic issue,
report and photo has a deterministic id, so a re-run skips whatever already
exists (and finishes processing any photo a previous run left behind).
"""

from __future__ import annotations

import hashlib
import io
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from geoalchemy2 import WKTElement
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_storage
from app.core.tenancy import system_session
from app.domains.categories.models import Category
from app.domains.issues.models import (
    CivicIssue,
    EventType,
    IssueEvent,
    ReferenceKind,
    Visibility,
)
from app.domains.issues.references import allocate
from app.domains.media.models import MediaAsset, MediaPurpose, MediaStatus
from app.domains.media.processing import process_asset
from app.domains.media.service import object_key
from app.domains.reports.models import Report, ReportStatus
from app.domains.workflow.statuses import IssueStatus

ISSUE_COUNT = 60
SEED_NAMESPACE = uuid.UUID("6c1d2f0e-6a43-4c55-9d38-0b6c5e5d1a01")


def _label(en: str, hi: str) -> dict[str, str]:
    return {"en": en, "hi": hi}


def _option(value: str, en: str, hi: str) -> dict[str, Any]:
    return {"value": value, "label_i18n": _label(en, hi)}


@dataclass(frozen=True)
class SeedCategory:
    code: str
    name: dict[str, str]
    description: dict[str, str]
    icon: str
    department: str
    sort_order: int
    fields: list[dict[str, Any]]
    color: tuple[int, int, int]
    min_photos: int = 1
    max_photos: int = 5


CATEGORIES = [
    SeedCategory(
        code="pothole",
        name=_label("Pothole / road damage", "गड्ढा / सड़क क्षति"),
        description=_label(
            "Potholes, cracks or broken road surface.", "सड़क में गड्ढे, दरारें या टूटी सतह।"
        ),
        icon="construction",
        department="ROADS",
        sort_order=10,
        color=(176, 96, 52),
        fields=[
            {
                "key": "road_name",
                "type": "text",
                "required": False,
                "label_i18n": _label("Road name", "सड़क का नाम"),
            },
            {
                "key": "size",
                "type": "select",
                "required": False,
                "label_i18n": _label("Size", "आकार"),
                "options": [
                    _option("small", "Small", "छोटा"),
                    _option("medium", "Medium", "मध्यम"),
                    _option("large", "Large", "बड़ा"),
                ],
            },
        ],
    ),
    SeedCategory(
        code="waste",
        name=_label("Garbage / waste accumulation", "कचरा / कूड़े का ढेर"),
        description=_label(
            "Uncollected garbage, overflowing bins or dumping.",
            "कचरा न उठाया जाना, भरे हुए कूड़ेदान या अवैध डंपिंग।",
        ),
        icon="trash-2",
        department="SOLID_WASTE",
        sort_order=20,
        color=(84, 130, 53),
        fields=[
            {
                "key": "waste_type",
                "type": "select",
                "required": False,
                "label_i18n": _label("Type of waste", "कचरे का प्रकार"),
                "options": [
                    _option("household", "Household", "घरेलू"),
                    _option("construction", "Construction debris", "निर्माण मलबा"),
                    _option("mixed", "Mixed", "मिश्रित"),
                ],
            },
            {
                "key": "blocking_road",
                "type": "boolean",
                "required": False,
                "label_i18n": _label("Blocking the road?", "क्या सड़क अवरुद्ध है?"),
            },
        ],
    ),
    SeedCategory(
        code="waterlogging",
        name=_label("Waterlogging", "जलभराव"),
        description=_label("Standing water on roads or footpaths.", "सड़कों या फुटपाथ पर जमा पानी।"),
        icon="waves",
        department="STORM_WATER_DRAINS",
        sort_order=30,
        color=(46, 117, 182),
        fields=[
            {
                "key": "depth",
                "type": "select",
                "required": False,
                "label_i18n": _label("Water depth", "पानी की गहराई"),
                "options": [
                    _option("ankle", "Ankle deep", "टखने तक"),
                    _option("knee", "Knee deep", "घुटने तक"),
                    _option("waist", "Waist deep", "कमर तक"),
                ],
            },
        ],
    ),
    SeedCategory(
        code="streetlight",
        name=_label("Streetlight not working", "स्ट्रीटलाइट खराब"),
        description=_label(
            "Streetlights that are off, flickering or damaged.",
            "बंद, टिमटिमाती या क्षतिग्रस्त स्ट्रीटलाइट।",
        ),
        icon="lamp",
        department="STREET_LIGHTING",
        sort_order=40,
        color=(191, 144, 0),
        min_photos=0,
        max_photos=3,
        fields=[
            {
                "key": "pole_number",
                "type": "text",
                "required": False,
                "label_i18n": _label("Pole number", "खंभा संख्या"),
            },
            {
                "key": "lights_out",
                "type": "number",
                "required": False,
                "label_i18n": _label("Lights not working", "बंद लाइटों की संख्या"),
            },
        ],
    ),
    SeedCategory(
        code="drainage",
        name=_label("Open drain / drainage hazard", "खुला नाला / जल निकासी खतरा"),
        description=_label(
            "Open or broken drains, missing covers, overflowing sewage.",
            "खुले या टूटे नाले, गायब ढक्कन, उफनता सीवेज।",
        ),
        icon="triangle-alert",
        department="STORM_WATER_DRAINS",
        sort_order=50,
        color=(112, 48, 160),
        fields=[
            {
                "key": "cover_missing",
                "type": "boolean",
                "required": False,
                "label_i18n": _label("Drain cover missing?", "क्या नाले का ढक्कन गायब है?"),
            },
        ],
    ),
]

DESCRIPTIONS = {
    "pothole": [
        "Deep pothole in the middle of the lane, two-wheelers swerving around it.",
        "मुख्य सड़क पर बड़ा गड्ढा, बारिश में पानी भर जाता है।",
    ],
    "waste": [
        "Garbage has not been collected for several days near the corner shop.",
        "बस स्टॉप के पास कूड़े का ढेर, बदबू आ रही है।",
    ],
    "waterlogging": [
        "Water collects here after every rain and does not drain for hours.",
        "अंडरपास में घुटनों तक पानी भरा है।",
    ],
    "streetlight": [
        "Three streetlights in a row are off, the stretch is completely dark.",
        "गली की स्ट्रीटलाइट कई दिनों से बंद है।",
    ],
    "drainage": [
        "Drain cover is missing next to the school gate.",
        "खुला नाला, बच्चों के गिरने का खतरा है।",
    ],
}

# reported 50%, under_review 20%, verified 20%, rejected 10%.
STATUS_CYCLE = (
    [IssueStatus.REPORTED] * 5
    + [IssueStatus.UNDER_REVIEW] * 2
    + [IssueStatus.VERIFIED] * 2
    + [IssueStatus.REJECTED]
)


def seed_id(kind: str, index: int) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"demo-city/{kind}/{index}")


async def seed_categories(
    db: AsyncSession, tenant_id: uuid.UUID, departments: dict[str, uuid.UUID]
) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    for category in CATEGORIES:
        values = {
            "name_i18n": category.name,
            "description_i18n": category.description,
            "icon": category.icon,
            "min_photos": category.min_photos,
            "max_photos": category.max_photos,
            "fields": category.fields,
            "default_department_id": departments[category.department],
            "sort_order": category.sort_order,
            "is_active": True,
        }
        stmt = (
            pg_insert(Category)
            .values(id=uuid.uuid4(), tenant_id=tenant_id, code=category.code, **values)
            .on_conflict_do_update(constraint="uq_categories_tenant_id_code", set_=values)
            .returning(Category.id)
        )
        ids[category.code] = (await db.execute(stmt)).scalar_one()
    return ids


def placeholder_photo(index: int, category: SeedCategory) -> bytes:
    """A flat-colour JPEG with the category name and SYNTHETIC on it."""
    image = Image.new("RGB", (1200, 900), category.color)
    draw = ImageDraw.Draw(image)
    big = ImageFont.load_default(size=72)
    small = ImageFont.load_default(size=40)
    draw.text((60, 300), category.name["en"], fill="white", font=big)
    draw.text((60, 420), "SYNTHETIC", fill="white", font=big)
    draw.text((60, 780), f"CivicPulse demo seed #{index + 1}", fill="white", font=small)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=80)
    return buffer.getvalue()


@dataclass(frozen=True)
class PlannedIssue:
    index: int
    category: SeedCategory
    status: IssueStatus
    lng: float
    lat: float
    created_at: datetime
    description: str
    address: str


def plan(wards: dict[uuid.UUID, tuple[float, float, float, float]]) -> list[PlannedIssue]:
    ward_boxes = list(wards.values())
    now = datetime.now(UTC)
    planned: list[PlannedIssue] = []
    for index in range(ISSUE_COUNT):
        # Deterministic per index (synthetic data, not security).
        rng = random.Random(index)  # noqa: S311
        category = CATEGORIES[index % len(CATEGORIES)]
        ward_number = index % len(ward_boxes)
        min_lng, min_lat, max_lng, max_lat = ward_boxes[ward_number]
        margin = 0.002
        planned.append(
            PlannedIssue(
                index=index,
                category=category,
                status=STATUS_CYCLE[index % len(STATUS_CYCLE)],
                lng=round(rng.uniform(min_lng + margin, max_lng - margin), 6),
                lat=round(rng.uniform(min_lat + margin, max_lat - margin), 6),
                # Spread over the last 30 days, oldest first.
                created_at=now
                - timedelta(days=30)
                + timedelta(hours=12 * index, minutes=rng.randint(0, 600)),
                description=DESCRIPTIONS[category.code][index % 2],
                address=f"Synthetic Street {index + 1}, Ward {ward_number + 1} (synthetic)",
            )
        )
    return planned


async def _ensure_photo(
    tenant_id: uuid.UUID, owner_id: uuid.UUID, issue: PlannedIssue
) -> uuid.UUID:
    """Upload and process the placeholder photo unless that already happened."""
    media_id = seed_id("media", issue.index)
    async with system_session(reason="development seed: photos") as db:
        status = await db.scalar(select(MediaAsset.status).where(MediaAsset.id == media_id))
        if status is None:
            data = placeholder_photo(issue.index, issue.category)
            key = object_key(tenant_id, media_id, "original.jpg")
            await get_storage().write(key, data, content_type="image/jpeg")
            db.add(
                MediaAsset(
                    id=media_id,
                    tenant_id=tenant_id,
                    owner_id=owner_id,
                    purpose=MediaPurpose.REPORT_EVIDENCE,
                    status=MediaStatus.PROCESSING,
                    content_type="image/jpeg",
                    declared_size_bytes=len(data),
                    size_bytes=len(data),
                    checksum_sha256=hashlib.sha256(data).hexdigest(),
                    storage_key=key,
                    width=1200,
                    height=900,
                    upload_expires_at=issue.created_at,
                    verified_at=issue.created_at,
                    created_at=issue.created_at,
                )
            )
            status = MediaStatus.PROCESSING
    if status == MediaStatus.PROCESSING:
        await process_asset(media_id, tenant_id)
    return media_id


def _history(issue: PlannedIssue) -> list[tuple[IssueStatus, IssueStatus, str | None, str | None]]:
    """The status changes that lead to the planned status: (from, to, reason, note)."""
    review = (IssueStatus.REPORTED, IssueStatus.UNDER_REVIEW, None, "We are looking into this.")
    if issue.status is IssueStatus.UNDER_REVIEW:
        return [review]
    if issue.status is IssueStatus.VERIFIED:
        return [
            review,
            (IssueStatus.UNDER_REVIEW, IssueStatus.VERIFIED, None, "Confirmed by the ward office."),
        ]
    if issue.status is IssueStatus.REJECTED:
        return [
            (
                IssueStatus.REPORTED,
                IssueStatus.REJECTED,
                "Synthetic rejection: location is private property.",
                "This location is not maintained by the municipality.",
            )
        ]
    return []


async def seed_issues(
    *,
    tenant_id: uuid.UUID,
    categories: dict[str, uuid.UUID],
    wards: dict[uuid.UUID, tuple[float, float, float, float]],
    citizen_id: uuid.UUID,
    operator_id: uuid.UUID,
) -> int:
    planned = plan(wards)
    ward_ids = list(wards)
    photos = {issue.index: await _ensure_photo(tenant_id, citizen_id, issue) for issue in planned}

    async with system_session(reason="development seed: issues") as db:
        existing = set(
            (
                await db.scalars(
                    select(Report.id).where(Report.id.in_([seed_id("report", i) for i in photos]))
                )
            ).all()
        )
        for issue in planned:
            report_id = seed_id("report", issue.index)
            if report_id in existing:
                continue
            issue_id = seed_id("issue", issue.index)
            ward_id = ward_ids[issue.index % len(ward_ids)]
            location = WKTElement(f"POINT({issue.lng} {issue.lat})", srid=4326)
            history = _history(issue)
            changed_at = issue.created_at + timedelta(hours=3)
            db.add(
                CivicIssue(
                    id=issue_id,
                    tenant_id=tenant_id,
                    reference=await allocate(db, tenant_id, ReferenceKind.ISSUE),
                    category_id=categories[issue.category.code],
                    status=issue.status,
                    location=location,
                    address_text=issue.address,
                    ward_id=ward_id,
                    report_count=1,
                    unique_reporter_count=1,
                    version=1 + len(history),
                    cover_media_id=photos[issue.index],
                    status_changed_at=changed_at if history else issue.created_at,
                    created_at=issue.created_at,
                    updated_at=changed_at if history else issue.created_at,
                )
            )
            await db.flush()
            db.add(
                Report(
                    id=report_id,
                    tenant_id=tenant_id,
                    reference=await allocate(db, tenant_id, ReferenceKind.REPORT),
                    reporter_id=citizen_id,
                    category_id=categories[issue.category.code],
                    issue_id=issue_id,
                    status=ReportStatus.ACCEPTED,
                    description=issue.description,
                    details={},
                    location=location,
                    location_accuracy_m=15.0,
                    location_source="gps",
                    address_text=issue.address,
                    ward_id=ward_id,
                    created_at=issue.created_at,
                    updated_at=issue.created_at,
                )
            )
            await db.flush()
            media = await db.get(MediaAsset, photos[issue.index])
            assert media is not None
            media.report_id = report_id
            media.position = 0
            db.add(
                IssueEvent(
                    tenant_id=tenant_id,
                    issue_id=issue_id,
                    report_id=report_id,
                    type=EventType.CREATED,
                    to_status=IssueStatus.REPORTED,
                    visibility=Visibility.PUBLIC,
                    actor_id=citizen_id,
                    created_at=issue.created_at,
                )
            )
            for step, (src, dst, reason, note) in enumerate(history):
                db.add(
                    IssueEvent(
                        tenant_id=tenant_id,
                        issue_id=issue_id,
                        type=EventType.STATUS_CHANGED,
                        from_status=src,
                        to_status=dst,
                        reason=reason,
                        public_note=note,
                        visibility=Visibility.PUBLIC,
                        actor_id=operator_id,
                        created_at=issue.created_at + timedelta(hours=1 + 2 * step),
                    )
                )
            await db.flush()
    return len(planned)
