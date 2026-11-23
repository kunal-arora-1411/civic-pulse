"""Imports every ORM model so the metadata is complete (Alembic, mappers)."""

from app.core.db import Base
from app.core.idempotency import IdempotencyKey
from app.domains.audit.models import AuditEvent
from app.domains.auth.models import AuthSession, OtpChallenge
from app.domains.categories.models import Category
from app.domains.issues.models import CivicIssue, IssueEvent, ReferenceCounter
from app.domains.media.models import MediaAsset
from app.domains.org.models import Department, Jurisdiction
from app.domains.rbac.models import UserRole
from app.domains.reports.models import Report
from app.domains.tenants.models import Tenant
from app.domains.users.models import User
from app.domains.workflow.models import StatusTransition

__all__ = [
    "AuditEvent",
    "AuthSession",
    "Base",
    "Category",
    "CivicIssue",
    "Department",
    "IdempotencyKey",
    "IssueEvent",
    "Jurisdiction",
    "MediaAsset",
    "OtpChallenge",
    "ReferenceCounter",
    "Report",
    "StatusTransition",
    "Tenant",
    "User",
    "UserRole",
]
