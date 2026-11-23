from __future__ import annotations

import math
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import PageParams, paginate, sort_clauses
from app.domains.audit import service as audit
from app.domains.categories.models import Category
from app.domains.categories.schemas import (
    CategoryCreate,
    CategoryOut,
    CategoryRef,
    CategoryUpdate,
    Dedup,
    Evidence,
    fields_as_json,
)
from app.domains.org.models import Department
from app.domains.rbac.principal import Principal

SORTS = {
    "sort_order": Category.sort_order,
    "code": Category.code,
    "created_at": Category.created_at,
}
MAX_TEXT_ANSWER = 500


def to_out(category: Category) -> CategoryOut:
    return CategoryOut.model_validate(
        {
            "id": category.id,
            "code": category.code,
            "parent_id": category.parent_id,
            "name_i18n": category.name_i18n,
            "description_i18n": category.description_i18n,
            "icon": category.icon,
            "evidence": Evidence(min_photos=category.min_photos, max_photos=category.max_photos),
            "fields": category.fields,
            "default_department_id": category.default_department_id,
            "dedup": Dedup(
                radius_m=category.dedup_radius_m, window_days=category.dedup_window_days
            ),
            "sort_order": category.sort_order,
            "is_active": category.is_active,
        }
    )


def to_ref(category: Category) -> CategoryRef:
    return CategoryRef(
        id=category.id, code=category.code, name_i18n=category.name_i18n, icon=category.icon
    )


async def list_active(db: AsyncSession) -> list[CategoryOut]:
    rows = await db.scalars(
        select(Category)
        .where(Category.is_active.is_(True))
        .order_by(Category.sort_order, Category.code)
    )
    return [to_out(c) for c in rows]


async def list_all(
    db: AsyncSession, params: PageParams, *, is_active: bool | None, sort: str | None
) -> tuple[list[CategoryOut], int]:
    stmt = select(Category)
    if is_active is not None:
        stmt = stmt.where(Category.is_active.is_(is_active))
    stmt = stmt.order_by(*sort_clauses(sort, SORTS, default="sort_order", tiebreaker=Category.id))
    rows, total = await paginate(db, stmt, params)
    return [to_out(row[0]) for row in rows], total


async def get(db: AsyncSession, category_id: uuid.UUID) -> Category:
    category = await db.get(Category, category_id)
    if category is None:
        raise NotFound()
    return category


async def _check_references(
    db: AsyncSession,
    *,
    category_id: uuid.UUID | None,
    parent_id: uuid.UUID | None,
    department_id: uuid.UUID | None,
) -> None:
    """Parent and department must exist in this tenant (RLS hides others)."""
    errors: list[dict[str, Any]] = []
    if department_id is not None and await db.get(Department, department_id) is None:
        errors.append({"loc": ["body", "default_department_id"], "msg": "Unknown department."})
    if parent_id is not None:
        if parent_id == category_id:
            errors.append(
                {"loc": ["body", "parent_id"], "msg": "A category can't be its own parent."}
            )
        elif await db.get(Category, parent_id) is None:
            errors.append({"loc": ["body", "parent_id"], "msg": "Unknown category."})
        elif category_id is not None:
            # Walk up from the new parent; meeting ourselves means a cycle.
            seen: set[uuid.UUID] = set()
            cursor: uuid.UUID | None = parent_id
            while cursor is not None and cursor not in seen:
                if cursor == category_id:
                    errors.append(
                        {"loc": ["body", "parent_id"], "msg": "That would create a cycle."}
                    )
                    break
                seen.add(cursor)
                cursor = await db.scalar(select(Category.parent_id).where(Category.id == cursor))
    if errors:
        raise ValidationFailed("Some category references are invalid.", details={"errors": errors})


async def _code_taken(db: AsyncSession, code: str, exclude: uuid.UUID | None = None) -> bool:
    stmt = select(Category.id).where(Category.code == code)
    if exclude is not None:
        stmt = stmt.where(Category.id != exclude)
    return await db.scalar(stmt) is not None


