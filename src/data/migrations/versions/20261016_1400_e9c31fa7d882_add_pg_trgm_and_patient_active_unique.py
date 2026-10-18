"""add_pg_trgm_and_patient_active_unique

Revision ID: e9c31fa7d882
Revises: be85ae9be4d7
Create Date: 2026-10-16 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9c31fa7d882'
down_revision: Union[str, None] = 'be85ae9be4d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Enable pg_trgm extension for fuzzy name search
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # 2. Add unique partial index: one active (booked) appointment per patient
    op.create_index(
        'uq_one_active_per_patient',
        'appointments',
        ['patient_id'],
        unique=True,
        postgresql_where=sa.text("status = 'booked'"),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_one_active_per_patient',
        table_name='appointments',
        postgresql_where=sa.text("status = 'booked'"),
    )
    # Notice: we generally don't drop pg_trgm as other extensions/tables may use it
