"""add whatsapp accounts

Revision ID: d7cddc4f5709
Revises: b91b3c8be654
Create Date: 2026-10-01 02:39:37.198370

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d7cddc4f5709"
down_revision: Union[str, Sequence[str], None] = "b91b3c8be654"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create WhatsApp accounts table."""

    op.create_table(
        "whatsapp_accounts",

        sa.Column(
            "id",
            sa.String(length=36),
            nullable=False,
        ),

        sa.Column(
            "tenant_id",
            sa.String(length=36),
            nullable=False,
        ),

        sa.Column(
            "phone_number_id",
            sa.String(),
            nullable=False,
        ),

        sa.Column(
            "waba_id",
            sa.String(),
            nullable=True,
        ),

        sa.Column(
            "display_phone_number",
            sa.String(),
            nullable=True,
        ),

        sa.Column(
            "access_token",
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            "verify_token",
            sa.String(),
            nullable=True,
        ),

        sa.Column(
            "admin_whatsapp_number",
            sa.String(),
            nullable=True,
        ),

        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="active",
        ),

        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),

        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),

        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),

        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone_number_id"),
    )

    # Indexes
    op.create_index(
        "ix_whatsapp_accounts_tenant_id",
        "whatsapp_accounts",
        ["tenant_id"],
        unique=False,
    )

    op.create_index(
        "ix_whatsapp_accounts_phone_number_id",
        "whatsapp_accounts",
        ["phone_number_id"],
        unique=True,
    )

    op.create_index(
        "ix_whatsapp_accounts_waba_id",
        "whatsapp_accounts",
        ["waba_id"],
        unique=False,
    )

    op.create_index(
        "ix_whatsapp_accounts_status",
        "whatsapp_accounts",
        ["status"],
        unique=False,
    )

    op.create_index(
        "ix_whatsapp_accounts_tenant_status",
        "whatsapp_accounts",
        ["tenant_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    """Remove WhatsApp accounts table."""

    op.drop_index(
        "ix_whatsapp_accounts_tenant_status",
        table_name="whatsapp_accounts",
    )

    op.drop_index(
        "ix_whatsapp_accounts_status",
        table_name="whatsapp_accounts",
    )

    op.drop_index(
        "ix_whatsapp_accounts_waba_id",
        table_name="whatsapp_accounts",
    )

    op.drop_index(
        "ix_whatsapp_accounts_phone_number_id",
        table_name="whatsapp_accounts",
    )

    op.drop_index(
        "ix_whatsapp_accounts_tenant_id",
        table_name="whatsapp_accounts",
    )

    op.drop_table("whatsapp_accounts")