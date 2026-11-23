from __future__ import annotations

from app.core.errors import AppError


class UnsupportedMediaType(AppError):
    status_code = 422
    code = "unsupported_media_type"
    message = "Only JPEG, PNG and WebP images can be uploaded."


class FileTooLarge(AppError):
    status_code = 422
    code = "file_too_large"
    message = "The file is larger than the upload limit."


class TooManyUploads(AppError):
    status_code = 429
    code = "too_many_uploads"
    message = "Too many unfinished uploads. Complete or abandon some first."


class UploadVerificationFailed(AppError):
    status_code = 422
    code = "upload_verification_failed"
    message = "The uploaded file could not be verified."
