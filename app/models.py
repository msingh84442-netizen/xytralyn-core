import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    email = Column(
        String,
        unique=True,
        index=True,
        nullable=False
    )

    business_name = Column(
        String,
        nullable=False
    )

    phone = Column(
        String,
        unique=True,
        nullable=False
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


class Lead(Base):
    __tablename__ = "leads"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True
    )

    # ============================================================
    # BASIC LEAD INFORMATION
    # ============================================================

    name = Column(
        String,
        nullable=True
    )

    email = Column(
        String,
        nullable=True
    )

    company = Column(
        String,
        nullable=True
    )

    phone = Column(
        String,
        index=True
    )

    # ============================================================
    # LEAD QUALIFICATION
    # ============================================================

    business_type = Column(
        String,
        nullable=True
    )

    lead_volume = Column(
        String,
        nullable=True
    )

    interested_agent = Column(
        String,
        nullable=True
    )

    # ============================================================
    # LEAD STATUS
    # ============================================================

    status = Column(
        String,
        default="new"
    )

    # ============================================================
    # DEMO INFORMATION
    # ============================================================

    demo_date = Column(
        String,
        nullable=True
    )

    demo_time = Column(
        String,
        nullable=True
    )

    demo_datetime = Column(
        String,
        nullable=True
    )

    demo_status = Column(
        String,
        default="not_scheduled"
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


class Message(Base):
    __tablename__ = "messages"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True
    )

    sender_phone = Column(
        String,
        index=True
    )

    content = Column(
        Text
    )

    agent_used = Column(
        String
    )

    # ============================================================
    # MESSAGE TYPE
    # user / assistant
    # ============================================================

    sender_type = Column(
        String,
        nullable=True
    )

    timestamp = Column(
        DateTime,
        default=datetime.utcnow
    )


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    # ============================================================
    # CUSTOMER / TENANT
    # ============================================================

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True
    )

    customer_phone = Column(
        String,
        index=True,
        nullable=False
    )

    # ============================================================
    # TICKET INFORMATION
    # ============================================================

    ticket_number = Column(
        String,
        unique=True,
        index=True,
        nullable=False
    )

    subject = Column(
        String,
        nullable=False
    )

    description = Column(
        Text,
        nullable=False
    )

    # ============================================================
    # CLASSIFICATION
    # ============================================================

    category = Column(
        String,
        default="general",
        nullable=False
    )

    priority = Column(
        String,
        default="medium",
        nullable=False
    )

    # ============================================================
    # STATUS
    # ============================================================

    status = Column(
        String,
        default="open",
        nullable=False
    )

    # ============================================================
    # ASSIGNMENT
    # ============================================================

    assigned_to = Column(
        String,
        nullable=True
    )

    # ============================================================
    # TIMESTAMPS
    # ============================================================

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    resolved_at = Column(
        DateTime,
        nullable=True
    )