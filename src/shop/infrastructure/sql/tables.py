"""Database schema.

Plain SQLAlchemy Core tables, deliberately not mapped onto the domain classes: the domain stays
free of persistence concerns and the repository translates explicitly. The Alembic migration in
``migrations/`` creates the same schema; a test fails if the two drift apart.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    Sequence,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

order_ids = Sequence("orders_id_seq", metadata=metadata)

orders = Table(
    "orders",
    metadata,
    Column("id", BigInteger, order_ids, primary_key=True, autoincrement=False),
    Column("email", Text, nullable=False),
    Column("customer_type", Text, nullable=False),
    Column("total_kopiyky", BigInteger, nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("total_kopiyky >= 0", name="orders_total_non_negative"),
    CheckConstraint(
        "status IN ('new', 'paid', 'shipped', 'delivered', 'cancelled')",
        name="orders_status_known",
    ),
)

order_lines = Table(
    "order_lines",
    metadata,
    Column(
        "order_id",
        BigInteger,
        ForeignKey("orders.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("position", Integer, primary_key=True),
    Column("unit_price_kopiyky", BigInteger, nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("title", Text, nullable=True),
    CheckConstraint("unit_price_kopiyky >= 0", name="order_lines_price_non_negative"),
    CheckConstraint("quantity > 0", name="order_lines_quantity_positive"),
)

outbox = Table(
    "outbox",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("event_type", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("next_attempt_at", DateTime(timezone=True), nullable=False),
    Column("locked_until", DateTime(timezone=True), nullable=True),
    Column("delivered_to", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("last_error", Text, nullable=True),
    CheckConstraint("status IN ('pending', 'delivered', 'dead')", name="outbox_status_known"),
    Index("outbox_due_idx", "status", "next_attempt_at"),
)
