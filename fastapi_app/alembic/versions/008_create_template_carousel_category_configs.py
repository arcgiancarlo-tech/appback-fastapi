"""
Revision ID: 008_create_template_page_display_configs
Revises: 007_add_template_is_spicy_flag
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa


revision = "008_create_template_page_display_configs"
down_revision = "007_add_template_is_spicy_flag"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "template_page_display_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("page_type", sa.String(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("page_type", "category_id", name="uq_template_page_display_configs_page_type_category_id"),
        sa.UniqueConstraint("page_type", "order", name="uq_template_page_display_configs_page_type_order"),
    )
    op.create_index(op.f("ix_template_page_display_configs_id"), "template_page_display_configs", ["id"], unique=False)
    op.create_index(op.f("ix_template_page_display_configs_page_type"), "template_page_display_configs", ["page_type"], unique=False)
    op.create_index(op.f("ix_template_page_display_configs_category_id"), "template_page_display_configs", ["category_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_template_page_display_configs_category_id"), table_name="template_page_display_configs")
    op.drop_index(op.f("ix_template_page_display_configs_page_type"), table_name="template_page_display_configs")
    op.drop_index(op.f("ix_template_page_display_configs_id"), table_name="template_page_display_configs")
    op.drop_table("template_page_display_configs")
