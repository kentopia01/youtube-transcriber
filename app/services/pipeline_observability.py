from __future__ import annotations

import socket
from typing import Any

ATTEMPT_REASON_CHANNEL_PROCESS = "channel_process"
ATTEMPT_REASON_AUTO_INGEST = "auto_ingest"
ATTEMPT_REASON_BATCH_ADVANCE = "batch_advance"
ATTEMPT_REASON_MANUAL_RESUBMIT = "manual_resubmit"
ATTEMPT_REASON_USER_RETRY = "user_retry"
ATTEMPT_REASON_STALE_RECOVERY = "stale_recovery"
ATTEMPT_REASON_OPERATOR_ACTION = "operator_action"
# Backward-compatible alias for initial/manual direct submission flows.
ATTEMPT_REASON_VIDEO_SUBMIT = ATTEMPT_REASON_OPERATOR_ACTION


def build_artifact_check_result(**kwargs: Any) -> dict[str, Any]:
    return {key: value for key, value in kwargs.items()}


def get_task_worker_identity(task: Any) -> tuple[str | None, str | None]:
    request = getattr(task, "request", None)
    worker_hostname = getattr(request, "hostname", None) if request else None
    worker_task_id = getattr(request, "id", None) if request else None

    if not worker_hostname:
        try:
            worker_hostname = socket.gethostname()
        except OSError:
            worker_hostname = None

    return worker_hostname, worker_task_id
