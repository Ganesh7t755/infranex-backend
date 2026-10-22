"""create_review_and_dispute_tables

Revision ID: d9345fabd789
Revises: c8234efac456
Create Date: 2026-10-17 15:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd9345fabd789'
down_revision: Union[str, Sequence[str], None] = 'c8234efac456'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 1. Create complaint_disputes table
    op.create_table(
        'complaint_disputes',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('complaint_id', sa.String(length=36), nullable=False),
        sa.Column('citizen_id', sa.String(length=64), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('supporting_evidence_id', sa.String(length=36), nullable=True),
        sa.Column('status', sa.Enum('PENDING_REVIEW', 'UPHELD', 'OVERTURNED', name='disputestatus'), nullable=False),
        sa.Column('reviewer_id', sa.String(length=64), nullable=True),
        sa.Column('reviewer_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['complaint_id'], ['complaints.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['supporting_evidence_id'], ['complaint_evidence.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_complaint_disputes_complaint_id'), 'complaint_disputes', ['complaint_id'], unique=False)
    op.create_index(op.f('ix_complaint_disputes_citizen_id'), 'complaint_disputes', ['citizen_id'], unique=False)
    op.create_index(op.f('ix_complaint_disputes_status'), 'complaint_disputes', ['status'], unique=False)

    # 2. Create complaint_review_decisions table
    op.create_table(
        'complaint_review_decisions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('complaint_id', sa.String(length=36), nullable=False),
        sa.Column('action', sa.Enum('CONFIRM_REPAIR', 'REQUEST_REWORK', 'REQUEST_EVIDENCE', name='reviewdecisionaction'), nullable=False),
        sa.Column('previous_status', sa.String(length=50), nullable=False),
        sa.Column('new_status', sa.String(length=50), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('reviewer_id', sa.String(length=64), nullable=False),
        sa.Column('is_simulation', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['complaint_id'], ['complaints.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_complaint_review_decisions_complaint_id'), 'complaint_review_decisions', ['complaint_id'], unique=False)
    op.create_index(op.f('ix_complaint_review_decisions_reviewer_id'), 'complaint_review_decisions', ['reviewer_id'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_complaint_review_decisions_reviewer_id'), table_name='complaint_review_decisions')
    op.drop_index(op.f('ix_complaint_review_decisions_complaint_id'), table_name='complaint_review_decisions')
    op.drop_table('complaint_review_decisions')

    op.drop_index(op.f('ix_complaint_disputes_status'), table_name='complaint_disputes')
    op.drop_index(op.f('ix_complaint_disputes_citizen_id'), table_name='complaint_disputes')
    op.drop_index(op.f('ix_complaint_disputes_complaint_id'), table_name='complaint_disputes')
    op.drop_table('complaint_disputes')
