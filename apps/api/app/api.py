"""The /api/v1 router, assembled from the domain routers."""

from __future__ import annotations

from fastapi import APIRouter

from app.domains.ai.router import admin_router as ai_admin_router
from app.domains.ai.router import router as ai_router
from app.domains.analytics.router import router as analytics_router
from app.domains.audit.router import router as audit_router
from app.domains.auth.router import router as auth_router
from app.domains.categories.router import router as categories_router
from app.domains.config.router import router as config_router
from app.domains.geo.router import router as geo_router
from app.domains.issues.router import router as issues_router
from app.domains.matching.router import router as matching_router
from app.domains.media.router import router as media_router
from app.domains.notifications.router import router as notifications_router
from app.domains.operations.field_router import router as field_router
from app.domains.operations.router import router as operations_router
from app.domains.org.router import router as org_router
from app.domains.reports.router import router as reports_router
from app.domains.tenants.router import platform_router
from app.domains.tenants.router import router as tenants_router
from app.domains.users.admin_router import router as admin_users_router
from app.domains.users.router import router as users_router
from app.domains.workflow.router import router as workflow_router

api_router = APIRouter()
api_router.include_router(tenants_router)
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(admin_users_router)
api_router.include_router(org_router)
api_router.include_router(audit_router)
api_router.include_router(platform_router)
api_router.include_router(workflow_router)
api_router.include_router(categories_router)
api_router.include_router(media_router)
api_router.include_router(geo_router)
api_router.include_router(reports_router)
api_router.include_router(issues_router)
api_router.include_router(config_router)
api_router.include_router(ai_router)
api_router.include_router(ai_admin_router)
api_router.include_router(matching_router)
api_router.include_router(operations_router)
api_router.include_router(field_router)
api_router.include_router(notifications_router)
api_router.include_router(analytics_router)
