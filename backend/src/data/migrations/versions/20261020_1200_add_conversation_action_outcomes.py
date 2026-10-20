"""Add distinct conversation statuses for reschedules and cancellations."""
from alembic import op


revision = "20261020_1200"
down_revision = "20261018_2200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE conversation_state ADD VALUE IF NOT EXISTS 'rescheduled'")
    op.execute("ALTER TYPE conversation_state ADD VALUE IF NOT EXISTS 'cancelled'")
    op.execute("ALTER TYPE outcome_type ADD VALUE IF NOT EXISTS 'rescheduled'")
    op.execute("ALTER TYPE outcome_type ADD VALUE IF NOT EXISTS 'cancelled'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values safely in place.
    pass
