"""add tenant phone composite indexes

Revision ID: e5d0c3baa524
Revises: da45964328d5
Create Date: 2026-10-07
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "e5d0c3baa524"
down_revision: Union[str, Sequence[str], None] = "da45964328d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_leads_tenant_phone",
        "leads",
        ["tenant_id", "phone"],
        unique=False,
    )

    op.create_index(
        "ix_messages_tenant_sender_phone",
        "messages",
        ["tenant_id", "sender_phone"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_messages_tenant_sender_phone",
        table_name="messages",
    )

    op.drop_index(
        "ix_leads_tenant_phone",
        table_name="leads",
    )