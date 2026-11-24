"""Imports every ORM model so the metadata is complete (Alembic, mappers)."""

from app.core.db import Base
from app.core.idempotency import IdempotencyKey
from app.domains.ai.models import Classification, MediaEmbedding, ModelRegistryEntry
from app.domains.audit.models import AuditEvent
from app.domains.auth.models import AuthSession, OtpChallenge
from app.domains.categories.models import Category
from app.domains.config.models import TenantConfig
from app.domains.issues.models import CivicIssue, IssueEvent, IssueRelation, ReferenceCounter
from app.domains.matching.models import MatchDecision, ReviewTask
from app.domains.media.models import MediaAsset
from app.domains.org.models import Department, Jurisdiction
from app.domains.places.models import PlaceOfInterest
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
    "Classification",
    "Department",
    "IdempotencyKey",
    "IssueEvent",
    "IssueRelation",
    "Jurisdiction",
    "MatchDecision",
    "MediaAsset",
    "MediaEmbedding",
    "ModelRegistryEntry",
    "OtpChallenge",
    "PlaceOfInterest",
    "ReferenceCounter",
    "Report",
    "ReviewTask",
    "StatusTransition",
    "Tenant",
    "TenantConfig",
    "User",
    "UserRole",
]
