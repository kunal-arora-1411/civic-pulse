"""List conventions: `limit`/`offset` paging, `sort=-field`, and the page envelope."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Query
from pydantic import BaseModel
from sqlalchemy import Row, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement, UnaryExpression

from app.core.errors import ValidationFailed


@dataclass(frozen=True, slots=True)
class PageParams:
    limit: int
    offset: int


def _page_params(
    limit: Annotated[int, Query(ge=1, le=100, description="Page size (1-100).")] = 20,
    offset: Annotated[int, Query(ge=0, description="Number of items to skip.")] = 0,
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


PageParamsDep = Annotated[PageParams, Depends(_page_params)]


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


def sort_clauses(
    sort: str | None,
    allowed: Mapping[str, ColumnElement[Any] | Any],
    *,
    default: str,
    tiebreaker: ColumnElement[Any] | Any,
) -> list[UnaryExpression[Any]]:
    """Turn `sort=-created_at` into ORDER BY clauses.

    Only whitelisted fields are accepted, and a unique tiebreaker is always
    appended so offset paging is stable.
    """
    value = (sort or default).strip()
    descending = value.startswith("-")
    field = value.lstrip("-+")
    if field not in allowed:
        raise ValidationFailed(
            "Unsupported sort field.",
            details={"sort": value, "allowed": sorted(allowed)},
        )
    column = allowed[field]
    primary = column.desc() if descending else column.asc()
    return [primary, tiebreaker.desc() if descending else tiebreaker.asc()]


async def paginate[*Ts](
    db: AsyncSession, stmt: Select[*Ts], params: PageParams
) -> tuple[Sequence[Row[*Ts]], int]:
    """Run `stmt` for one page, plus a count of all matching rows."""
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = (await db.execute(stmt.limit(params.limit).offset(params.offset))).all()
    return rows, int(total or 0)
