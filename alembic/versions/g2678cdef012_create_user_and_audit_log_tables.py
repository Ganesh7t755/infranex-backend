"""create_user_and_audit_log_tables

Revision ID: g2678cdef012
Revises: f1567bcde901
Create Date: 2026-10-21 15:10:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'g2678cdef012'
down_revision: Union[str, Sequence[str], None] = 'f1567bcde901'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = insp.get_table_names()

    # 1. Create users table if not exists
    if 'users' not in existing_tables:
        op.create_table(
            'users',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('username', sa.String(length=64), nullable=False),
            sa.Column('email', sa.String(length=120), nullable=True),
            sa.Column('full_name', sa.String(length=120), nullable=True),
            sa.Column('password_hash', sa.String(length=255), nullable=False),
            sa.Column('role', sa.String(length=32), nullable=False),
            sa.Column('department', sa.String(length=100), nullable=True),
            sa.Column('service_domains', sa.String(length=255), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('last_login_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
        op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
        op.create_index(op.f('ix_users_role'), 'users', ['role'], unique=False)

    # 2. Create audit_logs table if not exists
    if 'audit_logs' not in existing_tables:
        op.create_table(
            'audit_logs',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('user_id', sa.String(length=64), nullable=True),
            sa.Column('username', sa.String(length=64), nullable=True),
            sa.Column('role', sa.String(length=32), nullable=True),
            sa.Column('action', sa.String(length=64), nullable=False),
            sa.Column('resource_type', sa.String(length=64), nullable=True),
            sa.Column('resource_id', sa.String(length=64), nullable=True),
            sa.Column('details', sa.String(length=2000), nullable=True),
            sa.Column('ip_address', sa.String(length=45), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_audit_logs_user_id'), 'audit_logs', ['user_id'], unique=False)
        op.create_index(op.f('ix_audit_logs_username'), 'audit_logs', ['username'], unique=False)
        op.create_index(op.f('ix_audit_logs_role'), 'audit_logs', ['role'], unique=False)
        op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
        op.create_index(op.f('ix_audit_logs_resource_type'), 'audit_logs', ['resource_type'], unique=False)
        op.create_index(op.f('ix_audit_logs_resource_id'), 'audit_logs', ['resource_id'], unique=False)
        op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = insp.get_table_names()

    if 'audit_logs' in existing_tables:
        op.drop_index(op.f('ix_audit_logs_created_at'), table_name='audit_logs')
        op.drop_index(op.f('ix_audit_logs_resource_id'), table_name='audit_logs')
        op.drop_index(op.f('ix_audit_logs_resource_type'), table_name='audit_logs')
        op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
        op.drop_index(op.f('ix_audit_logs_role'), table_name='audit_logs')
        op.drop_index(op.f('ix_audit_logs_username'), table_name='audit_logs')
        op.drop_index(op.f('ix_audit_logs_user_id'), table_name='audit_logs')
        op.drop_table('audit_logs')

    if 'users' in existing_tables:
        op.drop_index(op.f('ix_users_role'), table_name='users')
        op.drop_index(op.f('ix_users_email'), table_name='users')
        op.drop_index(op.f('ix_users_username'), table_name='users')
        op.drop_table('users')
