"""
Xytralyn Ticket Service
-----------------------
Step 3 of the Support Agent integration.

Responsibilities:
- Create support tickets in the existing SQLAlchemy database.
- Generate unique human-readable ticket numbers.
- Avoid unnecessary duplicate open tickets for the same customer/category.
- Update ticket status and priority.
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
from typing import Any, Dict, Optional

from sqlalchemy.exc import IntegrityError

from app.models import Ticket

logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# Basic helpers
# ---------------------------------------------------------------------------

def _clean_text(value: Any) -> str:
    if value is None:
        return ""

    return re.sub(r"\s+", " ", str(value).strip())


def normalize_customer_phone(phone: Any) -> Optional[str]:
    """
    Normalize an Indian WhatsApp phone number to the same 10-digit format
    already used by the Xytralyn lead/customer flow.

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
    value = _clean_text(category).lower()

    if value in VALID_CATEGORIES:
        return value

    return "general"


def _safe_priority(priority: Any) -> str:
    value = _clean_text(priority).lower()

    if value in VALID_PRIORITIES:
        return value

    return "medium"


def _safe_status(status: Any) -> str:
    value = _clean_text(status).lower()

    if value in VALID_STATUSES:
        return value

    return "open"


def _generate_ticket_number() -> str:
    """
    Generate a readable ticket identifier.

    UUID suffix makes collisions extremely unlikely while the date keeps
    tickets easy for admins to recognize.
    """
    date_part = datetime.utcnow().strftime("%Y%m%d")
    random_part = uuid.uuid4().hex[:8].upper()

    return f"XYT-{date_part}-{random_part}"


# ---------------------------------------------------------------------------
# Ticket serialization
# ---------------------------------------------------------------------------

