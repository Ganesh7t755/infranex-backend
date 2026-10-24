"""reconcile_postgresql_enums

Revision ID: h3789cdef013
Revises: g2678cdef012
Create Date: 2026-10-24 17:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h3789cdef013'
down_revision: Union[str, Sequence[str], None] = 'g2678cdef012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# New enum values required by SQLAlchemy models and workflow transitions
COMPLAINT_STATUS_NEW_VALUES = [
    'PROCESSING',
    'REVIEW_REQUIRED',
    'MORE_EVIDENCE_REQUIRED',
    'VERIFIED',
    'REJECTED',
    'AUTHORITY_QUEUE',
    'ACTION_IN_PROGRESS',
    'RESOLVED',
]

ACTOR_TYPE_NEW_VALUES = [
    'AUTHORITY',
]

REVIEW_DECISION_ACTION_NEW_VALUES = [
    'APPROVE',
    'REJECT',
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # In PostgreSQL, ALTER TYPE ... ADD VALUE cannot be executed inside a standard transaction block.
        # Alembic provides autocommit_block() to safely execute non-transactional DDL.
        with op.get_context().autocommit_block():
            for val in COMPLAINT_STATUS_NEW_VALUES:
                op.execute(sa.text(f"ALTER TYPE complaintstatus ADD VALUE IF NOT EXISTS '{val}'"))

            for val in ACTOR_TYPE_NEW_VALUES:
                op.execute(sa.text(f"ALTER TYPE actortype ADD VALUE IF NOT EXISTS '{val}'"))

            for val in REVIEW_DECISION_ACTION_NEW_VALUES:
                op.execute(sa.text(f"ALTER TYPE reviewdecisionaction ADD VALUE IF NOT EXISTS '{val}'"))


def downgrade() -> None:
    # PostgreSQL does not natively support removing values from an enum type (ALTER TYPE ... DROP VALUE).
    # Reversing enum additions safely would require recreating the enum types and tables.
    pass
