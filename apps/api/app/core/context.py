"""Per-request context carried in context variables.

These are read by the JSON log formatter and by the audit service, so neither
needs the request object threaded through every call.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClientInfo:
    ip: str | None = None
    user_agent: str | None = None


request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
tenant_id_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
client_var: ContextVar[ClientInfo] = ContextVar("client", default=ClientInfo())  # noqa: B039


def get_request_id() -> str | None:
    return request_id_var.get()


def get_client() -> ClientInfo:
    return client_var.get()
