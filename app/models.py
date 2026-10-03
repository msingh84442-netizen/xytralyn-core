import uuid

from datetime import datetime



from sqlalchemy import (

    Column,

    String,

    DateTime,

    Text,

    ForeignKey,

    Index,

)


from sqlalchemy.orm import relationship



from app.database import Base





# ============================================================

# TENANT

# ============================================================



class Tenant(Base):

    __tablename__ = "tenants"



    id = Column(

        String(36),

        primary_key=True,

        default=lambda: str(uuid.uuid4()),

    )



    name = Column(

        String,

        nullable=False,

    )



    slug = Column(

        String,

        unique=True,

        index=True,

        nullable=False,

    )



    industry = Column(

        String,

        nullable=False,

        default="general",

    )



    status = Column(

        String,

        nullable=False,

        default="active",

        index=True,

    )



    created_at = Column(

        DateTime,

        default=datetime.utcnow,

        nullable=False,

    )



    updated_at = Column(

        DateTime,

        default=datetime.utcnow,

        onupdate=datetime.utcnow,

        nullable=False,

    )



    # Relationships

    memberships = relationship(

        "Membership",

        back_populates="tenant",

        cascade="all, delete-orphan",

    )



    leads = relationship(

        "Lead",

        back_populates="tenant",

    )



    messages = relationship(

        "Message",

        back_populates="tenant",



    )



    tickets = relationship(

        "Ticket",

        back_populates="tenant",

    )



    whatsapp_accounts = relationship(

        "WhatsAppAccount",

        back_populates="tenant",

        cascade="all, delete-orphan",

    )





# ============================================================

# USER

# ============================================================



class User(Base):

    __tablename__ = "users"



    id = Column(

        String(36),

        primary_key=True,

        default=lambda: str(uuid.uuid4()),

    )



    email = Column(

        String,

        unique=True,

        index=True,

        nullable=False,

    )



    # Kept for backward compatibility with the current system.

    # Later, business information will primarily live under Tenant.

    business_name = Column(

        String,

        nullable=False,

    )



    phone = Column(

        String,

        unique=True,

        nullable=False,

    )



    created_at = Column(

        DateTime,

        default=datetime.utcnow,

        nullable=False,

    )



    # Relationships

    memberships = relationship(

        "Membership",

        back_populates="user",

        cascade="all, delete-orphan",

    )



    leads = relationship(

        "Lead",

        back_populates="user",

    )



    messages = relationship(

        "Message",

        back_populates="user",

    )



    tickets = relationship(

        "Ticket",

        back_populates="user",

    )





# ============================================================

# MEMBERSHIP

# ============================================================



class Membership(Base):

    __tablename__ = "memberships"



    id = Column(

        String(36),

        primary_key=True,

        default=lambda: str(uuid.uuid4()),

    )



    user_id = Column(

        String(36),

        ForeignKey("users.id"),

        nullable=False,

        index=True,

    )



    tenant_id = Column(

        String(36),

        ForeignKey("tenants.id"),

        nullable=False,

        index=True,

    )



    role = Column(

        String,

        nullable=False,

        default="owner",

    )



    status = Column(

        String,

        nullable=False,

        default="active",

    )



    created_at = Column(

        DateTime,

        default=datetime.utcnow,

        nullable=False,

    )



    # Relationships

    user = relationship(

        "User",

        back_populates="memberships",

    )



    tenant = relationship(

        "Tenant",

        back_populates="memberships",

    )





# ============================================================

# LEAD

# ============================================================



class Lead(Base):

    __tablename__ = "leads"



    id = Column(

        String(36),

        primary_key=True,

        default=lambda: str(uuid.uuid4()),

    )



    # Multi-tenant ownership

    tenant_id = Column(

        String(36),

        ForeignKey("tenants.id"),

        nullable=True,

        index=True,

    )



    # Kept for backward compatibility

    user_id = Column(

        String(36),

        ForeignKey("users.id"),

        nullable=True,

        index=True,

    )



    name = Column(

        String,

        nullable=True,

    )



    email = Column(

        String,

        nullable=True,

    )



    company = Column(

        String,

        nullable=True,

    )



    phone = Column(

        String,

        index=True,

        nullable=True,

    )



    business_type = Column(

        String,

        nullable=True,

    )



    lead_volume = Column(

        String,

        nullable=True,

    )



    interested_agent = Column(

        String,

        nullable=True,

    )



    status = Column(

        String,

        default="new",

        index=True,

    )



    demo_date = Column(

        String,

        nullable=True,

    )



    demo_time = Column(

        String,

        nullable=True,

    )



    demo_datetime = Column(

        String,

        nullable=True,

    )



    demo_status = Column(

        String,

        default="not_scheduled",

    )



    created_at = Column(

        DateTime,

        default=datetime.utcnow,

        nullable=False,

    )



    # Relationships

    tenant = relationship(

        "Tenant",

        back_populates="leads",

    )



    user = relationship(

        "User",

        back_populates="leads",

    )



    __table_args__ = (

        Index(

            "ix_leads_tenant_status",

            "tenant_id",

            "status",

        ),

    )