async def create(db: AsyncSession, actor: Principal, body: CategoryCreate) -> CategoryOut:
    assert actor.tenant_id is not None
    if await _code_taken(db, body.code):
        raise Conflict("A category with this code already exists.", details={"code": body.code})
    await _check_references(
        db, category_id=None, parent_id=body.parent_id, department_id=body.default_department_id
    )
    category = Category(
        tenant_id=actor.tenant_id,
        code=body.code,
        parent_id=body.parent_id,
        name_i18n=body.name_i18n,
        description_i18n=body.description_i18n,
        icon=body.icon,
        min_photos=body.evidence.min_photos,
        max_photos=body.evidence.max_photos,
        fields=fields_as_json(body.fields),
        default_department_id=body.default_department_id,
        dedup_radius_m=body.dedup.radius_m,
        dedup_window_days=body.dedup.window_days,
        sort_order=body.sort_order,
        is_active=body.is_active,
    )
    db.add(category)
    try:
        await db.flush()
    except IntegrityError as exc:  # lost a race with a concurrent create
        raise Conflict("A category with this code already exists.") from exc
    out = to_out(category)
    await audit.record(
        db,
        action="category.created",
        entity_type="category",
        entity_id=category.id,
        actor=actor,
        after=out.model_dump(mode="json"),
    )
    return out


async def update(
    db: AsyncSession, actor: Principal, category_id: uuid.UUID, body: CategoryUpdate
) -> CategoryOut:
    category = await db.scalar(select(Category).where(Category.id == category_id).with_for_update())
    if category is None:
        raise NotFound()
    before = to_out(category)
    changes = body.model_fields_set
    if "code" in changes and body.code != category.code:
        assert body.code is not None
        if await _code_taken(db, body.code, exclude=category.id):
            raise Conflict("A category with this code already exists.", details={"code": body.code})
        category.code = body.code
    await _check_references(
        db,
        category_id=category.id,
        parent_id=body.parent_id if "parent_id" in changes else None,
        department_id=body.default_department_id if "default_department_id" in changes else None,
    )
    if "parent_id" in changes:
        category.parent_id = body.parent_id
    if "default_department_id" in changes:
        category.default_department_id = body.default_department_id
    if body.name_i18n is not None:
        category.name_i18n = body.name_i18n
    if body.description_i18n is not None:
        category.description_i18n = body.description_i18n
    if body.icon is not None:
        category.icon = body.icon
    if body.evidence is not None:
        category.min_photos = body.evidence.min_photos
        category.max_photos = body.evidence.max_photos
    if body.fields is not None:
        category.fields = fields_as_json(body.fields)
    if body.dedup is not None:
        category.dedup_radius_m = body.dedup.radius_m
        category.dedup_window_days = body.dedup.window_days
    if body.sort_order is not None:
        category.sort_order = body.sort_order
    if body.is_active is not None:
        category.is_active = body.is_active
    try:
        await db.flush()
    except IntegrityError as exc:
        raise Conflict("A category with this code already exists.") from exc
    after = to_out(category)
    if after != before:
        await audit.record(
            db,
            action="category.updated",
            entity_type="category",
            entity_id=category.id,
            actor=actor,
            before=before.model_dump(mode="json"),
            after=after.model_dump(mode="json"),
        )
    return after


def validate_details(fields: list[dict[str, Any]], details: dict[str, Any]) -> dict[str, Any]:
    """Check a report's `details` against its category's field definitions.

    Unknown keys, wrong types, values outside a select's options and missing
    required answers are all reported at once, in the same shape as other
    validation errors. Blank text answers count as missing. Returns the
    cleaned answers (trimmed text, no empty values).
    """
    errors: list[dict[str, Any]] = []
    cleaned: dict[str, Any] = {}
    by_key = {f["key"]: f for f in fields}

    for key in details:
        if key not in by_key:
            errors.append(_detail_error(key, "This category has no such field.", "extra_forbidden"))

    for key, field in by_key.items():
        value = details.get(key)
        if isinstance(value, str) and field["type"] == "text":
            value = value.strip() or None
        if value is None:
            if field.get("required"):
                errors.append(_detail_error(key, "This field is required.", "missing"))
            continue
        message = _type_error(field, value)
        if message is not None:
            errors.append(_detail_error(key, message, "invalid_value"))
            continue
        cleaned[key] = value

    if errors:
        raise ValidationFailed("Some details are invalid.", details={"errors": errors})
    return cleaned


def _type_error(field: dict[str, Any], value: Any) -> str | None:
    kind = field["type"]
    if kind == "text":
        if not isinstance(value, str):
            return "Expected text."
        if len(value) > MAX_TEXT_ANSWER:
            return f"At most {MAX_TEXT_ANSWER} characters."
    elif kind == "number":
        # bool is an int in Python; it is not a number here.
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            return "Expected a number."
    elif kind == "boolean":
        if not isinstance(value, bool):
            return "Expected true or false."
    elif kind == "select":
        allowed = [o["value"] for o in field.get("options") or []]
        if value not in allowed:
            return f"Expected one of: {', '.join(allowed)}."
    return None


def _detail_error(key: str, msg: str, type_: str) -> dict[str, Any]:
    return {"loc": ["body", "details", key], "msg": msg, "type": type_}
