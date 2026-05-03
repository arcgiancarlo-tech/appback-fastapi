"""
Revision ID: 006_create_revenuecat_webhook_events_table
Revises: 005_add_generation_credits_used
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa


revision = "006_create_revenuecat_webhook_events_table"
down_revision = "005_add_generation_credits_used"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "revenuecat_webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("refund_kind", sa.String(), nullable=False),
        sa.Column("app_user_id", sa.String(), nullable=False),
        sa.Column("product_id", sa.String(), nullable=True),
        sa.Column("transaction_id", sa.String(), nullable=True),
        sa.Column("original_transaction_id", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("credits_revoked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancel_reason", sa.String(), nullable=True),
        sa.Column("environment", sa.String(), nullable=True),
        sa.Column("raw_payload", sa.Text(), nullable=False),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_revenuecat_webhook_events_id", "revenuecat_webhook_events", ["id"])
    op.create_index("ix_revenuecat_webhook_events_event_id", "revenuecat_webhook_events", ["event_id"], unique=True)


def downgrade():
    op.drop_index("ix_revenuecat_webhook_events_event_id", table_name="revenuecat_webhook_events")
    op.drop_index("ix_revenuecat_webhook_events_id", table_name="revenuecat_webhook_events")
    op.drop_table("revenuecat_webhook_events")
