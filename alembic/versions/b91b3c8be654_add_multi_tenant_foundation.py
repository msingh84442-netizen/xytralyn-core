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
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # 1. Tenants table
    if "tenants" not in existing_tables:
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

    # 2. Memberships table
    if "memberships" not in existing_tables:
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

    # 3. Add tenant_id to leads
    if "leads" in existing_tables:
        lead_cols = [c["name"] for c in inspector.get_columns("leads")]
        if "tenant_id" not in lead_cols:
            with op.batch_alter_table("leads", schema=None) as batch_op:
                batch_op.add_column(sa.Column("tenant_id", sa.String(length=36), nullable=True))
                batch_op.create_index("ix_leads_tenant_id", ["tenant_id"], unique=False)

    # 4. Add tenant_id to messages
    if "messages" in existing_tables:
        msg_cols = [c["name"] for c in inspector.get_columns("messages")]
        if "tenant_id" not in msg_cols:
            with op.batch_alter_table("messages", schema=None) as batch_op:
                batch_op.add_column(sa.Column("tenant_id", sa.String(length=36), nullable=True))
                batch_op.create_index("ix_messages_tenant_id", ["tenant_id"], unique=False)

    # 5. Seed default tenant if not present
    default_tenant_id = str(uuid.uuid4())
    existing_tenant = conn.execute(
        sa.text("SELECT id FROM tenants WHERE slug = 'xytralyn'")
    ).fetchone()
    if not existing_tenant:
        conn.execute(
            sa.text(
                """
                INSERT INTO tenants (id, name, slug, industry, status)
                VALUES (:id, :name, :slug, :industry, :status)
                """
            ).bindparams(
                id=default_tenant_id,
                name="Xytralyn",
                slug="xytralyn",
                industry="general",
                status="active",
            )
        )

    # 6. Tickets table
    if "tickets" not in existing_tables:
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


def downgrade() -> None:
    pass