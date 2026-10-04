"""add multi tenant foundation

Revision ID: b91b3c8be654
Revises: c658d7e2625a
Create Date: 2026-10-01 01:48:54.511056

"""

from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "b91b3c8be654"
down_revision: Union[str, Sequence[str], None] = "c658d7e2625a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    try:
        op.create_table(
            "tenants",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("slug", sa.String(), nullable=False),
            sa.Column("industry", sa.String(), nullable=False, server_default="general"),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("slug", name="uq_tenants_slug"),
        )
        op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)
        op.create_index("ix_tenants_status", "tenants", ["status"], unique=False)
    except Exception as e:
        print(f"Skipping tenants creation: {e}")

    try:
        op.create_table(
            "memberships",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), nullable=True),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("role", sa.String(), nullable=False, server_default="owner"),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "tenant_id", name="uq_memberships_user_tenant"),
        )
        op.create_index("ix_memberships_user_id", "memberships", ["user_id"], unique=False)
        op.create_index("ix_memberships_tenant_id", "memberships", ["tenant_id"], unique=False)
    except Exception as e:
        print(f"Skipping memberships creation: {e}")

    try:
        with op.batch_alter_table("leads", schema=None) as batch_op:
            batch_op.add_column(sa.Column("tenant_id", sa.String(length=36), nullable=True))
            batch_op.create_index("ix_leads_tenant_id", ["tenant_id"], unique=False)
    except Exception as e:
        print(f"Skipping leads alter: {e}")

    try:
        with op.batch_alter_table("messages", schema=None) as batch_op:
            batch_op.add_column(sa.Column("tenant_id", sa.String(length=36), nullable=True))
            batch_op.create_index("ix_messages_tenant_id", ["tenant_id"], unique=False)
    except Exception as e:
        print(f"Skipping messages alter: {e}")

    default_tenant_id = str(uuid.uuid4())
    try:
        op.execute(
            sa.text(
                """
                INSERT INTO tenants (id, name, slug, industry, status)
                VALUES (:id, :name, :slug, :industry, :status)
                ON CONFLICT (slug) DO NOTHING
                """
            ).bindparams(
                id=default_tenant_id,
                name="Xytralyn",
                slug="xytralyn",
                industry="general",
                status="active",
            )
        )
    except Exception as e:
        print(f"Skipping default tenant: {e}")

    try:
        op.create_table(
            "tickets",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tenant_id", sa.String(length=36), nullable=True),
            sa.Column("user_id", sa.String(length=36), nullable=True),
            sa.Column("customer_phone", sa.String(), nullable=False),
            sa.Column("ticket_number", sa.String(), nullable=False),
            sa.Column("subject", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("category", sa.String(), nullable=False, server_default="general"),
            sa.Column("priority", sa.String(), nullable=False, server_default="medium"),
            sa.Column("status", sa.String(), nullable=False, server_default="open"),
            sa.Column("assigned_to", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("ticket_number", name="uq_tickets_ticket_number"),
        )
        op.create_index("ix_tickets_tenant_id", "tickets", ["tenant_id"], unique=False)
        op.create_index("ix_tickets_customer_phone", "tickets", ["customer_phone"], unique=False)
        op.create_index("ix_tickets_ticket_number", "tickets", ["ticket_number"], unique=True)
        op.create_index("ix_tickets_status", "tickets", ["status"], unique=False)
        op.create_index("ix_tickets_priority", "tickets", ["priority"], unique=False)
    except Exception as e:
        print(f"Skipping tickets creation: {e}")


def downgrade() -> None:
    pass