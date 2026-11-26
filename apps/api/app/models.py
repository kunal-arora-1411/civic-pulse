"""Imports every ORM model so the metadata is complete (Alembic, mappers)."""

from app.core.db import Base
from app.core.idempotency import IdempotencyKey
from app.domains.ai.models import Classification, MediaEmbedding, ModelRegistryEntry
from app.domains.analytics.models import AnalyticsView
from app.domains.announcements.models import Announcement
from app.domains.audit.models import AuditEvent
from app.domains.auth.models import AuthSession, OtpChallenge
from app.domains.categories.models import Category
from app.domains.community.models import CommentFlag, IssueComment, IssueSupport
from app.domains.config.models import TenantConfig
from app.domains.issues.models import CivicIssue, IssueEvent, IssueRelation, ReferenceCounter
from app.domains.matching.models import MatchDecision, ReviewTask
from app.domains.media.models import MediaAsset
from app.domains.notifications.models import Notification
from app.domains.operations.models import (
    ClosureRequest,
    IssueAssignment,
    IssueVerification,
    WorkOrder,
)
from app.domains.org.models import (
    Department,
    Jurisdiction,
    Team,
    TeamCategory,
    TeamJurisdiction,
    TeamMember,
)
from app.domains.outbox.models import OutboxDelivery, OutboxEvent
from app.domains.places.models import PlaceOfInterest
from app.domains.rbac.models import UserRole
from app.domains.reports.models import Report
from app.domains.sla.models import SlaTarget
from app.domains.tenants.models import Tenant
from app.domains.users.models import User
from app.domains.workflow.models import StatusTransition

__all__ = [
    "AnalyticsView",
    "Announcement",
    "AuditEvent",
    "AuthSession",
    "Base",
    "Category",
    "CivicIssue",
    "Classification",
    "ClosureRequest",
    "CommentFlag",
    "Department",
    "IdempotencyKey",
    "IssueAssignment",
    "IssueComment",
    "IssueEvent",
    "IssueRelation",
    "IssueSupport",
    "IssueVerification",
    "Jurisdiction",
    "MatchDecision",
    "MediaAsset",
    "MediaEmbedding",
    "ModelRegistryEntry",
    "Notification",
    "OtpChallenge",
    "OutboxDelivery",
    "OutboxEvent",
    "PlaceOfInterest",
    "ReferenceCounter",
    "Report",
    "ReviewTask",
    "SlaTarget",
    "StatusTransition",
    "Team",
    "TeamCategory",
    "TeamJurisdiction",
    "TeamMember",
    "Tenant",
    "TenantConfig",
    "User",
    "UserRole",
    "WorkOrder",
]
