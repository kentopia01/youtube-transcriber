"""Static Alembic/model contract tests.

These tests are intentionally non-mutating: they inspect Alembic revision metadata,
SQLAlchemy model metadata, and selected migration ``upgrade`` functions with a fake
``op`` recorder. They must not call ``alembic upgrade`` against the configured
runtime database.

If we ever add a live migration smoke test, keep it in an explicit opt-in test that
requires a disposable ``DATABASE_URL_SYNC`` and skips by default.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

# Importing app.models populates Base.metadata and mirrors alembic/env.py. It also
# loads PostgreSQL dialect symbols before selected migration functions construct
# PostgreSQL-specific columns under the fake operation recorder.
import app.models as _models  # noqa: F401
from app.database import Base
from app.models.video import Video
from app.models.video_report import SUMMARY_REPORT_TYPE


REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_DIR = REPO_ROOT / "alembic"
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


@dataclass(frozen=True)
class RecordedOperation:
    name: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


class RecordingOperations:
    """Minimal Alembic ``op`` stand-in that records calls without a database."""

    def __init__(self) -> None:
        self.calls: list[RecordedOperation] = []

    def __getattr__(self, operation_name: str):
        def _record(*args: Any, **kwargs: Any) -> None:
            self.calls.append(RecordedOperation(operation_name, args, kwargs))

        return _record


def _script_directory() -> ScriptDirectory:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    config.set_main_option("path_separator", "os")
    return ScriptDirectory.from_config(config)


def _record_upgrade(revision: str) -> list[RecordedOperation]:
    script = _script_directory()
    module = script.get_revision(revision).module
    recorder = RecordingOperations()
    original_op = module.op
    module.op = recorder
    try:
        module.upgrade()
    finally:
        module.op = original_op
    return recorder.calls


def _create_index_calls(revision: str) -> dict[str, RecordedOperation]:
    return {
        call.args[0]: call
        for call in _record_upgrade(revision)
        if call.name == "create_index"
    }


def _columns_created_or_added(revisions: list[str]) -> dict[str, set[str]]:
    columns_by_table: dict[str, set[str]] = defaultdict(set)

    for revision in revisions:
        for call in _record_upgrade(revision):
            if call.name == "create_table":
                table_name = call.args[0]
                for table_item in call.args[1:]:
                    if isinstance(table_item, sa.Column):
                        columns_by_table[table_name].add(table_item.name)
            elif call.name == "add_column":
                table_name, column = call.args[:2]
                columns_by_table[table_name].add(column.name)

    return columns_by_table


def _table(table_name: str) -> sa.Table:
    try:
        return Base.metadata.tables[table_name]
    except KeyError:  # pragma: no cover - failure path gives an actionable diff.
        available = sorted(Base.metadata.tables)
        raise AssertionError(f"missing model metadata table {table_name!r}; have {available}") from None


def _constraint_column_sets(table: sa.Table, constraint_type: type) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, constraint_type)
    }


def _unique_constraint_columns_by_name(table: sa.Table) -> dict[str, tuple[str, ...]]:
    return {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name
    }


def _foreign_key_targets(table: sa.Table) -> set[tuple[tuple[str, ...], tuple[str, ...]]]:
    targets: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    for constraint in table.constraints:
        if not isinstance(constraint, ForeignKeyConstraint):
            continue
        local_columns = tuple(column.name for column in constraint.columns)
        remote_columns = tuple(element.column.table.name + "." + element.column.name for element in constraint.elements)
        targets.add((local_columns, remote_columns))
    return targets


def test_alembic_revision_chain_is_single_linear_chain_to_head():
    script = _script_directory()
    revisions = list(script.walk_revisions())
    revision_by_id = {revision.revision: revision for revision in revisions}
    version_files = [
        path
        for path in (ALEMBIC_DIR / "versions").glob("*.py")
        if path.name != "__init__.py"
    ]

    assert script.get_heads(), "Alembic has no head revision"
    assert len(script.get_heads()) == 1, f"expected one Alembic head, got {script.get_heads()}"
    assert len(script.get_bases()) == 1, f"expected one Alembic base, got {script.get_bases()}"
    assert len(revisions) == len(version_files), "Alembic did not load every version file"

    children_by_parent: dict[str, list[str]] = defaultdict(list)
    base_revisions: list[str] = []
    for revision in revisions:
        down_revision = revision.down_revision
        if down_revision is None:
            base_revisions.append(revision.revision)
            continue
        assert isinstance(down_revision, str), (
            f"revision {revision.revision} has non-linear down_revision={down_revision!r}"
        )
        children_by_parent[down_revision].append(revision.revision)

    assert len(base_revisions) == 1, f"expected one base revision, got {base_revisions}"
    branch_points = {
        parent: children
        for parent, children in children_by_parent.items()
        if len(children) > 1
    }
    assert not branch_points, f"Alembic branch point(s) found: {branch_points}"

    chain_from_head: list[str] = []
    current_revision = script.get_heads()[0]
    while current_revision is not None:
        chain_from_head.append(current_revision)
        down_revision = revision_by_id[current_revision].down_revision
        current_revision = down_revision if isinstance(down_revision, str) else None

    assert set(chain_from_head) == set(revision_by_id), (
        "Alembic head does not reach every revision; "
        f"chain={chain_from_head}, revisions={sorted(revision_by_id)}"
    )


def test_subscription_last_error_model_and_migration_match():
    table = _table("channel_subscriptions")
    assert "last_error" in table.c
    calls = _record_upgrade("022")
    add = next(call for call in calls if call.name == "add_column")
    assert add.args[0] == "channel_subscriptions"
    assert add.args[1].name == "last_error"


@pytest.mark.parametrize(
    ("table_name", "required_columns"),
    [
        (
            "videos",
            {
                "id",
                "youtube_video_id",
                "channel_id",
                "title",
                "url",
                "status",
                "chat_enabled",
                "last_activity_at",
                "compressed_at",
                "dismissed_at",
                "dismissed_reason",
                "created_at",
                "updated_at",
            },
        ),
        (
            "jobs",
            {
                "id",
                "video_id",
                "channel_id",
                "batch_id",
                "celery_task_id",
                "job_type",
                "status",
                "current_stage",
                "stage_updated_at",
                "current_stage_started_at",
                "last_stage_ended_at",
                "last_ended_stage",
                "last_activity_at",
                "attempt_number",
                "supersedes_job_id",
                "attempt_creation_reason",
                "worker_hostname",
                "worker_task_id",
                "last_artifact_check_result",
                "progress_pct",
                "progress_message",
                "error_message",
                "failure_signature",
                "failure_signature_count",
                "recovery_status",
                "recovery_reason",
                "started_at",
                "completed_at",
                "hidden_from_queue",
                "hidden_reason",
                "hidden_at",
                "superseded_by_job_id",
                "created_at",
            },
        ),
        (
            "video_reports",
            {
                "id",
                "video_id",
                "report_type",
                "title",
                "html_content",
                "markdown_content",
                "artifact_path",
                "model",
                "prompt_tokens",
                "completion_tokens",
                "delivery_status",
                "delivery_error",
                "created_at",
                "updated_at",
            },
        ),
        (
            "channel_subscriptions",
            {
                "id",
                "channel_id",
                "enabled",
                "poll_frequency_hours",
                "max_videos_per_poll",
                "last_polled_at",
                "last_seen_video_ids",
                "videos_ingested_today",
                "daily_counter_reset_at",
                "consecutive_failure_count",
                "disabled_reason",
                "created_at",
            },
        ),
        (
            "digest_lanes",
            {
                "id",
                "label",
                "slug",
                "telegram_user_id",
                "telegram_chat_id",
                "timezone",
                "digest_enabled",
                "role",
                "created_at",
                "updated_at",
            },
        ),
        (
            "lane_subscriptions",
            {
                "id",
                "lane_id",
                "channel_id",
                "enabled",
                "poll_frequency_hours",
                "max_videos_per_poll",
                "last_polled_at",
                "last_seen_video_ids",
                "videos_ingested_today",
                "daily_counter_reset_at",
                "consecutive_failure_count",
                "disabled_reason",
                "created_at",
                "updated_at",
            },
        ),
        (
            "lane_video_items",
            {
                "id",
                "lane_id",
                "video_id",
                "lane_subscription_id",
                "processing_job_id",
                "source",
                "first_seen_at",
                "digest_delivered_at",
                "dismissed_at",
                "created_at",
                "updated_at",
            },
        ),
        (
            "chat_sessions",
            {"id", "title", "platform", "telegram_chat_id", "persona_id", "created_at", "updated_at"},
        ),
        (
            "chat_messages",
            {
                "id",
                "session_id",
                "role",
                "content",
                "sources",
                "model",
                "prompt_tokens",
                "completion_tokens",
                "created_at",
            },
        ),
        (
            "personas",
            {
                "id",
                "scope_type",
                "scope_id",
                "display_name",
                "persona_prompt",
                "style_notes",
                "exemplar_chunk_ids",
                "source_chunk_count",
                "confidence",
                "generated_by_model",
                "generated_at",
                "refresh_after_videos",
                "videos_at_generation",
            },
        ),
        (
            "summaries",
            {"id", "video_id", "content", "model", "prompt_tokens", "completion_tokens", "created_at"},
        ),
        (
            "transcriptions",
            {
                "id",
                "video_id",
                "full_text",
                "language",
                "model_size",
                "word_count",
                "processing_time_seconds",
                "created_at",
            },
        ),
        (
            "transcription_segments",
            {"id", "transcription_id", "segment_index", "start_time", "end_time", "text", "confidence", "speaker"},
        ),
        (
            "embedding_chunks",
            {
                "id",
                "transcription_id",
                "video_id",
                "chunk_index",
                "chunk_text",
                "start_time",
                "end_time",
                "embedding",
                "token_count",
                "speaker",
                "search_vector",
                "created_at",
            },
        ),
        (
            "llm_usage",
            {"id", "model", "input_tokens", "output_tokens", "estimated_cost_usd", "source", "created_at"},
        ),
    ],
)
def test_model_metadata_contains_critical_tables_and_columns(table_name: str, required_columns: set[str]):
    table = _table(table_name)

    missing_columns = sorted(required_columns - set(table.c.keys()))
    assert not missing_columns, f"{table_name} missing critical model columns: {missing_columns}"


def test_jobs_model_preserves_pipeline_state_column_contract():
    jobs = _table("jobs")

    non_nullable_columns = {"id", "job_type", "status", "attempt_number", "failure_signature_count", "hidden_from_queue"}
    nullable_drift = sorted(column for column in non_nullable_columns if jobs.c[column].nullable)
    assert not nullable_drift, f"jobs columns unexpectedly nullable: {nullable_drift}"

    assert jobs.c.attempt_number.server_default is not None
    assert jobs.c.failure_signature_count.server_default is not None
    assert jobs.c.hidden_from_queue.server_default is not None
    assert jobs.c.current_stage.type.length == 64
    assert jobs.c.attempt_creation_reason.type.length == 64
    assert jobs.c.recovery_status.type.length == 32
    assert jobs.c.worker_hostname.type.length == 255
    assert jobs.c.worker_task_id.type.length == 255


def test_video_reports_model_preserves_one_current_summary_report_contract():
    video_reports = _table("video_reports")

    assert video_reports.c.video_id.nullable is False
    assert video_reports.c.report_type.nullable is False
    assert video_reports.c.title.nullable is False
    assert video_reports.c.html_content.nullable is False
    assert video_reports.c.artifact_path.nullable is False
    assert video_reports.c.delivery_status.nullable is False
    assert video_reports.c.markdown_content.nullable is True
    assert video_reports.c.report_type.type.length == 64
    assert video_reports.c.report_type.default is not None
    assert video_reports.c.report_type.default.arg == SUMMARY_REPORT_TYPE
    assert video_reports.c.artifact_path.type.length == 1024

    unique_constraints = _constraint_column_sets(video_reports, UniqueConstraint)
    assert ("video_id",) in unique_constraints
    assert ("video_id", "report_type") not in unique_constraints
    assert _unique_constraint_columns_by_name(video_reports)["uq_video_reports_video_id"] == (
        "video_id",
    )
    assert Video.report.property.uselist is False
    assert (("video_id",), ("videos.id",)) in _foreign_key_targets(video_reports)


def test_subscription_chat_and_persona_model_constraints_are_represented():
    subscriptions = _table("channel_subscriptions")
    personas = _table("personas")
    chat_sessions = _table("chat_sessions")
    chat_messages = _table("chat_messages")

    assert ("channel_id",) in _constraint_column_sets(subscriptions, UniqueConstraint)
    assert ("scope_type", "scope_id") in _constraint_column_sets(personas, UniqueConstraint)
    assert (("persona_id",), ("personas.id",)) in _foreign_key_targets(chat_sessions)
    assert (("session_id",), ("chat_sessions.id",)) in _foreign_key_targets(chat_messages)


def test_recipient_lane_model_constraints_preserve_scope_and_delivery_boundaries():
    lanes = _table("digest_lanes")
    subscriptions = _table("lane_subscriptions")
    items = _table("lane_video_items")

    lane_uniques = _unique_constraint_columns_by_name(lanes)
    assert lane_uniques["uq_digest_lanes_label"] == ("label",)
    assert lane_uniques["uq_digest_lanes_slug"] == ("slug",)
    assert lane_uniques["uq_digest_lanes_telegram_user_id"] == ("telegram_user_id",)
    assert lane_uniques["uq_digest_lanes_telegram_chat_id"] == ("telegram_chat_id",)
    assert ("lane_id", "channel_id") in _constraint_column_sets(
        subscriptions, UniqueConstraint
    )
    assert ("lane_id", "video_id") in _constraint_column_sets(items, UniqueConstraint)
    assert (("lane_id",), ("digest_lanes.id",)) in _foreign_key_targets(subscriptions)
    assert (("lane_id",), ("digest_lanes.id",)) in _foreign_key_targets(items)
    assert (("video_id",), ("videos.id",)) in _foreign_key_targets(items)
    assert (("processing_job_id",), ("jobs.id",)) in _foreign_key_targets(items)


def test_recipient_lane_migration_declares_tables_constraints_and_indexes():
    calls = _record_upgrade("018")
    create_tables = {
        call.args[0]: call
        for call in calls
        if call.name == "create_table"
    }
    assert {"digest_lanes", "lane_subscriptions", "lane_video_items"} <= set(
        create_tables
    )

    lane_constraints = create_tables["digest_lanes"].args[1:]
    assert any(
        isinstance(item, sa.CheckConstraint)
        and item.name == "ck_digest_lanes_role"
        and "restricted" in str(item.sqltext)
        and "admin" in str(item.sqltext)
        for item in lane_constraints
    )

    index_calls = _create_index_calls("018")
    assert list(index_calls["ix_lane_subscriptions_due"].args[2]) == [
        "enabled",
        "last_polled_at",
    ]
    assert list(index_calls["ix_lane_video_items_digest_pending"].args[2]) == [
        "lane_id",
        "digest_delivered_at",
        "dismissed_at",
    ]


def test_jobs_pipeline_contract_columns_are_backed_by_migrations():
    columns_by_table = _columns_created_or_added(["001", "008", "009", "011", "012", "013"])
    expected_jobs_columns = {
        "id",
        "video_id",
        "channel_id",
        "batch_id",
        "celery_task_id",
        "job_type",
        "status",
        "progress_pct",
        "progress_message",
        "error_message",
        "started_at",
        "completed_at",
        "created_at",
        "hidden_from_queue",
        "hidden_reason",
        "hidden_at",
        "superseded_by_job_id",
        "attempt_number",
        "supersedes_job_id",
        "current_stage",
        "stage_updated_at",
        "last_activity_at",
        "failure_signature",
        "failure_signature_count",
        "recovery_status",
        "recovery_reason",
        "current_stage_started_at",
        "last_stage_ended_at",
        "last_ended_stage",
        "attempt_creation_reason",
        "worker_hostname",
        "worker_task_id",
        "last_artifact_check_result",
    }

    missing_columns = sorted(expected_jobs_columns - columns_by_table["jobs"])
    assert not missing_columns, f"jobs migrations do not declare required columns: {missing_columns}"


def test_pipeline_indexes_and_active_attempt_uniqueness_are_declared_in_migrations():
    expected_indexes = {
        "008": {
            "idx_jobs_failed_visible": ("jobs", ["status", "hidden_from_queue", "completed_at"]),
            "idx_jobs_hidden_superseded_cleanup": (
                "jobs",
                ["status", "hidden_from_queue", "hidden_reason", "hidden_at"],
            ),
        },
        "009": {
            "idx_jobs_pipeline_attempt_lineage": ("jobs", ["video_id", "job_type", "attempt_number"]),
            "idx_jobs_pipeline_active_lookup": ("jobs", ["video_id", "job_type", "status", "created_at"]),
        },
        "011": {
            "idx_jobs_pipeline_stage_lookup": ("jobs", ["job_type", "status", "current_stage", "created_at"]),
        },
        "012": {
            "idx_jobs_pipeline_recovery_lookup": (
                "jobs",
                ["video_id", "job_type", "status", "recovery_status", "created_at"],
            ),
        },
        "013": {
            "idx_jobs_pipeline_worker_lookup": (
                "jobs",
                ["job_type", "status", "worker_hostname", "current_stage", "created_at"],
            ),
        },
    }

    for revision, index_contracts in expected_indexes.items():
        calls_by_name = _create_index_calls(revision)
        for index_name, (table_name, columns) in index_contracts.items():
            assert index_name in calls_by_name, f"migration {revision} missing index {index_name}"
            call = calls_by_name[index_name]
            assert call.args[1] == table_name
            assert list(call.args[2]) == columns

    active_index = _create_index_calls("010")["uq_jobs_pipeline_one_active_attempt"]
    assert active_index.args[1] == "jobs"
    assert list(active_index.args[2]) == ["video_id"]
    assert active_index.kwargs.get("unique") is True
    active_predicate = str(active_index.kwargs.get("postgresql_where"))
    assert "video_id IS NOT NULL" in active_predicate
    assert "job_type = 'pipeline'" in active_predicate
    for status in ("pending", "queued", "running"):
        assert status in active_predicate


def test_video_dismissal_fields_are_backed_by_migration_contract():
    columns_by_table = _columns_created_or_added(["016"])
    assert {"dismissed_at", "dismissed_reason"} <= columns_by_table["videos"]

    dismiss_index = _create_index_calls("016")["idx_videos_dismissed_at_null"]
    assert dismiss_index.args[1] == "videos"
    assert list(dismiss_index.args[2]) == ["dismissed_at"]
    assert "dismissed_at IS NULL" in str(dismiss_index.kwargs.get("postgresql_where"))

def test_video_reports_migration_declares_table_uniqueness_and_delivery_index():
    calls = _record_upgrade("017")
    create_table_calls = [call for call in calls if call.name == "create_table" and call.args[0] == "video_reports"]
    assert len(create_table_calls) == 1

    create_table_call = create_table_calls[0]
    columns = {item.name: item for item in create_table_call.args[1:] if isinstance(item, sa.Column)}
    required_columns = {
        "id",
        "video_id",
        "report_type",
        "title",
        "html_content",
        "markdown_content",
        "artifact_path",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "delivery_status",
        "delivery_error",
        "created_at",
        "updated_at",
    }
    assert required_columns <= set(columns)
    assert columns["video_id"].nullable is False
    assert columns["html_content"].nullable is False
    assert columns["artifact_path"].nullable is False

    unique_constraints = [
        item
        for item in create_table_call.args[1:]
        if isinstance(item, UniqueConstraint)
    ]
    unique_column_sets = {
        tuple(column.name for column in constraint.columns)
        or tuple(getattr(constraint, "_pending_colargs", ()))
        for constraint in unique_constraints
    }
    assert ("video_id",) in unique_column_sets
    assert ("video_id", "report_type") not in unique_column_sets
    assert any(
        constraint.name == "uq_video_reports_video_id"
        and (
            tuple(column.name for column in constraint.columns) == ("video_id",)
            or tuple(getattr(constraint, "_pending_colargs", ())) == ("video_id",)
        )
        for constraint in unique_constraints
    )

    delivery_index = _create_index_calls("017")["ix_video_reports_delivery_status"]
    assert delivery_index.args[1] == "video_reports"
    assert list(delivery_index.args[2]) == ["delivery_status"]
