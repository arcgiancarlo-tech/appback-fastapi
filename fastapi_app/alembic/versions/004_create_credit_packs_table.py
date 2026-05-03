"""
Revision ID: 004_create_credit_packs_table
Revises: 003_create_generations_table
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_table(
        'credit_packs',
        sa.Column('id', sa.Integer, primary_key=True, index=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id')),
        sa.Column('pack_name', sa.String, nullable=False),
        sa.Column('credits', sa.Integer, nullable=False),
        sa.Column('price', sa.Float, nullable=False),
        sa.Column('purchased_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

def downgrade():
    op.drop_table('credit_packs')
