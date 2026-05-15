"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-14 22:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("api_key_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("api_key_hash"),
    )

    op.create_table(
        "endpoints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("secret", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("endpoint_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["endpoint_id"], ["endpoints.id"]),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_deliveries_event_id", "deliveries", ["event_id"])
    op.create_index("ix_deliveries_endpoint_id", "deliveries", ["endpoint_id"])
    op.create_index("ix_deliveries_next_retry_at", "deliveries", ["next_retry_at"])
    op.create_index(
        "ix_deliveries_status_retry", "deliveries", ["status", "next_retry_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_deliveries_status_retry", table_name="deliveries")
    op.drop_index("ix_deliveries_next_retry_at", table_name="deliveries")
    op.drop_index("ix_deliveries_endpoint_id", table_name="deliveries")
    op.drop_index("ix_deliveries_event_id", table_name="deliveries")
    op.drop_table("deliveries")
    op.drop_table("events")
    op.drop_table("endpoints")
    op.drop_table("tenants")
