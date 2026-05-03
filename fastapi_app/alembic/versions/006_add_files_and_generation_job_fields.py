"""
Revision ID: 006_add_files_and_generation_job_fields
Revises: 005_add_generation_credits_used
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa


revision = "006_add_files_and_generation_job_fields"
down_revision = "005_add_generation_credits_used"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("storage_driver", sa.String(), nullable=False, server_default="local_private_disk"),
        sa.Column("relative_path", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checksum", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_files_id", "files", ["id"])
    op.create_index("ix_files_owner_user_id", "files", ["owner_user_id"])
    op.create_unique_constraint("uq_files_relative_path", "files", ["relative_path"])

    op.add_column("generations", sa.Column("input_file_id", sa.Integer(), nullable=True))
    op.add_column("generations", sa.Column("output_file_id", sa.Integer(), nullable=True))
    op.add_column("generations", sa.Column("comfyui_job_id", sa.String(), nullable=True))
    op.add_column("generations", sa.Column("comfyui_server_id", sa.String(), nullable=True))
    op.add_column("generations", sa.Column("workflow_key", sa.String(), nullable=True))
    op.add_column("generations", sa.Column("result_kind", sa.String(), nullable=True))
    op.add_column("generations", sa.Column("error_code", sa.String(), nullable=True))
    op.add_column("generations", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("generations", sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("generations", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("generations", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_generations_input_file_id", "generations", "files", ["input_file_id"], ["id"])
    op.create_foreign_key("fk_generations_output_file_id", "generations", "files", ["output_file_id"], ["id"])


def downgrade():
    op.drop_constraint("fk_generations_output_file_id", "generations", type_="foreignkey")
    op.drop_constraint("fk_generations_input_file_id", "generations", type_="foreignkey")
    op.drop_column("generations", "failed_at")
    op.drop_column("generations", "started_at")
    op.drop_column("generations", "queued_at")
    op.drop_column("generations", "error_message")
    op.drop_column("generations", "error_code")
    op.drop_column("generations", "result_kind")
    op.drop_column("generations", "workflow_key")
    op.drop_column("generations", "comfyui_server_id")
    op.drop_column("generations", "comfyui_job_id")
    op.drop_column("generations", "output_file_id")
    op.drop_column("generations", "input_file_id")

    op.drop_constraint("uq_files_relative_path", "files", type_="unique")
    op.drop_index("ix_files_owner_user_id", table_name="files")
    op.drop_index("ix_files_id", table_name="files")
    op.drop_table("files")
