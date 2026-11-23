"""The OpenAPI document the frontend generates its client from."""

from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI

from scripts.export_openapi import OUTPUT, render

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _operations(schema: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path, method, op)
        for path, item in schema["paths"].items()
        for method, op in item.items()
        if method in HTTP_METHODS
    ]


def test_every_operation_has_a_clean_unique_id(app: FastAPI) -> None:
    operations = _operations(app.openapi())
    ids = [op["operationId"] for _, _, op in operations]
    assert len(ids) == len(set(ids))
    for operation_id in ids:
        assert re.fullmatch(r"[a-z]+(_[a-z]+)+", operation_id), operation_id


def test_errors_are_documented_with_the_envelope(app: FastAPI) -> None:
    schema = app.openapi()
    assert "HTTPValidationError" not in schema["components"]["schemas"]
    for path, method, op in _operations(schema):
        for status, response in op["responses"].items():
            if status.startswith(("4", "5")) and path not in ("/ready",):
                ref = response["content"]["application/json"]["schema"]["$ref"]
                assert ref.endswith("/ErrorResponse"), (method, path, status)


def test_committed_openapi_json_is_current(app: FastAPI) -> None:
    assert OUTPUT.read_text(encoding="utf-8") == render(app.openapi()), (
        "openapi.json is stale: run `uv run python scripts/export_openapi.py`"
    )
