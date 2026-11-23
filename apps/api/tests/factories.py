"""Test data, written through the owner connection (which bypasses RLS).

Every helper generates unique slugs and phone numbers, so tests don't need to
clean up after each other.
"""

from __future__ import annotations

import itertools
import json
import random
import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_phone_counter = itertools.count(random.randint(0, 10_000) * 10_000)


def unique_phone() -> str:
    # +91 8xxxxxxxxx: valid Indian mobile numbers, never the seeded 90000/91000 range.
    return f"+918{next(_phone_counter) % 1_000_000_000:09d}"


def unique_slug(prefix: str = "t") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@dataclass
class TenantRow:
    id: uuid.UUID
    slug: str


@dataclass
class UserRow:
    id: uuid.UUID
    tenant_id: uuid.UUID | None
    phone: str
    roles: list[str] = field(default_factory=list)


async def create_tenant(conn: AsyncConnection, *, name: str = "Test City") -> TenantRow:
    slug = unique_slug()
    tenant_id = (
        await conn.execute(
            text("INSERT INTO tenants (slug, name) VALUES (:slug, :name) RETURNING id"),
            {"slug": slug, "name": name},
        )
    ).scalar_one()
    return TenantRow(id=tenant_id, slug=slug)


async def create_user(
    conn: AsyncConnection,
    tenant_id: uuid.UUID | None,
    *roles: str,
    phone: str | None = None,
    display_name: str | None = "Test User",
    department_id: uuid.UUID | None = None,
    jurisdiction_id: uuid.UUID | None = None,
    is_active: bool = True,
) -> UserRow:
    phone = phone or unique_phone()
    user_id = (
        await conn.execute(
            text(
                "INSERT INTO users (tenant_id, phone, display_name, is_active) "
                "VALUES (:tenant_id, :phone, :display_name, :is_active) RETURNING id"
            ),
            {
                "tenant_id": tenant_id,
                "phone": phone,
                "display_name": display_name,
                "is_active": is_active,
            },
        )
    ).scalar_one()
    for role in roles:
        await conn.execute(
            text(
                "INSERT INTO user_roles (tenant_id, user_id, role, department_id, jurisdiction_id) "
                "VALUES (:tenant_id, :user_id, :role, :department_id, :jurisdiction_id)"
            ),
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "role": role,
                "department_id": department_id,
                "jurisdiction_id": jurisdiction_id,
            },
        )
    return UserRow(id=user_id, tenant_id=tenant_id, phone=phone, roles=list(roles))


async def create_department(
    conn: AsyncConnection, tenant_id: uuid.UUID, *, code: str = "ROADS", name: str = "Roads"
) -> uuid.UUID:
    return (
        await conn.execute(
            text(
                "INSERT INTO departments (tenant_id, name, code) "
                "VALUES (:tenant_id, :name, :code) RETURNING id"
            ),
            {"tenant_id": tenant_id, "name": name, "code": code},
        )
    ).scalar_one()


async def create_jurisdiction(
    conn: AsyncConnection,
    tenant_id: uuid.UUID,
    *,
    kind: str,
    code: str,
    name: str | None = None,
    parent_id: uuid.UUID | None = None,
    wkt: str | None = None,
) -> uuid.UUID:
    return (
        await conn.execute(
            text(
                "INSERT INTO jurisdictions (tenant_id, parent_id, kind, name, code, geom) "
                "VALUES (:tenant_id, :parent_id, :kind, :name, :code, "
                "        CASE WHEN CAST(:wkt AS text) IS NULL THEN NULL "
                "             ELSE ST_Multi(ST_GeomFromText(:wkt, 4326)) END) "
                "RETURNING id"
            ),
            {
                "tenant_id": tenant_id,
                "parent_id": parent_id,
                "kind": kind,
                "name": name or code,
                "code": code,
                "wkt": wkt,
            },
        )
    ).scalar_one()


# --- Phase 1: categories, issues, reports -----------------------------------------------

_reference_counter = itertools.count(1)


