"""Append-only audit trail for security- and consent-relevant actions."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from voix_api.models import AuditLog


def record(
    db: Session,
    action: str,
    *,
    user_id: uuid.UUID | None,
    target: str | None = None,
    ip: str | None = None,
    **meta: Any,
) -> None:
    """Stage an audit row in the caller's transaction (committed with it)."""
    db.add(AuditLog(user_id=user_id, action=action, target=target, ip=ip, meta=meta))
