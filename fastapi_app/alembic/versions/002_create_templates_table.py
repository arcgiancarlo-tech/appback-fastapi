"""
Revision ID: 002_create_templates_table
Revises: 001_create_users_table
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_table(
        'templates',
        sa.Column('id', sa.Integer, primary_key=True, index=True),
        sa.Column('name', sa.String, nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('category', sa.String, nullable=True),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

def downgrade():
    op.drop_table('templates')
