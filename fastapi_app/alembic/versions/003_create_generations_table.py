"""
Revision ID: 003_create_generations_table
Revises: 002_create_templates_table
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_table(
        'generations',
        sa.Column('id', sa.Integer, primary_key=True, index=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id')),
        sa.Column('template_id', sa.Integer, sa.ForeignKey('templates.id')),
        sa.Column('input_path', sa.String, nullable=False),
        sa.Column('output_path', sa.String, nullable=True),
        sa.Column('status', sa.String, default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )

def downgrade():
    op.drop_table('generations')
