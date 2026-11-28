"""Reading and replacing a tenant's matching and priority configuration."""

from __future__ import annotations

import logging

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log_fields
from app.domains.audit import service as audit
from app.domains.config.models import ConfigKey, TenantConfig
from app.domains.config.schemas import (
    ClosureConfig,
    MatchingConfig,
    PriorityConfig,
    ReportLimitsConfig,
)
from app.domains.rbac.principal import Principal

logger = logging.getLogger(__name__)


async def _load[C: BaseModel](db: AsyncSession, key: ConfigKey, model: type[C]) -> C:
    """The tenant's document, or the defaults when it has none.

    Reads under RLS, so the caller's session must be scoped to the tenant.
    A stored document that no longer validates (written by an older
    version, say) falls back to the defaults rather than breaking matching.
    """
    value = await db.scalar(select(TenantConfig.value).where(TenantConfig.key == key))
    if value is None:
        return model()
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        logger.error(
            "stored tenant config is invalid; using defaults",
            extra=log_fields(config_key=key.value, error=str(exc)),
        )
        return model()


async def matching_config(db: AsyncSession) -> MatchingConfig:
    return await _load(db, ConfigKey.MATCHING, MatchingConfig)


async def priority_config(db: AsyncSession) -> PriorityConfig:
    return await _load(db, ConfigKey.PRIORITY, PriorityConfig)


async def closure_config(db: AsyncSession) -> ClosureConfig:
    return await _load(db, ConfigKey.CLOSURE, ClosureConfig)


async def report_limits_config(db: AsyncSession) -> ReportLimitsConfig:
    return await _load(db, ConfigKey.REPORT_LIMITS, ReportLimitsConfig)


async def replace[C: BaseModel](db: AsyncSession, actor: Principal, key: ConfigKey, body: C) -> C:
    """Store a new document for the actor's tenant, audited with both versions."""
    assert actor.tenant_id is not None
    model = type(body)
    # Lock the current row (if any) so two admins saving at once are
    # recorded in order, each audit event with the right "before".
    current = await db.scalar(
        select(TenantConfig.value).where(TenantConfig.key == key).with_for_update()
    )
    before = (await _load(db, key, model)) if current is not None else model()
    value = body.model_dump(mode="json")
    await db.execute(
        pg_insert(TenantConfig)
        .values(tenant_id=actor.tenant_id, key=key.value, value=value, updated_by=actor.user_id)
        .on_conflict_do_update(
            constraint="pk_tenant_configs",
            set_={"value": value, "updated_by": actor.user_id, "updated_at": func.now()},
        )
    )
    await audit.record(
        db,
        action=f"config.{key.value}_updated",
        entity_type="tenant_config",
        entity_id=key.value,
        actor=actor,
        before=before.model_dump(mode="json"),
        after=value,
    )
    return body
