"""Imports every ORM model so the metadata is complete (Alembic, mappers)."""

from app.core.db import Base
from app.core.idempotency import IdempotencyKey
from app.domains.audit.models import AuditEvent
from app.domains.auth.models import AuthSession, OtpChallenge
from app.domains.org.models import Department, Jurisdiction
from app.domains.rbac.models import UserRole
from app.domains.tenants.models import Tenant
from app.domains.users.models import User

__all__ = [
    "AuditEvent",
    "AuthSession",
    "Base",
    "Department",
    "IdempotencyKey",
    "Jurisdiction",
    "OtpChallenge",
    "Tenant",
    "User",
    "UserRole",
]
