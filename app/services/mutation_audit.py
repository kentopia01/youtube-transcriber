from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings


_LOCK = threading.Lock()
_ACTOR_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def sanitize_actor(value: str | None, *, browser: bool = False) -> str:
    candidate = (value or "").strip()
    if candidate and _ACTOR_RE.fullmatch(candidate):
        return candidate
    return "web" if browser else "local-api"


def record_mutation(
    *,
    actor: str,
    method: str,
    path: str,
    status_code: int,
    client: str | None,
) -> dict[str, Any]:
    record = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "actor": sanitize_actor(actor),
        "method": method[:10].upper(),
        "path": path[:512],
        "status_code": int(status_code),
        "outcome": "accepted" if status_code < 400 else "rejected",
        "client": (client or "")[:64] or None,
    }
    audit_path = Path(settings.mutation_audit_path)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return record


def list_mutations(*, limit: int = 100, actor: str | None = None) -> list[dict[str, Any]]:
    audit_path = Path(settings.mutation_audit_path)
    if not audit_path.exists():
        return []
    selected: list[dict[str, Any]] = []
    with _LOCK, audit_path.open("r", encoding="utf-8") as handle:
        lines = handle.readlines()
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if actor and item.get("actor") != actor:
            continue
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


__all__ = ["list_mutations", "record_mutation", "sanitize_actor"]
