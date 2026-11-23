"""The /api/v1 router, assembled from the domain routers."""

from __future__ import annotations

from fastapi import APIRouter

from app.domains.audit.router import router as audit_router
from app.domains.auth.router import router as auth_router
from app.domains.org.router import router as org_router
from app.domains.tenants.router import router as tenants_router
from app.domains.users.admin_router import router as admin_users_router
from app.domains.users.router import router as users_router

api_router = APIRouter()
api_router.include_router(tenants_router)
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(admin_users_router)
api_router.include_router(org_router)
api_router.include_router(audit_router)
