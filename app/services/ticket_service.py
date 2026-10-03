"""
Xytralyn Ticket Service
-----------------------
Multi-tenant Support Ticket Service.

Responsibilities:
- Create support tickets in the SQLAlchemy database.
- Generate unique human-readable ticket numbers.
- Prevent unnecessary duplicate open tickets.
- Keep all ticket queries tenant-scoped.
- Update ticket status and priority.
- Assign tickets safely.
- Fetch tickets safely.
- Keep database logic separate from support_agent.py and chat.py.

This service does NOT:
- send WhatsApp messages
- call Groq
- decide the support response
- contain customer-specific hardcoded data

Those responsibilities belong to other layers.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Ticket


logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

VALID_CATEGORIES = {
    "technical",
    "billing",
    "account",
    "product",
    "general",
    "other",
}

VALID_PRIORITIES = {
    "low",
    "medium",
    "high",
    "urgent",
}

VALID_STATUSES = {
    "open",
    "in_progress",
    "resolved",
    "closed",
}


OPEN_STATUSES = {
    "open",
    "in_progress",
}


CLOSED_STATUSES = {
    "resolved",
    "closed",
}


# ============================================================================
# BASIC HELPERS
# ============================================================================


def _clean_text(value: Any) -> str:
    """
    Safely convert a value into normalized text.
    """
    if value is None:
        return ""

    return re.sub(r"\s+", " ", str(value).strip())


def normalize_customer_phone(phone: Any) -> Optional[str]:
    """
    Normalize an Indian WhatsApp phone number into 10-digit format.

    Examples:
        +91 98765 43210 -> 9876543210
        919876543210    -> 9876543210
        9876543210      -> 9876543210
    """

    if phone is None:
        return None

    digits = re.sub(r"\D", "", str(phone))

    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]

    if len(digits) != 10:
        return None

    if digits[0] not in "6789":
        return None

    return digits


def _safe_category(category: Any) -> str:
    """
    Normalize and validate ticket category.
    """

    value = _clean_text(category).lower()

    if value in VALID_CATEGORIES:
        return value

    return "general"


def _safe_priority(priority: Any) -> str:
    """
    Normalize and validate ticket priority.
    """

    value = _clean_text(priority).lower()

    if value in VALID_PRIORITIES:
        return value

    return "medium"


def _safe_status(status: Any) -> str:
    """
    Normalize and validate ticket status.
    """

    value = _clean_text(status).lower()

    if value in VALID_STATUSES:
        return value

    return "open"


def _validate_tenant_id(tenant_id: Any) -> bool:
    """
    Validate that a tenant_id has been supplied.

    Tenant isolation is mandatory for ticket operations.
    """

    return tenant_id is not None


def _generate_ticket_number() -> str:
    """
    Generate a readable ticket identifier.

    Example:
        XYT-20261001-A1B2C3D4
    """

    date_part = datetime.utcnow().strftime("%Y%m%d")
    random_part = uuid.uuid4().hex[:8].upper()

    return f"XYT-{date_part}-{random_part}"


# ============================================================================
# TICKET SERIALIZATION
# ============================================================================


def ticket_to_dict(
    ticket: Optional[Ticket],
) -> Optional[Dict[str, Any]]:
    """
    Convert a Ticket SQLAlchemy object into a JSON-friendly dictionary.
    """

    if ticket is None:
        return None

    return {
        "id": str(ticket.id) if ticket.id is not None else None,
        "tenant_id": (
            str(ticket.tenant_id)
            if ticket.tenant_id is not None
            else None
        ),
        "ticket_number": ticket.ticket_number,
        "user_id": (
            str(ticket.user_id)
            if ticket.user_id is not None
            else None
        ),
        "customer_phone": ticket.customer_phone,
        "subject": ticket.subject,
        "description": ticket.description,
        "category": ticket.category,
        "priority": ticket.priority,
        "status": ticket.status,
        "assigned_to": ticket.assigned_to,
        "created_at": (
            ticket.created_at.isoformat()
            if ticket.created_at is not None
            else None
        ),
        "updated_at": (
            ticket.updated_at.isoformat()
            if ticket.updated_at is not None
            else None
        ),
        "resolved_at": (
            ticket.resolved_at.isoformat()
            if ticket.resolved_at is not None
            else None
        ),
    }


# ============================================================================
# DUPLICATE DETECTION
# ============================================================================


def find_existing_open_ticket(
    db: Session,
    customer_phone: str,
    category: str = "general",
    tenant_id=None,
) -> Optional[Ticket]:
    """
    Find an existing unresolved ticket.

    IMPORTANT:
    The search is ALWAYS restricted to the supplied tenant_id.

    This prevents:
        Tenant A customer -> seeing Tenant B ticket

    and prevents duplicate tickets for the same customer/category
    inside the same tenant.
    """

    phone = normalize_customer_phone(customer_phone)

    if not phone:
        return None

    if not _validate_tenant_id(tenant_id):
        logger.warning(
            "XYTRALYN TICKET | duplicate search rejected | "
            "missing tenant_id"
        )
        return None

    category = _safe_category(category)

    return (
        db.query(Ticket)
        .filter(
            Ticket.tenant_id == tenant_id,
            Ticket.customer_phone == phone,
            Ticket.category == category,
            Ticket.status.in_(list(OPEN_STATUSES)),
        )
        .order_by(Ticket.created_at.desc())
        .first()
    )


# ============================================================================
# CREATE TICKET
# ============================================================================


def create_ticket(
    db: Session,
    customer_phone: str,
    subject: str,
    description: str,
    category: str = "general",
    priority: str = "medium",
    user_id=None,
    tenant_id=None,
    assigned_to: Optional[str] = None,
    prevent_duplicate: bool = True,
) -> Dict[str, Any]:
    """
    Create a support ticket.

    Tenant isolation is mandatory.

    Returns:
        {
            "success": bool,
            "created": bool,
            "duplicate": bool,
            "ticket": dict | None,
            "error": str | None
        }
    """

    # ------------------------------------------------------------------
    # Tenant validation
    # ------------------------------------------------------------------

    if not _validate_tenant_id(tenant_id):
        logger.error(
            "XYTRALYN TICKET | create rejected | missing tenant_id"
        )

        return {
            "success": False,
            "created": False,
            "duplicate": False,
            "ticket": None,
            "error": "Tenant ID is required.",
        }

    # ------------------------------------------------------------------
    # Phone validation
    # ------------------------------------------------------------------

    phone = normalize_customer_phone(customer_phone)

    if not phone:
        return {
            "success": False,
            "created": False,
            "duplicate": False,
            "ticket": None,
            "error": "Invalid customer phone number.",
        }

    # ------------------------------------------------------------------
    # Normalize values
    # ------------------------------------------------------------------

    subject = _clean_text(subject)
    description = _clean_text(description)
    category = _safe_category(category)
    priority = _safe_priority(priority)

    if not subject:
        subject = f"{category.title()} Support Request"

    if not description:
        description = subject

    # ------------------------------------------------------------------
    # Duplicate prevention
    # ------------------------------------------------------------------

    if prevent_duplicate:
        existing = find_existing_open_ticket(
            db=db,
            customer_phone=phone,
            category=category,
            tenant_id=tenant_id,
        )

        if existing is not None:
            logger.info(
                "XYTRALYN TICKET | duplicate prevented | "
                "tenant=%s ticket=%s phone=%s category=%s",
                tenant_id,
                existing.ticket_number,
                phone,
                category,
            )

            return {
                "success": True,
                "created": False,
                "duplicate": True,
                "ticket": ticket_to_dict(existing),
                "error": None,
            }

    # ------------------------------------------------------------------
    # Create ticket object
    # ------------------------------------------------------------------

    ticket = Ticket(
        tenant_id=tenant_id,
        user_id=user_id,
        customer_phone=phone,
        ticket_number=_generate_ticket_number(),
        subject=subject,
        description=description,
        category=category,
        priority=priority,
        status="open",
        assigned_to=_clean_text(assigned_to) or None,
    )

    db.add(ticket)

    # ------------------------------------------------------------------
    # Commit
    # ------------------------------------------------------------------

    try:
        db.commit()
        db.refresh(ticket)

    except IntegrityError:
        db.rollback()

        logger.warning(
            "XYTRALYN TICKET | integrity error | "
            "tenant=%s ticket=%s",
            tenant_id,
            ticket.ticket_number,
        )

        # Retry with a fresh ticket number.
        ticket.ticket_number = _generate_ticket_number()

        db.add(ticket)

        try:
            db.commit()
            db.refresh(ticket)

        except Exception as retry_error:
            db.rollback()

            logger.exception(
                "XYTRALYN TICKET | create failed after retry"
            )

            return {
                "success": False,
                "created": False,
                "duplicate": False,
                "ticket": None,
                "error": str(retry_error),
            }

    except Exception as exc:
        db.rollback()

        logger.exception(
            "XYTRALYN TICKET | database create failed | "
            "tenant=%s",
            tenant_id,
        )

        return {
            "success": False,
            "created": False,
            "duplicate": False,
            "ticket": None,
            "error": str(exc),
        }

    # ------------------------------------------------------------------
    # Success
    # ------------------------------------------------------------------

    logger.info(
        "XYTRALYN TICKET | created | "
        "tenant=%s ticket=%s phone=%s category=%s priority=%s",
        tenant_id,
        ticket.ticket_number,
        phone,
        category,
        priority,
    )

    return {
        "success": True,
        "created": True,
        "duplicate": False,
        "ticket": ticket_to_dict(ticket),
        "error": None,
    }


# ============================================================================
# GET SINGLE TICKET
# ============================================================================


def get_ticket(
    db: Session,
    ticket_number: str,
    tenant_id=None,
) -> Optional[Ticket]:
    """
    Fetch one ticket by ticket number.

    IMPORTANT:
    tenant_id is mandatory for safe lookup.
    """

    number = _clean_text(ticket_number)

    if not number:
        return None

    if not _validate_tenant_id(tenant_id):
        logger.warning(
            "XYTRALYN TICKET | get rejected | missing tenant_id"
        )
        return None

    return (
        db.query(Ticket)
        .filter(
            Ticket.ticket_number == number,
            Ticket.tenant_id == tenant_id,
        )
        .first()
    )


# ============================================================================
# GET CUSTOMER TICKETS
# ============================================================================


def get_customer_tickets(
    db: Session,
    customer_phone: str,
    tenant_id=None,
    include_closed: bool = True,
) -> List[Ticket]:
    """
    Return tickets belonging only to the supplied customer
    and supplied tenant.
    """

    phone = normalize_customer_phone(customer_phone)

    if not phone:
        return []

    if not _validate_tenant_id(tenant_id):
        logger.warning(
            "XYTRALYN TICKET | customer tickets rejected | "
            "missing tenant_id"
        )
        return []

    query = (
        db.query(Ticket)
        .filter(
            Ticket.tenant_id == tenant_id,
            Ticket.customer_phone == phone,
        )
        .order_by(Ticket.created_at.desc())
    )

    if not include_closed:
        query = query.filter(
            Ticket.status.in_(list(OPEN_STATUSES))
        )

    return query.all()


# ============================================================================
# GET ALL TENANT TICKETS
# ============================================================================


def get_tenant_tickets(
    db: Session,
    tenant_id=None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 100,
) -> List[Ticket]:
    """
    Fetch tickets belonging to one tenant.

    This function is intended for admin/dashboard/service usage.
    """

    if not _validate_tenant_id(tenant_id):
        logger.warning(
            "XYTRALYN TICKET | tenant ticket listing rejected | "
            "missing tenant_id"
        )
        return []

    # Protect against unreasonable limits.
    limit = max(1, min(int(limit), 500))

    query = (
        db.query(Ticket)
        .filter(Ticket.tenant_id == tenant_id)
        .order_by(Ticket.created_at.desc())
    )

    if status:
        query = query.filter(
            Ticket.status == _safe_status(status)
        )

    if priority:
        query = query.filter(
            Ticket.priority == _safe_priority(priority)
        )

    if category:
        query = query.filter(
            Ticket.category == _safe_category(category)
        )

    return query.limit(limit).all()


# ============================================================================
# UPDATE TICKET STATUS
# ============================================================================


def update_ticket_status(
    db: Session,
    ticket_number: str,
    status: str,
    tenant_id=None,
) -> Dict[str, Any]:
    """
    Update a ticket status.

    When status becomes resolved/closed,
    resolved_at is populated.
    """

    ticket = get_ticket(
        db=db,
        ticket_number=ticket_number,
        tenant_id=tenant_id,
    )

    if ticket is None:
        return {
            "success": False,
            "ticket": None,
            "error": "Ticket not found.",
        }

    new_status = _safe_status(status)

    ticket.status = new_status

    if new_status in CLOSED_STATUSES:
        ticket.resolved_at = datetime.utcnow()
    else:
        ticket.resolved_at = None

    ticket.updated_at = datetime.utcnow()

    try:
        db.commit()
        db.refresh(ticket)

    except Exception as exc:
        db.rollback()

        logger.exception(
            "XYTRALYN TICKET | status update failed | "
            "tenant=%s ticket=%s",
            tenant_id,
            ticket_number,
        )

        return {
            "success": False,
            "ticket": None,
            "error": str(exc),
        }

    logger.info(
        "XYTRALYN TICKET | status updated | "
        "tenant=%s ticket=%s status=%s",
        tenant_id,
        ticket.ticket_number,
        new_status,
    )

    return {
        "success": True,
        "ticket": ticket_to_dict(ticket),
        "error": None,
    }


# ============================================================================
# UPDATE TICKET PRIORITY
# ============================================================================


def update_ticket_priority(
    db: Session,
    ticket_number: str,
    priority: str,
    tenant_id=None,
) -> Dict[str, Any]:
    """
    Update a ticket priority.
    """

    ticket = get_ticket(
        db=db,
        ticket_number=ticket_number,
        tenant_id=tenant_id,
    )

    if ticket is None:
        return {
            "success": False,
            "ticket": None,
            "error": "Ticket not found.",
        }

    ticket.priority = _safe_priority(priority)
    ticket.updated_at = datetime.utcnow()

    try:
        db.commit()
        db.refresh(ticket)

    except Exception as exc:
        db.rollback()

        logger.exception(
            "XYTRALYN TICKET | priority update failed | "
            "tenant=%s ticket=%s",
            tenant_id,
            ticket_number,
        )

        return {
            "success": False,
            "ticket": None,
            "error": str(exc),
        }

    logger.info(
        "XYTRALYN TICKET | priority updated | "
        "tenant=%s ticket=%s priority=%s",
        tenant_id,
        ticket.ticket_number,
        ticket.priority,
    )

    return {
        "success": True,
        "ticket": ticket_to_dict(ticket),
        "error": None,
    }


# ============================================================================
# ASSIGN TICKET
# ============================================================================


def assign_ticket(
    db: Session,
    ticket_number: str,
    assigned_to: Optional[str],
    tenant_id=None,
) -> Dict[str, Any]:
    """
    Assign or unassign a ticket.

    Tenant isolation is enforced through get_ticket().
    """

    ticket = get_ticket(
        db=db,
        ticket_number=ticket_number,
        tenant_id=tenant_id,
    )

    if ticket is None:
        return {
            "success": False,
            "ticket": None,
            "error": "Ticket not found.",
        }

    ticket.assigned_to = _clean_text(assigned_to) or None
    ticket.updated_at = datetime.utcnow()

    try:
        db.commit()
        db.refresh(ticket)

    except Exception as exc:
        db.rollback()

        logger.exception(
            "XYTRALYN TICKET | assignment update failed | "
            "tenant=%s ticket=%s",
            tenant_id,
            ticket_number,
        )

        return {
            "success": False,
            "ticket": None,
            "error": str(exc),
        }

    logger.info(
        "XYTRALYN TICKET | assignment updated | "
        "tenant=%s ticket=%s assigned_to=%s",
        tenant_id,
        ticket.ticket_number,
        ticket.assigned_to,
    )

    return {
        "success": True,
        "ticket": ticket_to_dict(ticket),
        "error": None,
    }


# ============================================================================
# CLOSE TICKET
# ============================================================================


def close_ticket(
    db: Session,
    ticket_number: str,
    tenant_id=None,
) -> Dict[str, Any]:
    """
    Convenience function to close a ticket.
    """

    return update_ticket_status(
        db=db,
        ticket_number=ticket_number,
        status="closed",
        tenant_id=tenant_id,
    )


# ============================================================================
# RESOLVE TICKET
# ============================================================================


def resolve_ticket(
    db: Session,
    ticket_number: str,
    tenant_id=None,
) -> Dict[str, Any]:
    """
    Convenience function to resolve a ticket.
    """

    return update_ticket_status(
        db=db,
        ticket_number=ticket_number,
        status="resolved",
        tenant_id=tenant_id,
    )


# ============================================================================
# REOPEN TICKET
# ============================================================================


def reopen_ticket(
    db: Session,
    ticket_number: str,
    tenant_id=None,
) -> Dict[str, Any]:
    """
    Convenience function to reopen a ticket.
    """

    return update_ticket_status(
        db=db,
        ticket_number=ticket_number,
        status="open",
        tenant_id=tenant_id,
    )


# ============================================================================
# TICKET COUNTS
# ============================================================================


def count_tenant_tickets(
    db: Session,
    tenant_id=None,
) -> Dict[str, int]:
    """
    Return ticket counts for one tenant.

    Example:
        {
            "total": 10,
            "open": 4,
            "in_progress": 2,
            "resolved": 3,
            "closed": 1
        }
    """

    if not _validate_tenant_id(tenant_id):
        return {
            "total": 0,
            "open": 0,
            "in_progress": 0,
            "resolved": 0,
            "closed": 0,
        }

    tickets = (
        db.query(Ticket)
        .filter(Ticket.tenant_id == tenant_id)
        .all()
    )

    result = {
        "total": len(tickets),
        "open": 0,
        "in_progress": 0,
        "resolved": 0,
        "closed": 0,
    }

    for ticket in tickets:
        status = _safe_status(ticket.status)

        if status in result:
            result[status] += 1

    return result


# ============================================================================
# PUBLIC API
# ============================================================================


__all__ = [
    "VALID_CATEGORIES",
    "VALID_PRIORITIES",
    "VALID_STATUSES",
    "OPEN_STATUSES",
    "CLOSED_STATUSES",
    "normalize_customer_phone",
    "ticket_to_dict",
    "find_existing_open_ticket",
    "create_ticket",
    "get_ticket",
    "get_customer_tickets",
    "get_tenant_tickets",
    "update_ticket_status",
    "update_ticket_priority",
    "assign_ticket",
    "close_ticket",
    "resolve_ticket",
    "reopen_ticket",
    "count_tenant_tickets",
]