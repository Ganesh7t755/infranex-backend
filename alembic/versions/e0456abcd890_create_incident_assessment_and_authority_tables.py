"""create_incident_assessment_and_authority_tables

Revision ID: e0456abcd890
Revises: d9345fabd789
Create Date: 2026-10-18 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e0456abcd890'
down_revision: Union[str, Sequence[str], None] = 'd9345fabd789'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 1. Create incident_assessments table
    op.create_table(
        'incident_assessments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('complaint_id', sa.String(length=36), nullable=False),
        sa.Column('evidence_id', sa.String(length=36), nullable=True),
        sa.Column('provider_id', sa.String(length=64), nullable=False),
        sa.Column('model_name', sa.String(length=64), nullable=False),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column('category_match', sa.Boolean(), nullable=True),
        sa.Column('detected_category', sa.String(length=64), nullable=True),
        sa.Column('evidence_suitable', sa.Boolean(), nullable=False),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('limitations', sa.String(length=1000), nullable=True),
        sa.Column('is_simulation', sa.Boolean(), nullable=False),
        sa.Column('review_required', sa.Boolean(), nullable=False),
        sa.Column('assessment_metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['complaint_id'], ['complaints.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['evidence_id'], ['complaint_evidence.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_incident_assessments_complaint_id'), 'incident_assessments', ['complaint_id'], unique=False)
    op.create_index(op.f('ix_incident_assessments_evidence_id'), 'incident_assessments', ['evidence_id'], unique=False)

    # 2. Create authority_actions table
    op.create_table(
        'authority_actions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('complaint_id', sa.String(length=36), nullable=False),
        sa.Column('authority_id', sa.String(length=64), nullable=False),
        sa.Column('department', sa.String(length=100), nullable=False),
        sa.Column('action_type', sa.String(length=50), nullable=False),
        sa.Column('work_order_reference', sa.String(length=64), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['complaint_id'], ['complaints.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_authority_actions_complaint_id'), 'authority_actions', ['complaint_id'], unique=False)
    op.create_index(op.f('ix_authority_actions_authority_id'), 'authority_actions', ['authority_id'], unique=False)

def downgrade() -> None:
    # Drop authority_actions
    op.drop_index(op.f('ix_authority_actions_authority_id'), table_name='authority_actions')
    op.drop_index(op.f('ix_authority_actions_complaint_id'), table_name='authority_actions')
    op.drop_table('authority_actions')

    # Drop incident_assessments
    op.drop_index(op.f('ix_incident_assessments_evidence_id'), table_name='incident_assessments')
    op.drop_index(op.f('ix_incident_assessments_complaint_id'), table_name='incident_assessments')
    op.drop_table('incident_assessments')
