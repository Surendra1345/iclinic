"""Fix reschedule audit columns for in-place appointment updates."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "20261018_2200"
down_revision = "rm_notif_recipient_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "check_reschedule_different_appointments",
        "appointment_reschedules",
        type_="check",
    )
    op.drop_constraint(
        "uq_reschedules_old_new",
        "appointment_reschedules",
        type_="unique",
    )
    op.add_column(
        "appointment_reschedules",
        sa.Column("old_slot_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "appointment_reschedules",
        sa.Column("new_slot_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_reschedules_old_slot",
        "appointment_reschedules",
        "slots",
        ["old_slot_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_reschedules_new_slot",
        "appointment_reschedules",
        "slots",
        ["new_slot_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        """
        UPDATE appointment_reschedules ar
        SET old_slot_id = a.slot_id, new_slot_id = a.slot_id
        FROM appointments a
        WHERE a.id = ar.new_appointment_id
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_reschedules_new_slot", "appointment_reschedules", type_="foreignkey")
    op.drop_constraint("fk_reschedules_old_slot", "appointment_reschedules", type_="foreignkey")
    op.drop_column("appointment_reschedules", "new_slot_id")
    op.drop_column("appointment_reschedules", "old_slot_id")
    op.create_unique_constraint(
        "uq_reschedules_old_new",
        "appointment_reschedules",
        ["old_appointment_id", "new_appointment_id"],
    )
    op.create_check_constraint(
        "check_reschedule_different_appointments",
        "appointment_reschedules",
        "old_appointment_id <> new_appointment_id",
    )