# ============================================================

# MESSAGE

# ============================================================



class Message(Base):

    __tablename__ = "messages"



    id = Column(

        String(36),

        primary_key=True,

        default=lambda: str(uuid.uuid4()),

    )



    # Multi-tenant ownership

    tenant_id = Column(

        String(36),

        ForeignKey("tenants.id"),

        nullable=True,

        index=True,

    )



    # Kept for backward compatibility

    user_id = Column(

        String(36),

        ForeignKey("users.id"),

        nullable=True,

        index=True,

    )



    sender_phone = Column(

        String,

        index=True,

        nullable=True,

    )



    content = Column(

        Text,

        nullable=True,

    )



    agent_used = Column(

        String,

        nullable=True,

    )



    sender_type = Column(

        String,

        nullable=True,

    )



    timestamp = Column(

        DateTime,

        default=datetime.utcnow,

        nullable=False,

    )



    # Relationships

    tenant = relationship(

        "Tenant",

        back_populates="messages",

    )



    user = relationship(

        "User",

        back_populates="messages",

    )



    __table_args__ = (

        Index(

            "ix_messages_tenant_timestamp",

            "tenant_id",

            "timestamp",

        ),

    )





# ============================================================

# TICKET

# ============================================================



class Ticket(Base):

    __tablename__ = "tickets"



    id = Column(

        String(36),

        primary_key=True,

        default=lambda: str(uuid.uuid4()),

    )



    # Multi-tenant ownership

    tenant_id = Column(

        String(36),

        ForeignKey("tenants.id"),

        nullable=True,

        index=True,

    )



    # Optional user association

    user_id = Column(

        String(36),

        ForeignKey("users.id"),

        nullable=True,

        index=True,

    )



    customer_phone = Column(

        String,

        index=True,

        nullable=False,

    )



    ticket_number = Column(

        String,

        unique=True,

        index=True,

        nullable=False,

    )



    subject = Column(

        String,

        nullable=False,

    )



    description = Column(

        Text,

        nullable=False,

    )



    category = Column(

        String,

        default="general",

        nullable=False,

    )



    priority = Column(

        String,

        default="medium",

        nullable=False,

        index=True,

    )



    status = Column(

        String,

        default="open",

        nullable=False,

        index=True,

    )



    assigned_to = Column(

        String,

        nullable=True,

    )



    created_at = Column(

        DateTime,

        default=datetime.utcnow,

        nullable=False,

    )



    updated_at = Column(

        DateTime,

        default=datetime.utcnow,

        onupdate=datetime.utcnow,

        nullable=False,

    )



    resolved_at = Column(

        DateTime,

        nullable=True,

    )



    # Relationships

    tenant = relationship(

        "Tenant",

        back_populates="tickets",

    )



    user = relationship(

        "User",

        back_populates="tickets",

    )



    __table_args__ = (

        Index(

            "ix_tickets_tenant_status",

            "tenant_id",

            "status",

        ),

        Index(

            "ix_tickets_tenant_priority",

            "tenant_id",

            "priority",

        ),

    )

   # ============================================================

# WHATSAPP ACCOUNT

# ============================================================



class WhatsAppAccount(Base):

    __tablename__ = "whatsapp_accounts"



    id = Column(

        String(36),

        primary_key=True,

        default=lambda: str(uuid.uuid4()),

    )



    # Which Xytralyn tenant owns this WhatsApp account

    tenant_id = Column(

        String(36),

        ForeignKey("tenants.id"),

        nullable=False,

        index=True,

    )



    # Meta WhatsApp Business identifiers

    phone_number_id = Column(

        String,

        unique=True,

        index=True,

        nullable=False,

    )



    waba_id = Column(

        String,

        nullable=True,

        index=True,

    )



    display_phone_number = Column(

        String,

        nullable=True,

    )



    # Meta credentials

    access_token = Column(

        Text,

        nullable=True,

    )



    verify_token = Column(

        String,

        nullable=True,

    )



    # Tenant-specific admin number for escalations

    admin_whatsapp_number = Column(

        String,

        nullable=True,

    )



    # active / inactive

    status = Column(

        String,

        nullable=False,

        default="active",

        index=True,

    )



    created_at = Column(

        DateTime,

        default=datetime.utcnow,

        nullable=False,

    )



    updated_at = Column(

        DateTime,

        default=datetime.utcnow,

        onupdate=datetime.utcnow,

        nullable=False,

    )



    # Relationship

    tenant = relationship(

        "Tenant",

        back_populates="whatsapp_accounts",

    )



    __table_args__ = (

        Index(

            "ix_whatsapp_accounts_tenant_status",

            "tenant_id",

            "status",

        ),

    )