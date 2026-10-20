"""Allow a new notification record for each appointment lifecycle action."""
from typing import Union

from alembic import op


revision: str = "rm_notif_recipient_unique"
down_revision: Union[str, None] = "e9c31fa7d882"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_notifications_app_channel_recip",
        "notifications",
        type_="unique",
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_notifications_app_channel_recip",
        "notifications",
        ["appointment_id", "channel", "recipient"],
    )
