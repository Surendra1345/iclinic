"""add_slot_status_patient_source_and_verified_at

Revision ID: be85ae9be4d7
Revises: c4d445a4844d
Create Date: 2026-10-16 11:24:21.284998

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM


# revision identifiers, used by Alembic.
revision: str = 'be85ae9be4d7'
down_revision: Union[str, None] = 'c4d445a4844d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update existing Postgres Enums
    op.execute("ALTER TYPE appointment_status ADD VALUE IF NOT EXISTS 'completed'")
    op.execute("ALTER TYPE conversation_state ADD VALUE IF NOT EXISTS 'slot_reserved'")

    # 2. Add identity_verified_at to conversations
    op.add_column('conversations', sa.Column('identity_verified_at', sa.DateTime(timezone=True), nullable=True))

    # 3. Consolidate provider_call_id unique index
    op.drop_constraint(op.f('outbound_calls_provider_call_id_key'), 'outbound_calls', type_='unique')
    op.drop_index(op.f('ix_outbound_calls_provider_call_id'), table_name='outbound_calls')
    op.create_index(op.f('ix_outbound_calls_provider_call_id'), 'outbound_calls', ['provider_call_id'], unique=True)

    # 4. Create patient_source enum and add source to patients
    patient_source_enum = ENUM('assistant', 'front_desk', name='patient_source', create_type=False)
    op.execute("DO $$ BEGIN CREATE TYPE patient_source AS ENUM ('assistant', 'front_desk'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.add_column('patients', sa.Column('source', patient_source_enum, server_default=sa.text("'assistant'"), nullable=False))

    # 5. Create slot_status enum and add status & reserved_until to slots
    slot_status_enum = ENUM('available', 'reserved', 'booked', name='slot_status', create_type=False)
    op.execute("DO $$ BEGIN CREATE TYPE slot_status AS ENUM ('available', 'reserved', 'booked'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.add_column('slots', sa.Column('status', slot_status_enum, server_default=sa.text("'available'"), nullable=False))
    op.add_column('slots', sa.Column('reserved_until', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_slots_status'), 'slots', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_slots_status'), table_name='slots')
    op.drop_column('slots', 'reserved_until')
    op.drop_column('slots', 'status')
    op.drop_column('patients', 'source')
    op.execute("DROP TYPE IF EXISTS slot_status CASCADE")
    op.execute("DROP TYPE IF EXISTS patient_source CASCADE")
    op.drop_index(op.f('ix_outbound_calls_provider_call_id'), table_name='outbound_calls')
    op.create_index(op.f('ix_outbound_calls_provider_call_id'), 'outbound_calls', ['provider_call_id'], unique=False)
    op.create_unique_constraint(op.f('outbound_calls_provider_call_id_key'), 'outbound_calls', ['provider_call_id'])
    op.drop_column('conversations', 'identity_verified_at')
