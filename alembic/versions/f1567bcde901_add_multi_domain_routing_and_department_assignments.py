"""add_multi_domain_routing_and_department_assignments

Revision ID: f1567bcde901
Revises: e0456abcd890
Create Date: 2026-10-18 18:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f1567bcde901'
down_revision: Union[str, Sequence[str], None] = 'e0456abcd890'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add multi-domain routing columns to complaints table
    with op.batch_alter_table('complaints', schema=None) as batch_op:
        batch_op.add_column(sa.Column('service_domain', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('assigned_department', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('assignment_status', sa.String(length=50), nullable=False, server_default='UNASSIGNED'))
        batch_op.create_index(batch_op.f('ix_complaints_service_domain'), ['service_domain'], unique=False)

    # 2. Create complaint_assignments table for persistent, auditable department assignment history
    op.create_table(
        'complaint_assignments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('complaint_id', sa.String(length=36), nullable=False),
        sa.Column('service_domain', sa.String(length=50), nullable=False),
        sa.Column('department', sa.String(length=100), nullable=False),
        sa.Column('assignment_status', sa.String(length=50), nullable=False),
        sa.Column('assigned_by', sa.String(length=64), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['complaint_id'], ['complaints.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_complaint_assignments_complaint_id'), 'complaint_assignments', ['complaint_id'], unique=False)
    op.create_index(op.f('ix_complaint_assignments_service_domain'), 'complaint_assignments', ['service_domain'], unique=False)
    op.create_index(op.f('ix_complaint_assignments_department'), 'complaint_assignments', ['department'], unique=False)


def downgrade() -> None:
    # Drop complaint_assignments
    op.drop_index(op.f('ix_complaint_assignments_department'), table_name='complaint_assignments')
    op.drop_index(op.f('ix_complaint_assignments_service_domain'), table_name='complaint_assignments')
    op.drop_index(op.f('ix_complaint_assignments_complaint_id'), table_name='complaint_assignments')
    op.drop_table('complaint_assignments')

    # Drop columns from complaints
    with op.batch_alter_table('complaints', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_complaints_service_domain'))
        batch_op.drop_column('assignment_status')
        batch_op.drop_column('assigned_department')
        batch_op.drop_column('service_domain')
