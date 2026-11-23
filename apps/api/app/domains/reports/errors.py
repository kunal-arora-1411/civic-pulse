from __future__ import annotations

from app.core.errors import AppError


class OutOfJurisdiction(AppError):
    status_code = 422
    code = "out_of_jurisdiction"
    message = "This location is outside the area this municipality serves."


class EvidenceRequired(AppError):
    status_code = 422
    code = "evidence_required"
    message = "The report doesn't have the photos or description it needs."


class InvalidMedia(AppError):
    status_code = 422
    code = "invalid_media"
    message = "Some attached media can't be used for this report."
