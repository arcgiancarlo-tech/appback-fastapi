"""
Revision ID: 009_template_page_display_configs_followup_noop
Revises: 008_create_template_page_display_configs
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa


revision = "009_template_page_display_configs_followup_noop"
down_revision = "008_create_template_page_display_configs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "template_page_display_configs",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )


def downgrade():
    op.drop_column("template_page_display_configs", "is_active")
