"""Add persistent run stages and append-only analysis events.

Revision ID: 20260715_0002
Revises: 20260714_0001
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260715_0002"
down_revision: str | None = "20260714_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("reports", sa.Column("parent_report_id", sa.String(length=36), nullable=True))
    op.add_column("reports", sa.Column("changed_section_ids_json", sa.JSON(), server_default="[]", nullable=False))
    op.add_column("reports", sa.Column("change_json", sa.JSON(), server_default="{}", nullable=False))
    op.add_column(
        "reports",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index("ix_reports_version", "reports", ["version"])
    op.add_column("messages", sa.Column("metadata_json", sa.JSON(), server_default="{}", nullable=False))
    op.add_column(
        "messages",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_table(
        "analysis_run_stages",
        sa.Column("stage_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("stage_key", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.run_id"]),
        sa.PrimaryKeyConstraint("stage_id"),
        sa.UniqueConstraint("run_id", "stage_key", name="uq_analysis_run_stage"),
    )
    op.create_index("ix_analysis_run_stages_run_id", "analysis_run_stages", ["run_id"])
    op.create_index("ix_analysis_run_stages_status", "analysis_run_stages", ["status"])
    op.create_table(
        "analysis_events",
        sa.Column("event_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("stage_key", sa.String(length=64), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.run_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_analysis_events_run_id", "analysis_events", ["run_id"])
    op.create_index("ix_analysis_events_event_type", "analysis_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_analysis_events_event_type", table_name="analysis_events")
    op.drop_index("ix_analysis_events_run_id", table_name="analysis_events")
    op.drop_table("analysis_events")
    op.drop_index("ix_analysis_run_stages_status", table_name="analysis_run_stages")
    op.drop_index("ix_analysis_run_stages_run_id", table_name="analysis_run_stages")
    op.drop_table("analysis_run_stages")
    op.drop_column("messages", "created_at")
    op.drop_column("messages", "metadata_json")
    op.drop_index("ix_reports_version", table_name="reports")
    op.drop_column("reports", "created_at")
    op.drop_column("reports", "change_json")
    op.drop_column("reports", "changed_section_ids_json")
    op.drop_column("reports", "parent_report_id")
    op.drop_column("reports", "version")
