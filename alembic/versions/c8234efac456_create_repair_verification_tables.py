"""create_repair_verification_tables

Revision ID: c8234efac456
Revises: b7123debc123
Create Date: 2026-10-17 15:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c8234efac456'
down_revision: Union[str, Sequence[str], None] = 'b7123debc123'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'repair_verifications',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('complaint_id', sa.String(length=36), nullable=False),
        sa.Column('before_evidence_id', sa.String(length=36), nullable=True),
        sa.Column('after_evidence_id', sa.String(length=36), nullable=True),
        sa.Column('outcome', sa.Enum('LIKELY_RESOLVED', 'LIKELY_UNRESOLVED', 'INCONCLUSIVE', name='repairverificationoutcome'), nullable=False),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('observations', sa.JSON(), nullable=False),
        sa.Column('evidence_quality', sa.String(length=255), nullable=False),
        sa.Column('limitations', sa.String(length=1000), nullable=False),
        sa.Column('provider_id', sa.String(length=64), nullable=False),
        sa.Column('model_name', sa.String(length=64), nullable=False),
        sa.Column('is_simulation', sa.Boolean(), nullable=False),
        sa.Column('human_review_required', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['complaint_id'], ['complaints.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['before_evidence_id'], ['complaint_evidence.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['after_evidence_id'], ['complaint_evidence.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_repair_verifications_complaint_id'), 'repair_verifications', ['complaint_id'], unique=False)
    op.create_index(op.f('ix_repair_verifications_outcome'), 'repair_verifications', ['outcome'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_repair_verifications_outcome'), table_name='repair_verifications')
    op.drop_index(op.f('ix_repair_verifications_complaint_id'), table_name='repair_verifications')
    op.drop_table('repair_verifications')
