"""add multi tenant foundation

Revision ID: b91b3c8be654
Revises: c658d7e2625a
Create Date: 2026-10-01 01:48:54.511056

"""

from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b91b3c8be654"
down_revision: Union[str, Sequence[str], None] = "c658d7e2625a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the initial multi-tenant foundation."""

    # ---------------------------------------------------------
    # 1. Create tenants table
    # ---------------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column(
            "industry",
            sa.String(),
            nullable=False,
            server_default="general",
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
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )

    op.create_index(
        "ix_tenants_slug",
        "tenants",
        ["slug"],
        unique=True,
    )

    op.create_index(
        "ix_tenants_status",
        "tenants",
        ["status"],
        unique=False,
    )

    # ---------------------------------------------------------
    # 2. Create memberships table
    # ---------------------------------------------------------
        try:
        op.create_table(
            "memberships",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), nullable=True),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("role", sa.String(length=50), nullable=False, server_default="owner"),
            sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    except Exception as e:
        print(f"Skipping memberships table creation: {e}")

    op.create_index(
        "ix_memberships_user_id",
        "memberships",
        ["user_id"],
        unique=False,
    )

    op.create_index(
        "ix_memberships_tenant_id",
        "memberships",
        ["tenant_id"],
        unique=False,
    )

    # ---------------------------------------------------------
    # 3. Add tenant_id to leads
    # ---------------------------------------------------------
    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "tenant_id",
                sa.String(length=36),
                nullable=True,
            )
        )

        batch_op.create_index(
            "ix_leads_tenant_id",
            ["tenant_id"],
            unique=False,
        )

        batch_op.create_foreign_key(
            "fk_leads_tenant_id",
            "tenants",
            ["tenant_id"],
            ["id"],
        )

    # ---------------------------------------------------------
    # 4. Add tenant_id to messages
    # ---------------------------------------------------------
    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "tenant_id",
                sa.String(length=36),
                nullable=True,
            )
        )

        batch_op.create_index(
            "ix_messages_tenant_id",
            ["tenant_id"],
            unique=False,
        )

        batch_op.create_foreign_key(
            "fk_messages_tenant_id",
            "tenants",
            ["tenant_id"],
            ["id"],
        )

    # ---------------------------------------------------------
    # 5. Create default tenant for existing Xytralyn data
    # ---------------------------------------------------------
    default_tenant_id = str(uuid.uuid4())

    op.execute(
        sa.text(
            """
            INSERT INTO tenants
                (id, name, slug, industry, status)
            VALUES
                (:id, :name, :slug, :industry, :status)
            """
        ).bindparams(
            id=default_tenant_id,
            name="Xytralyn",
            slug="xytralyn",
            industry="general",
            status="active",
        )
    )

    # ---------------------------------------------------------
    # 6. Backfill existing leads
    # ---------------------------------------------------------
    op.execute(
        sa.text(
            """
            UPDATE leads
            SET tenant_id = :tenant_id
            WHERE tenant_id IS NULL
            """
        ).bindparams(
            tenant_id=default_tenant_id
        )
    )

    # ---------------------------------------------------------
    # 7. Backfill existing messages
    # ---------------------------------------------------------
    op.execute(
        sa.text(
            """
            UPDATE messages
            SET tenant_id = :tenant_id
            WHERE tenant_id IS NULL
            """
        ).bindparams(
            tenant_id=default_tenant_id
        )
    )

    # ---------------------------------------------------------
    # 8. Create tickets table
    # ---------------------------------------------------------
        try:
        op.create_table(
            "tickets",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tenant_id", sa.String(length=36), nullable=True),
            sa.Column("user_id", sa.String(length=36), nullable=True),
            sa.Column("customer_phone", sa.String(length=50), nullable=False),
            sa.Column("ticket_number", sa.String(length=50), nullable=False),
            sa.Column("subject", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("category", sa.String(length=50), nullable=False, server_default="general"),
            sa.Column("priority", sa.String(length=50), nullable=False, server_default="medium"),
            sa.Column("status", sa.String(length=50), nullable=False, server_default="open"),
            sa.Column("assigned_to", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
        )
    except Exception as e:
        print(f"Skipping tickets table creation: {e}")

    op.create_index(
        "ix_tickets_tenant_id",
        "tickets",
        ["tenant_id"],
        unique=False,
    )

    op.create_index(
        "ix_tickets_customer_phone",
        "tickets",
        ["customer_phone"],
        unique=False,
    )

    op.create_index(
        "ix_tickets_ticket_number",
        "tickets",
        ["ticket_number"],
        unique=True,
    )

    op.create_index(
        "ix_tickets_status",
        "tickets",
        ["status"],
        unique=False,
    )

    op.create_index(
        "ix_tickets_priority",
        "tickets",
        ["priority"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the multi-tenant foundation."""

    # Drop tickets first because it references tenants/users.
    op.drop_index("ix_tickets_priority", table_name="tickets")
    op.drop_index("ix_tickets_status", table_name="tickets")
    op.drop_index("ix_tickets_ticket_number", table_name="tickets")
    op.drop_index("ix_tickets_customer_phone", table_name="tickets")
    op.drop_index("ix_tickets_tenant_id", table_name="tickets")
    op.drop_table("tickets")

    # Remove tenant_id from messages.
    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_messages_tenant_id",
            type_="foreignkey",
        )
        batch_op.drop_index("ix_messages_tenant_id")
        batch_op.drop_column("tenant_id")

    # Remove tenant_id from leads.
    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_leads_tenant_id",
            type_="foreignkey",
        )
        batch_op.drop_index("ix_leads_tenant_id")
        batch_op.drop_column("tenant_id")

    # Drop memberships.
    op.drop_index(
        "ix_memberships_tenant_id",
        table_name="memberships",
    )
    op.drop_index(
        "ix_memberships_user_id",
        table_name="memberships",
    )
    op.drop_table("memberships")

    # Drop tenants.
    op.drop_index("ix_tenants_status", table_name="tenants")
    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")


