from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.core.pagination import Page


class AuditActor(BaseModel):
    id: uuid.UUID
    display_name: str | None


class AuditEventOut(BaseModel):
    id: int
    occurred_at: datetime
    actor: AuditActor | None
    action: str
    entity_type: str
    entity_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    request_id: str | None


class AuditEventPage(Page[AuditEventOut]):
    pass


# --- the hash chain (A6.3) ---------------------------------------------------------------


class AuditChainHeadOut(BaseModel):
    """Where a chain currently ends."""

    seq: int
    hash: str
    occurred_at: datetime | None


class AuditCheckpointOut(BaseModel):
    id: uuid.UUID
    up_to_seq: int
    head_hash: str
    key_id: str
    created_at: datetime
    signature_valid: bool


class AuditCheckpointPage(Page[AuditCheckpointOut]):
    pass


VerificationStatus = Literal["pending", "running", "passed", "failed", "error"]
VerificationMode = Literal["db", "independent"]


class AuditChainVerificationOut(BaseModel):
    id: uuid.UUID
    status: VerificationStatus
    mode: VerificationMode
    from_seq: int
    to_seq: int
    checked_count: int
    first_bad_seq: int | None
    failure_reason: str | None
    started_at: datetime
    finished_at: datetime | None


class AuditChainVerificationPage(Page[AuditChainVerificationOut]):
    pass


class AuditChainVerificationRequest(BaseModel):
    """A window to verify. `to_seq` defaults to the head of the chain."""

    from_seq: Annotated[int, Field(ge=1)] = 1
    to_seq: Annotated[int, Field(ge=1)] | None = None
    mode: VerificationMode = "db"


class AuditChainStatus(BaseModel):
    """The single thing an operator or a monitor watches.

    `healthy` is false when the newest checkpoint's signature does not verify, the
    last verification failed, or the head is behind a checkpoint that was signed --
    each of which means rows moved or vanished after they were sealed. It is
    deliberately not part of `/ready`: a broken chain is an incident, not an outage.
    """

    scope: Literal["tenant"] = "tenant"
    events: int
    head: AuditChainHeadOut
    last_checkpoint: AuditCheckpointOut | None
    unsealed_events: int
    last_verification: AuditChainVerificationOut | None
    healthy: bool
