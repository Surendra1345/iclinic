"""convert_to_uuid_and_add_cancellations_reschedules

Revision ID: c4d445a4844d
Revises: b1a9838e2f22
Create Date: 2026-10-14 17:29:39.569289

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID


# revision identifiers, used by Alembic.
revision: str = 'c4d445a4844d'
down_revision: Union[str, None] = 'b1a9838e2f22'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update appointment_status enum with cancelled and rescheduled
    op.execute("ALTER TYPE appointment_status ADD VALUE IF NOT EXISTS 'cancelled'")
    op.execute("ALTER TYPE appointment_status ADD VALUE IF NOT EXISTS 'rescheduled'")

    # 2. Drop existing tables in reverse dependency order to transition cleanly to UUID
    tables_to_drop = [
        "notifications",
        "appointment_reschedules",
        "appointment_cancellations",
        "appointments",
        "outbound_calls",
        "outbound_call_requests",
        "conversations",
        "slots",
        "patients",
        "appointment_types",
        "providers",
        "locations",
    ]
    for table_name in tables_to_drop:
        op.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")

    # 3. Create locations (UUID)
    op.create_table(
        'locations',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sa.String(150), nullable=False),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(100), server_default='system', nullable=False),
        sa.Column('updated_by', sa.String(100), server_default='system', nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # 4. Create providers (UUID)
    op.create_table(
        'providers',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('full_name', sa.String(150), nullable=False),
        sa.Column('specialty', sa.String(100), nullable=True),
        sa.Column('location_id', UUID(as_uuid=True), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(100), server_default='system', nullable=False),
        sa.Column('updated_by', sa.String(100), server_default='system', nullable=False),
        sa.ForeignKeyConstraint(['location_id'], ['locations.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_providers_location_id', 'providers', ['location_id'])
    op.create_index('ix_providers_specialty', 'providers', ['specialty'])

    # 5. Create appointment_types (UUID)
    op.create_table(
        'appointment_types',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False),
        sa.Column('instructions', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(100), server_default='system', nullable=False),
        sa.Column('updated_by', sa.String(100), server_default='system', nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # 6. Create slots (UUID)
    op.create_table(
        'slots',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('provider_id', UUID(as_uuid=True), nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('source_ref', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(100), server_default='system', nullable=False),
        sa.Column('updated_by', sa.String(100), server_default='system', nullable=False),
        sa.ForeignKeyConstraint(['provider_id'], ['providers.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider_id', 'start_time', name='uq_slots_provider_start_time'),
        sa.CheckConstraint('end_time > start_time', name='slots_end_after_start'),
    )
    op.create_index('ix_slots_provider_id', 'slots', ['provider_id'])
    op.create_index('ix_slots_start_time', 'slots', ['start_time'])
    op.create_index('idx_slots_start_provider', 'slots', ['start_time', 'provider_id'])

    # 7. Create patients (UUID)
    op.create_table(
        'patients',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('full_name', sa.String(150), nullable=False),
        sa.Column('date_of_birth', sa.Date(), nullable=False),
        sa.Column('phone', sa.String(30), nullable=False),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(100), server_default='system', nullable=False),
        sa.Column('updated_by', sa.String(100), server_default='system', nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_patients_phone', 'patients', ['phone'])
    op.create_index('ix_patients_full_name_dob', 'patients', ['full_name', 'date_of_birth'])

    # 8. Create conversations (UUID)
    op.create_table(
        'conversations',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('channel', ENUM('voice', 'outbound_call', 'chat', name='channel_type', create_type=False), nullable=False),
        sa.Column('patient_id', UUID(as_uuid=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_state', ENUM('started', 'identifying_patient', 'collecting_details', 'suggesting_slots', 'reconfirming', 'booked', 'confirmation_sent', 'abandoned', 'failed', 'handed_to_front_desk', 'no_answer', 'busy', 'retry_scheduled', name='conversation_state', create_type=False), nullable=False),
        sa.Column('outcome', ENUM('booked', 'abandoned', 'failed', 'handed_to_front_desk', 'not_reached', 'wrong_person', name='outcome_type', create_type=False), nullable=True),
        sa.Column('handoff_reason', sa.Text(), nullable=True),
        sa.Column('confirmation_status', ENUM('pending', 'sent', 'retrying', 'failed', 'flagged', name='confirmation_status_type', create_type=False), nullable=False),
        sa.Column('collected_details', JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('state_history', JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('messages', JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('step_logs', JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(100), server_default='system', nullable=False),
        sa.Column('updated_by', sa.String(100), server_default='system', nullable=False),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_conversations_channel', 'conversations', ['channel'])
    op.create_index('ix_conversations_patient_id', 'conversations', ['patient_id'])
    op.create_index('ix_conversations_started_at', 'conversations', ['started_at'])
    op.create_index('ix_conversations_current_state', 'conversations', ['current_state'])
    op.create_index('ix_conversations_confirmation_status', 'conversations', ['confirmation_status'])
    op.create_index('idx_conversations_channel_state_started', 'conversations', ['channel', 'current_state', 'started_at'])

    # 9. Create outbound_call_requests (UUID)
    op.create_table(
        'outbound_call_requests',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('conversation_id', UUID(as_uuid=True), nullable=False),
        sa.Column('number_to_call', sa.String(30), nullable=False),
        sa.Column('status', ENUM('waiting', 'processing', 'started', 'completed', 'cancelled', 'expired', 'failed', name='outbound_call_request_status', create_type=False), server_default=sa.text("'waiting'"), nullable=False),
        sa.Column('status_reason', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(100), server_default='system', nullable=False),
        sa.Column('updated_by', sa.String(100), server_default='system', nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('conversation_id'),
    )
    op.create_index('ix_outbound_call_requests_expires_at', 'outbound_call_requests', ['expires_at'])
    op.create_index('ix_outbound_call_requests_claimed_at', 'outbound_call_requests', ['claimed_at'])
    op.create_index('idx_outbound_requests_status_created', 'outbound_call_requests', ['status', 'created_at'])
    op.create_index('idx_outbound_requests_number_status', 'outbound_call_requests', ['number_to_call', 'status'])
    op.create_index(
        'one_active_request_per_number',
        'outbound_call_requests',
        ['number_to_call'],
        unique=True,
        postgresql_where=sa.text("status IN ('waiting', 'processing', 'started')"),
    )

    # 10. Create outbound_calls (UUID)
    op.create_table(
        'outbound_calls',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('call_request_id', UUID(as_uuid=True), nullable=False),
        sa.Column('conversation_id', UUID(as_uuid=True), nullable=False),
        sa.Column('provider_call_id', sa.String(100), nullable=True),
        sa.Column('number_called', sa.String(30), nullable=False),
        sa.Column('status', ENUM('dialing', 'no_answer', 'busy', 'answered', 'failed', name='call_status', create_type=False), server_default=sa.text("'dialing'"), nullable=False),
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_event_id', sa.String(100), nullable=True),
        sa.Column('last_event_type', sa.String(100), nullable=True),
        sa.Column('last_event_timestamp', sa.DateTime(timezone=True), nullable=True),
        sa.Column('provider_response', JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(100), server_default='system', nullable=False),
        sa.Column('updated_by', sa.String(100), server_default='system', nullable=False),
        sa.ForeignKeyConstraint(['call_request_id'], ['outbound_call_requests.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('call_request_id', 'attempt_number', name='uq_outbound_calls_request_attempt'),
        sa.UniqueConstraint('provider_call_id'),
    )
    op.create_index('ix_outbound_calls_conversation_id', 'outbound_calls', ['conversation_id'])
    op.create_index('ix_outbound_calls_provider_call_id', 'outbound_calls', ['provider_call_id'])
    op.create_index('ix_outbound_calls_last_event_id', 'outbound_calls', ['last_event_id'])
    op.create_index('idx_outbound_calls_status_retry', 'outbound_calls', ['status', 'next_retry_at'])

    # 11. Create appointments (UUID)
    op.create_table(
        'appointments',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('patient_id', UUID(as_uuid=True), nullable=False),
        sa.Column('slot_id', UUID(as_uuid=True), nullable=False),
        sa.Column('appointment_type_id', UUID(as_uuid=True), nullable=False),
        sa.Column('channel', ENUM('voice', 'outbound_call', 'chat', name='channel_type', create_type=False), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('status', ENUM('booked', 'cancelled', 'rescheduled', name='appointment_status', create_type=False), server_default=sa.text("'booked'"), nullable=False),
        sa.Column('conversation_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(100), server_default='system', nullable=False),
        sa.Column('updated_by', sa.String(100), server_default='system', nullable=False),
        sa.ForeignKeyConstraint(['appointment_type_id'], ['appointment_types.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['slot_id'], ['slots.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('conversation_id'),
    )
    op.create_index('ix_appointments_patient_id', 'appointments', ['patient_id'])
    op.create_index('ix_appointments_slot_id', 'appointments', ['slot_id'])
    op.create_index('ix_appointments_appointment_type_id', 'appointments', ['appointment_type_id'])
    op.create_index('ix_appointments_channel', 'appointments', ['channel'])
    op.create_index('ix_appointments_status', 'appointments', ['status'])
    op.create_index(
        'uq_active_appointment_slot',
        'appointments',
        ['slot_id'],
        unique=True,
        postgresql_where=sa.text("status = 'booked'"),
    )
    op.create_index('idx_appointments_channel_status_created', 'appointments', ['channel', 'status', 'created_at'])

    # 12. Create appointment_cancellations (UUID)
    op.create_table(
        'appointment_cancellations',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('appointment_id', UUID(as_uuid=True), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('conversation_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_appointment_cancellations_appointment_id', 'appointment_cancellations', ['appointment_id'])
    op.create_index('ix_appointment_cancellations_conversation_id', 'appointment_cancellations', ['conversation_id'])
    op.create_index('ix_appointment_cancellations_created_at', 'appointment_cancellations', ['created_at'])

    # 13. Create appointment_reschedules (UUID)
    op.create_table(
        'appointment_reschedules',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('old_appointment_id', UUID(as_uuid=True), nullable=False),
        sa.Column('new_appointment_id', UUID(as_uuid=True), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('conversation_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['old_appointment_id'], ['appointments.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['new_appointment_id'], ['appointments.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('old_appointment_id', 'new_appointment_id', name='uq_reschedules_old_new'),
        sa.CheckConstraint('old_appointment_id <> new_appointment_id', name='check_reschedule_different_appointments'),
    )
    op.create_index('ix_appointment_reschedules_old_appointment_id', 'appointment_reschedules', ['old_appointment_id'])
    op.create_index('ix_appointment_reschedules_new_appointment_id', 'appointment_reschedules', ['new_appointment_id'])
    op.create_index('ix_appointment_reschedules_conversation_id', 'appointment_reschedules', ['conversation_id'])
    op.create_index('ix_appointment_reschedules_created_at', 'appointment_reschedules', ['created_at'])

    # 14. Create notifications (UUID)
    op.create_table(
        'notifications',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('appointment_id', UUID(as_uuid=True), nullable=False),
        sa.Column('channel', ENUM('sms', 'email', name='notification_channel', create_type=False), nullable=False),
        sa.Column('recipient', sa.String(100), nullable=False),
        sa.Column('status', ENUM('pending', 'sent', 'failed', name='notification_status', create_type=False), server_default=sa.text("'pending'"), nullable=False),
        sa.Column('retry_count', sa.Integer(), nullable=False),
        sa.Column('is_fallback', sa.Boolean(), nullable=False),
        sa.Column('error_detail', sa.Text(), nullable=True),
        sa.Column('provider_response', JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('flagged_for_staff', sa.Boolean(), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(100), server_default='system', nullable=False),
        sa.Column('updated_by', sa.String(100), server_default='system', nullable=False),
        sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('appointment_id', 'channel', 'recipient', name='uq_notifications_app_channel_recip'),
    )
    op.create_index('ix_notifications_status', 'notifications', ['status'])
    op.create_index('ix_notifications_flagged_for_staff', 'notifications', ['flagged_for_staff'])


def downgrade() -> None:
    tables_to_drop = [
        "notifications",
        "appointment_reschedules",
        "appointment_cancellations",
        "appointments",
        "outbound_calls",
        "outbound_call_requests",
        "conversations",
        "slots",
        "patients",
        "appointment_types",
        "providers",
        "locations",
    ]
    for table_name in tables_to_drop:
        op.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
