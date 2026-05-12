from __future__ import annotations

from sqlalchemy.orm import Session

from app.services import channel_dispatcher


def update_batch_progress_and_maybe_advance(db: Session, batch_id):
    """Compatibility wrapper for dispatcher-owned channel batch progression."""
    return channel_dispatcher.update_batch_progress_and_maybe_advance(db, batch_id)
