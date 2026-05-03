"""
Revision ID: 007_add_template_is_spicy_flag
Revises: 006_add_files_and_generation_job_fields
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa


revision = "007_add_template_is_spicy_flag"
down_revision = "006_add_files_and_generation_job_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "templates",
        sa.Column("is_spicy", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )


def downgrade():
    op.drop_column("templates", "is_spicy")
