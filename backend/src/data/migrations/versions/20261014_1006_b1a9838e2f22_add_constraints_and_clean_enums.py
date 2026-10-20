
"""add_constraints_and_clean_enums

Revision ID: b1a9838e2f22
Revises: 4a2ed1ed7c56
Create Date: 2026-10-14 10:06:21.153382

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b1a9838e2f22'
down_revision: Union[str, None] = '4a2ed1ed7c56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENUM_RENAMES = [
    ("channel_type", [("VOICE", "voice"), ("OUTBOUND_CALL", "outbound_call"), ("CHAT", "chat")]),
    ("appointment_status", [("BOOKED", "booked")]),
    (
        "conversation_state",
        [
            ("STARTED", "started"),
            ("IDENTIFYING_PATIENT", "identifying_patient"),
            ("COLLECTING_DETAILS", "collecting_details"),
            ("SUGGESTING_SLOTS", "suggesting_slots"),
            ("RECONFIRMING", "reconfirming"),
            ("BOOKED", "booked"),
            ("CONFIRMATION_SENT", "confirmation_sent"),
            ("ABANDONED", "abandoned"),
            ("FAILED", "failed"),
            ("HANDED_TO_FRONT_DESK", "handed_to_front_desk"),
            ("NO_ANSWER", "no_answer"),
            ("BUSY", "busy"),
            ("RETRY_SCHEDULED", "retry_scheduled"),
        ],
    ),
    (
        "outcome_type",
        [
            ("BOOKED", "booked"),
            ("ABANDONED", "abandoned"),
            ("FAILED", "failed"),
            ("HANDED_TO_FRONT_DESK", "handed_to_front_desk"),
            ("NOT_REACHED", "not_reached"),
            ("WRONG_PERSON", "wrong_person"),
        ],
    ),
    (
        "confirmation_status_type",
        [
            ("PENDING", "pending"),
            ("SENT", "sent"),
            ("RETRYING", "retrying"),
            ("FAILED", "failed"),
            ("FLAGGED", "flagged"),
        ],
    ),
    (
        "outbound_call_request_status",
        [
            ("WAITING", "waiting"),
            ("PROCESSING", "processing"),
            ("STARTED", "started"),
            ("COMPLETED", "completed"),
            ("CANCELLED", "cancelled"),
            ("EXPIRED", "expired"),
            ("FAILED", "failed"),
        ],
    ),
    (
        "call_status",
        [
            ("DIALING", "dialing"),
            ("NO_ANSWER", "no_answer"),
            ("BUSY", "busy"),
            ("ANSWERED", "answered"),
            ("FAILED", "failed"),
        ],
    ),
    ("notification_channel", [("SMS", "sms"), ("EMAIL", "email")]),
    ("notification_status", [("PENDING", "pending"), ("SENT", "sent"), ("FAILED", "failed")]),
]


def upgrade() -> None:
    # 1. Convert PostgreSQL enums to canonical lowercase
    for enum_type, pairs in ENUM_RENAMES:
        for old_val, new_val in pairs:
            op.execute(sa.text(f"ALTER TYPE {enum_type} RENAME VALUE '{old_val}' TO '{new_val}'"))

    # 2. Patient modifications: email NOT NULL + composite lookup index
    op.alter_column('patients', 'email',
               existing_type=sa.VARCHAR(length=255),
               nullable=False)
    op.create_index('ix_patients_full_name_dob', 'patients', ['full_name', 'date_of_birth'], unique=False)

    # 3. Slots constraints & FK restriction
    op.drop_index(op.f('ix_slots_provider_start_time'), table_name='slots')
    op.create_unique_constraint('uq_slots_provider_start_time', 'slots', ['provider_id', 'start_time'])
    op.drop_constraint('slots_provider_id_fkey', 'slots', type_='foreignkey')
    op.create_foreign_key('fk_slots_provider_id_providers', 'slots', 'providers', ['provider_id'], ['id'], ondelete='RESTRICT')

    # 4. Appointment constraints: prevent double booking & 1:1 conversation link
    op.create_unique_constraint('uq_appointments_slot_id', 'appointments', ['slot_id'])
    op.create_unique_constraint('uq_appointments_conversation_id', 'appointments', ['conversation_id'])

    # 5. Conversation started_at nullable
    op.alter_column('conversations', 'started_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True)

    # 6. Outbound call request constraints
    op.create_unique_constraint('uq_outbound_call_requests_conversation_id', 'outbound_call_requests', ['conversation_id'])
    op.create_index(
        'uq_open_outbound_requests_number',
        'outbound_call_requests',
        ['number_to_call'],
        unique=True,
        postgresql_where=sa.text("status IN ('waiting', 'processing')"),
    )

    # 7. Outbound call constraints: unique provider_call_id + attempt unique per request
    op.drop_index(op.f('ix_outbound_calls_provider_call_id'), table_name='outbound_calls')
    op.create_index('ix_outbound_calls_provider_call_id', 'outbound_calls', ['provider_call_id'], unique=True)
    op.create_unique_constraint('uq_outbound_calls_request_attempt', 'outbound_calls', ['call_request_id', 'attempt_number'])

    # 8. Server defaults for audit fields & is_active
    all_tables = [
        'appointment_types', 'locations', 'patients', 'conversations',
        'providers', 'slots', 'outbound_call_requests', 'outbound_calls',
        'appointments', 'notifications'
    ]
    for table in all_tables:
        op.alter_column(table, 'created_by', server_default='system')
        op.alter_column(table, 'updated_by', server_default='system')

    for table in ['locations', 'providers', 'appointment_types', 'patients']:
        op.alter_column(table, 'is_active', server_default='true')


def downgrade() -> None:
    # 8. Remove server defaults
    for table in ['locations', 'providers', 'appointment_types', 'patients']:
        op.alter_column(table, 'is_active', server_default=None)

    all_tables = [
        'appointment_types', 'locations', 'patients', 'conversations',
        'providers', 'slots', 'outbound_call_requests', 'outbound_calls',
        'appointments', 'notifications'
    ]
    for table in all_tables:
        op.alter_column(table, 'created_by', server_default=None)
        op.alter_column(table, 'updated_by', server_default=None)

    # 7. Revert outbound call constraints
    op.drop_constraint('uq_outbound_calls_request_attempt', 'outbound_calls', type_='unique')
    op.drop_index('ix_outbound_calls_provider_call_id', table_name='outbound_calls')
    op.create_index(op.f('ix_outbound_calls_provider_call_id'), 'outbound_calls', ['provider_call_id'], unique=False)

    # 6. Revert outbound call request constraints
    op.drop_index('uq_open_outbound_requests_number', table_name='outbound_call_requests', postgresql_where=sa.text("status IN ('waiting', 'processing')"))
    op.drop_constraint('uq_outbound_call_requests_conversation_id', 'outbound_call_requests', type_='unique')

    # 5. Revert conversation started_at
    op.alter_column('conversations', 'started_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False)

    # 4. Revert appointment constraints
    op.drop_constraint('uq_appointments_conversation_id', 'appointments', type_='unique')
    op.drop_constraint('uq_appointments_slot_id', 'appointments', type_='unique')

    # 3. Revert slot constraints & FK
    op.drop_constraint('fk_slots_provider_id_providers', 'slots', type_='foreignkey')
    op.create_foreign_key('slots_provider_id_fkey', 'slots', 'providers', ['provider_id'], ['id'], ondelete='CASCADE')
    op.drop_constraint('uq_slots_provider_start_time', 'slots', type_='unique')
    op.create_index(op.f('ix_slots_provider_start_time'), 'slots', ['provider_id', 'start_time'], unique=False)

    # 2. Revert patient modifications
    op.drop_index('ix_patients_full_name_dob', table_name='patients')
    op.alter_column('patients', 'email',
               existing_type=sa.VARCHAR(length=255),
               nullable=True)

    # 1. Revert enums to uppercase
    for enum_type, pairs in ENUM_RENAMES:
        for old_val, new_val in pairs:
            op.execute(sa.text(f"ALTER TYPE {enum_type} RENAME VALUE '{new_val}' TO '{old_val}'"))

