"""
Revision ID: 005_add_generation_credits_used
Revises: 004_create_credit_packs_table
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa


revision = "005_add_generation_credits_used"
down_revision = "004_create_credit_packs_table"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "generations",
        sa.Column("credits_used", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("generations", "credits_used")
