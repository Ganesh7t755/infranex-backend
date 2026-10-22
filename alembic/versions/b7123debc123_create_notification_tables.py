"""create_notification_tables

Revision ID: b7123debc123
Revises: a4029debb8f7
Create Date: 2026-10-17 12:38:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7123debc123'
down_revision: Union[str, Sequence[str], None] = 'a4029debb8f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'notification_preferences',
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('notify_status_updates', sa.Boolean(), nullable=False),
        sa.Column('notify_evidence_requests', sa.Boolean(), nullable=False),
        sa.Column('notify_resolution_alerts', sa.Boolean(), nullable=False),
        sa.Column('notify_nearby_alerts', sa.Boolean(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table(
        'notifications',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('complaint_id', sa.String(length=36), nullable=True),
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('message', sa.String(length=500), nullable=False),
        sa.Column('notification_type', sa.Enum('STATUS_UPDATE', 'EVIDENCE_REQUESTED', 'REPAIR_CLAIMED', 'RESOLVED', 'SYSTEM', name='notificationtype'), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['complaint_id'], ['complaints.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notifications_is_read'), 'notifications', ['is_read'], unique=False)
    op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)
    op.create_index(op.f('ix_notifications_complaint_id'), 'notifications', ['complaint_id'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_notifications_complaint_id'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_user_id'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_is_read'), table_name='notifications')
    op.drop_table('notifications')
    op.drop_table('notification_preferences')