def square_wkt(min_lng: float, min_lat: float, max_lng: float, max_lat: float) -> str:
    return (
        f"POLYGON(({min_lng} {min_lat}, {max_lng} {min_lat}, {max_lng} {max_lat}, "
        f"{min_lng} {max_lat}, {min_lng} {min_lat}))"
    )


async def create_category(
    conn: AsyncConnection,
    tenant_id: uuid.UUID,
    *,
    code: str | None = None,
    min_photos: int = 0,
    max_photos: int = 5,
    fields: list[dict] | None = None,
    is_active: bool = True,
    sort_order: int = 0,
) -> uuid.UUID:
    code = code or f"cat_{uuid.uuid4().hex[:8]}"
    return (
        await conn.execute(
            text(
                "INSERT INTO categories (tenant_id, code, name_i18n, icon, min_photos, "
                "max_photos, fields, is_active, sort_order) VALUES (:t, :code, "
                "CAST(:names AS jsonb), 'construction', :min, :max, CAST(:fields AS jsonb), "
                ":active, :sort) RETURNING id"
            ),
            {
                "t": tenant_id,
                "code": code,
                "names": json.dumps({"en": code.title(), "hi": "श्रेणी"}),
                "min": min_photos,
                "max": max_photos,
                "fields": json.dumps(fields or []),
                "active": is_active,
                "sort": sort_order,
            },
        )
    ).scalar_one()


@dataclass
class IssueRow:
    id: uuid.UUID
    reference: str
    report_id: uuid.UUID
    report_reference: str


async def create_issue(
    conn: AsyncConnection,
    tenant_id: uuid.UUID,
    *,
    category_id: uuid.UUID,
    reporter_id: uuid.UUID,
    lng: float = 77.60,
    lat: float = 12.98,
    status: str = "reported",
    ward_id: uuid.UUID | None = None,
    description: str | None = "Something needs fixing",
    address_text: str | None = None,
    created_at: str | None = None,
) -> IssueRow:
    """An issue with its one report and `created` event, as POST /reports leaves them."""
    n = next(_reference_counter)
    issue_ref, report_ref = f"CP-99-{n:06d}", f"R-99-{n:06d}"
    params = {
        "t": tenant_id,
        "category": category_id,
        "reporter": reporter_id,
        "lng": lng,
        "lat": lat,
        "status": status,
        "ward": ward_id,
        "description": description,
        "address": address_text,
        "created_at": created_at,
    }
    issue_id = (
        await conn.execute(
            text(
                "INSERT INTO civic_issues (tenant_id, reference, category_id, status, location, "
                "address_text, ward_id, report_count, unique_reporter_count, created_at, "
                "updated_at) VALUES (:t, :ref, :category, :status, "
                "ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), :address, :ward, 1, 1, "
                "COALESCE(CAST(:created_at AS timestamptz), now()), "
                "COALESCE(CAST(:created_at AS timestamptz), now())) RETURNING id"
            ),
            {**params, "ref": issue_ref},
        )
    ).scalar_one()
    report_id = (
        await conn.execute(
            text(
                "INSERT INTO reports (tenant_id, reference, reporter_id, category_id, issue_id, "
                "status, description, location, location_source, address_text, ward_id, "
                "created_at) VALUES (:t, :ref, :reporter, :category, :issue, 'accepted', "
                ":description, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), 'gps', :address, "
                ":ward, COALESCE(CAST(:created_at AS timestamptz), now())) RETURNING id"
            ),
            {**params, "ref": report_ref, "issue": issue_id},
        )
    ).scalar_one()
    await conn.execute(
        text(
            "INSERT INTO issue_events (tenant_id, issue_id, report_id, type, to_status, "
            "visibility, actor_id) VALUES (:t, :issue, :report, 'created', 'reported', "
            "'public', :reporter)"
        ),
        {"t": tenant_id, "issue": issue_id, "report": report_id, "reporter": reporter_id},
    )
    return IssueRow(issue_id, issue_ref, report_id, report_ref)
