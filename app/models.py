import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, index=True, nullable=False)
    business_name = Column(String, nullable=False)
    phone = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Lead(Base):
    __tablename__ = "leads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True
    )

    # Basic lead information
    name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    company = Column(String, nullable=True)
    phone = Column(String, index=True)

    # Lead qualification
    business_type = Column(String, nullable=True)
    lead_volume = Column(String, nullable=True)
    interested_agent = Column(String, nullable=True)

    # Lead status
    status = Column(String, default="new")

    # Demo information
    demo_date = Column(String, nullable=True)
    demo_time = Column(String, nullable=True)
    demo_datetime = Column(String, nullable=True)
    demo_status = Column(String, default="not_scheduled")

    created_at = Column(DateTime, default=datetime.utcnow)


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True
    )

    sender_phone = Column(String, index=True)
    content = Column(Text)
    agent_used = Column(String)

    # VERY IMPORTANT:
    # user / assistant
    sender_type = Column(String, nullable=True)

    timestamp = Column(DateTime, default=datetime.utcnow)