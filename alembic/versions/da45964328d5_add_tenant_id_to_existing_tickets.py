"""add tenant id to existing tickets

Revision ID: da45964328d5
Revises: d7cddc4f5709
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "da45964328d5"

down_revision: Union[str, Sequence[str], None] = "d7cddc4f5709"

branch_labels: Union[str, Sequence[str], None] = None

depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    # ============================================================
    # Get database connection
    # ============================================================

    connection = op.get_bind()

    inspector = sa.inspect(connection)

    existing_tables = inspector.get_table_names()

    # ============================================================
    # Safety check: tickets table must exist
    # ============================================================

    if "tickets" not in existing_tables:
        raise RuntimeError(
            "The 'tickets' table was not found. "
            "Cannot add tenant_id to tickets."
        )

    # ============================================================
    # Check whether tenant_id already exists
    # ============================================================

    ticket_columns = [
        column["name"]
        for column in inspector.get_columns("tickets")
    ]

    # ============================================================
    # 1. Add tenant_id as nullable
    # ============================================================

    # Existing tickets already exist in the database, therefore
    # tenant_id must initially be nullable so the existing rows
    # can be safely backfilled.

    if "tenant_id" not in ticket_columns:

        op.add_column(
            "tickets",
            sa.Column(
                "tenant_id",
                sa.String(length=36),
                nullable=True,
            ),
        )

    # ============================================================
    # 2. Find existing Xytralyn tenant
    # ============================================================

    tenant_result = connection.execute(
        sa.text(
            """
            SELECT id
            FROM tenants
            WHERE slug = 'xytralyn'
            LIMIT 1
            """
        )
    ).fetchone()

    if tenant_result is None:

        raise RuntimeError(
            "Xytralyn tenant was not found. "
            "Existing tickets cannot be safely backfilled."
        )

    xytralyn_tenant_id = tenant_result[0]

    # ============================================================
    # 3. Backfill existing legacy tickets
    # ============================================================

    connection.execute(
        sa.text(
            """
            UPDATE tickets
            SET tenant_id = :tenant_id
            WHERE tenant_id IS NULL
            """
        ),
        {
            "tenant_id": xytralyn_tenant_id,
        },
    )

    # ============================================================
    # 4. Safety check
    # ============================================================

    remaining = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM tickets
            WHERE tenant_id IS NULL
            """
        )
    ).scalar()

    if remaining is None:
        remaining = 0

    if int(remaining) != 0:

        raise RuntimeError(
            f"{remaining} ticket(s) still have NULL tenant_id."
        )

    # ============================================================
    # 5. Add foreign key
    # ============================================================

    inspector = sa.inspect(connection)

    foreign_keys = inspector.get_foreign_keys("tickets")

    tenant_foreign_key_exists = False

    for foreign_key in foreign_keys:

        constrained_columns = foreign_key.get(
            "constrained_columns",
            [],
        )

        referred_table = foreign_key.get(
            "referred_table",
        )

        referred_columns = foreign_key.get(
            "referred_columns",
            [],
        )

        if (
            constrained_columns == ["tenant_id"]
            and referred_table == "tenants"
            and referred_columns == ["id"]
        ):

            tenant_foreign_key_exists = True
            break

    if not tenant_foreign_key_exists:

        op.create_foreign_key(
            "fk_tickets_tenant_id",
            "tickets",
            "tenants",
            ["tenant_id"],
            ["id"],
        )

    # ============================================================
    # 6. Add index
    # ============================================================

    inspector = sa.inspect(connection)

    existing_indexes = inspector.get_indexes("tickets")

    tenant_index_exists = False

    for index in existing_indexes:

        if index.get("name") == "ix_tickets_tenant_id":

            tenant_index_exists = True
            break

    if not tenant_index_exists:

        op.create_index(
            "ix_tickets_tenant_id",
            "tickets",
            ["tenant_id"],
            unique=False,
        )

    # ============================================================
    # 7. Enforce NOT NULL
    # ============================================================

    op.alter_column(
        "tickets",
        "tenant_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )


def downgrade() -> None:

    # ============================================================
    # Get database connection
    # ============================================================

    connection = op.get_bind()

    inspector = sa.inspect(connection)

    existing_tables = inspector.get_table_names()

    # ============================================================
    # Safety check: tickets table
    # ============================================================

    if "tickets" not in existing_tables:
        return

    # ============================================================
    # Check tenant_id column
    # ============================================================

    ticket_columns = [
        column["name"]
        for column in inspector.get_columns("tickets")
    ]

    if "tenant_id" not in ticket_columns:
        return

    # ============================================================
    # Drop foreign key
    # ============================================================

    inspector = sa.inspect(connection)

    foreign_keys = inspector.get_foreign_keys("tickets")

    for foreign_key in foreign_keys:

        constraint_name = foreign_key.get("name")

        constrained_columns = foreign_key.get(
            "constrained_columns",
            [],
        )

        referred_table = foreign_key.get(
            "referred_table",
        )

        referred_columns = foreign_key.get(
            "referred_columns",
            [],
        )

        if (
            constraint_name
            and constrained_columns == ["tenant_id"]
            and referred_table == "tenants"
            and referred_columns == ["id"]
        ):

            op.drop_constraint(
                constraint_name,
                "tickets",
                type_="foreignkey",
            )

    # ============================================================
    # Drop index
    # ============================================================

    inspector = sa.inspect(connection)

    existing_indexes = inspector.get_indexes("tickets")

    tenant_index_exists = False

    for index in existing_indexes:

        if index.get("name") == "ix_tickets_tenant_id":

            tenant_index_exists = True
            break

    if tenant_index_exists:

        op.drop_index(
            "ix_tickets_tenant_id",
            table_name="tickets",
        )

    # ============================================================
    # Drop tenant_id
    # ============================================================

    op.drop_column(
        "tickets",
        "tenant_id",
    )