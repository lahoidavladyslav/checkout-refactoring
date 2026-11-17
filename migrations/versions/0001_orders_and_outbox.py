"""Orders, order lines and the transactional outbox.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.schema.CreateSequence(sa.Sequence("orders_id_seq")))
    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("customer_type", sa.Text(), nullable=False),
        sa.Column("total_kopiyky", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("total_kopiyky >= 0", name="orders_total_non_negative"),
        sa.CheckConstraint(
            "status IN ('new', 'paid', 'shipped', 'delivered', 'cancelled')",
            name="orders_status_known",
        ),
    )
    op.create_table(
        "order_lines",
        sa.Column(
            "order_id",
            sa.BigInteger(),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("unit_price_kopiyky", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.CheckConstraint("unit_price_kopiyky >= 0", name="order_lines_price_non_negative"),
        sa.CheckConstraint("quantity > 0", name="order_lines_quantity_positive"),
    )
    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "delivered_to",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'delivered', 'dead')", name="outbox_status_known"
        ),
    )
    op.create_index("outbox_due_idx", "outbox", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_index("outbox_due_idx", table_name="outbox")
    op.drop_table("outbox")
    op.drop_table("order_lines")
    op.drop_table("orders")
    op.execute(sa.schema.DropSequence(sa.Sequence("orders_id_seq")))