def ticket_to_dict(ticket: Optional[Ticket]) -> Optional[Dict[str, Any]]:
    """Convert a Ticket SQLAlchemy object into a JSON-friendly dictionary."""
    if ticket is None:
        return None

    return {
        "id": str(ticket.id) if ticket.id is not None else None,
        "ticket_number": ticket.ticket_number,
        "user_id": str(ticket.user_id) if ticket.user_id is not None else None,
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


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

def find_existing_open_ticket(
    db,
    customer_phone: str,
    category: str = "general",
) -> Optional[Ticket]:
    """
    Find an existing unresolved ticket for this customer/category.

    This prevents a customer sending several messages about the same
    unresolved issue from creating a new ticket every time.
    """
    phone = normalize_customer_phone(customer_phone)

    if not phone:
        return None

    category = _safe_category(category)

    return (
        db.query(Ticket)
        .filter(
            Ticket.customer_phone == phone,
            Ticket.category == category,
            Ticket.status.in_(["open", "in_progress"]),
        )
        .order_by(Ticket.created_at.desc())
        .first()
    )


# ---------------------------------------------------------------------------
# Create ticket
# ---------------------------------------------------------------------------

def create_ticket(
    db,
    customer_phone: str,
    subject: str,
    description: str,
    category: str = "general",
    priority: str = "medium",
    user_id=None,
    assigned_to: Optional[str] = None,
    prevent_duplicate: bool = True,
) -> Dict[str, Any]:
    """
    Create a support ticket.

    Returns:
        {
            "success": bool,
            "created": bool,
            "duplicate": bool,
            "ticket": {...} | None,
            "error": str | None,
        }

    If an unresolved ticket already exists for the same customer/category,
    that ticket is returned instead of creating another one when
    prevent_duplicate=True.
    """
    phone = normalize_customer_phone(customer_phone)

    if not phone:
        return {
            "success": False,
            "created": False,
            "duplicate": False,
            "ticket": None,
            "error": "Invalid customer phone number.",
        }

    subject = _clean_text(subject)
    description = _clean_text(description)
    category = _safe_category(category)
    priority = _safe_priority(priority)

    if not subject:
        subject = f"{category.title()} Support Request"

    if not description:
        description = subject

    if prevent_duplicate:
        existing = find_existing_open_ticket(
            db=db,
            customer_phone=phone,
            category=category,
        )

        if existing is not None:
            logger.info(
                "XYTRALYN TICKET | duplicate prevented | "
                "ticket=%s phone=%s category=%s",
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

    ticket = Ticket(
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

    try:
        db.commit()
        db.refresh(ticket)

    except IntegrityError:
        db.rollback()

        # A ticket-number collision is extraordinarily unlikely, but a retry
        # keeps the service safe if it ever happens.
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
            "XYTRALYN TICKET | database create failed"
        )

        return {
            "success": False,
            "created": False,
            "duplicate": False,
            "ticket": None,
            "error": str(exc),
        }

    logger.info(
        "XYTRALYN TICKET | created | ticket=%s phone=%s category=%s priority=%s",
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


# ---------------------------------------------------------------------------
# Fetch tickets
# ---------------------------------------------------------------------------

def get_ticket(
    db,
    ticket_number: str,
) -> Optional[Ticket]:
    """Fetch one ticket by its public ticket number."""
    number = _clean_text(ticket_number)

    if not number:
        return None

    return (
        db.query(Ticket)
        .filter(Ticket.ticket_number == number)
        .first()
    )


def get_customer_tickets(
    db,
    customer_phone: str,
    include_closed: bool = True,
):
    """Return tickets belonging only to the supplied customer phone."""
    phone = normalize_customer_phone(customer_phone)

    if not phone:
        return []

    query = (
        db.query(Ticket)
        .filter(Ticket.customer_phone == phone)
        .order_by(Ticket.created_at.desc())
    )

    if not include_closed:
        query = query.filter(
            Ticket.status.in_(["open", "in_progress"])
        )

    return query.all()


# ---------------------------------------------------------------------------
# Update ticket
# ---------------------------------------------------------------------------

def update_ticket_status(
    db,
    ticket_number: str,
    status: str,
) -> Dict[str, Any]:
    """
    Update a ticket status.

    When status becomes resolved/closed, resolved_at is populated.
    """
    ticket = get_ticket(db, ticket_number)

    if ticket is None:
        return {
            "success": False,
            "ticket": None,
            "error": "Ticket not found.",
        }

    new_status = _safe_status(status)

    ticket.status = new_status

    if new_status in {"resolved", "closed"}:
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
            "XYTRALYN TICKET | status update failed | ticket=%s",
            ticket_number,
        )

        return {
            "success": False,
            "ticket": None,
            "error": str(exc),
        }

    logger.info(
        "XYTRALYN TICKET | status updated | ticket=%s status=%s",
        ticket.ticket_number,
        new_status,
    )

    return {
        "success": True,
        "ticket": ticket_to_dict(ticket),
        "error": None,
    }


def update_ticket_priority(
    db,
    ticket_number: str,
    priority: str,
) -> Dict[str, Any]:
    """Update a ticket priority."""
    ticket = get_ticket(db, ticket_number)

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
            "XYTRALYN TICKET | priority update failed | ticket=%s",
            ticket_number,
        )

        return {
            "success": False,
            "ticket": None,
            "error": str(exc),
        }

    return {
        "success": True,
        "ticket": ticket_to_dict(ticket),
        "error": None,
    }


def assign_ticket(
    db,
    ticket_number: str,
    assigned_to: Optional[str],
) -> Dict[str, Any]:
    """Assign or unassign a ticket."""
    ticket = get_ticket(db, ticket_number)

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
            "XYTRALYN TICKET | assignment update failed | ticket=%s",
            ticket_number,
        )

        return {
            "success": False,
            "ticket": None,
            "error": str(exc),
        }

    return {
        "success": True,
        "ticket": ticket_to_dict(ticket),
        "error": None,
    }


__all__ = [
    "VALID_CATEGORIES",
    "VALID_PRIORITIES",
    "VALID_STATUSES",
    "normalize_customer_phone",
    "ticket_to_dict",
    "find_existing_open_ticket",
    "create_ticket",
    "get_ticket",
    "get_customer_tickets",
    "update_ticket_status",
    "update_ticket_priority",
    "assign_ticket",
]
