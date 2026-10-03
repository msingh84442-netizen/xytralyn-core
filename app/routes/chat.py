# XYTRALYN CHAT ROUTE

# META WHATSAPP CLOUD API

# PART 1/2

# ============================================================

import os

import re

import logging

import asyncio

from typing import Optional, Dict, Any, List

import httpx

from dotenv import load_dotenv

from fastapi import APIRouter, Request, HTTPException

from fastapi.responses import PlainTextResponse

from app.database import SessionLocal

from app.models import Lead, Message, Tenant, WhatsAppAccount

from app.services.tenant_service import get_whatsapp_account

from app.services.support_agent import (
    generate_support_reply,
)

from app.services.ticket_service import (
    create_ticket,
)

from app.services.ai_agent import (
    detect_agent,
    extract_lead_info,
    generate_agent_reply,
    normalize_history,
    memory_to_text,
    is_valid_customer_name,
    is_valid_memory_value,
)

load_dotenv(override=True)

logger = logging.getLogger(__name__)

router = APIRouter()

# ============================================================

# BUSINESS CONFIG

# ============================================================

BUSINESS_NAME = "Xytralyn"

HISTORY_LIMIT = 20

# ============================================================

# META WHATSAPP CONFIG

# ============================================================

WHATSAPP_TOKEN = (os.getenv("WHATSAPP_TOKEN") or "").strip()

WHATSAPP_PHONE_NUMBER_ID = (os.getenv("WHATSAPP_PHONE_NUMBER_ID") or "").strip()

WHATSAPP_VERIFY_TOKEN = (os.getenv("WHATSAPP_VERIFY_TOKEN") or "").strip()

META_GRAPH_VERSION = (
    os.getenv("META_GRAPH_VERSION") or "v26.0"
).strip()

ADMIN_WHATSAPP_NUMBER = (
    os.getenv("ADMIN_WHATSAPP_NUMBER") or ""
).strip()

DEBUG_ROUTES_ENABLED = (
    (os.getenv("DEBUG_ROUTES_ENABLED") or "false").strip().lower()
    in {"1", "true", "yes", "on"}
)

# ============================================================

# GREEN-API ADMIN CONFIG

# ============================================================

GREEN_API_INSTANCE_ID = (
    os.getenv("GREEN_API_INSTANCE_ID") or ""
).strip()

GREEN_API_TOKEN = (
    os.getenv("GREEN_API_TOKEN") or ""
).strip()

GREEN_API_BASE_URL = (
    os.getenv("GREEN_API_BASE_URL")
    or "https://7107.api.greenapi.com"
).strip().rstrip("/")

# ============================================================

# TENANT / WHATSAPP HELPERS

# ============================================================


def resolve_whatsapp_context(db, phone_number_id: str):
    """Resolve an incoming Meta phone_number_id to an active WhatsApp account and tenant."""
    phone_number_id = str(phone_number_id or "").strip()
    if not phone_number_id:
        return None, None
    account = get_whatsapp_account(db, phone_number_id)
    if not account or str(getattr(account, "status", "active")).lower() != "active":
        return None, None
    tenant = (
        db.query(Tenant)
        .filter(Tenant.id == account.tenant_id, Tenant.status == "active")
        .first()
    )
    if not tenant:
        return account, None
    return account, tenant


def tenant_value(tenant, field: str, fallback: str = "") -> str:
    value = getattr(tenant, field, None) if tenant is not None else None
    return str(value).strip() if value is not None else fallback
# ============================================================

# CUSTOMER MEMORY

# ============================================================

# ============================================================

# PHONE NORMALIZATION

# ============================================================


def normalize_customer_phone(
    phone: str,
) -> str:
    if not phone:
        return ""
    digits = re.sub(
        r"\D",
        "",
        str(phone),
    )
    if (
        len(digits) == 10
        and digits[0] in "6789"
    ):
        digits = "91" + digits
    return digits


def sanitize_customer_memory_data(
    data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Keep only confirmed, non-placeholder customer data."""
    if not isinstance(data, dict):
        return {}
    cleaned = {}
    for field, value in data.items():
        if not is_valid_memory_value(value):
            continue
        if field == "name" and not is_valid_customer_name(value):
            continue
        cleaned[field] = value
    return cleaned
# ============================================================

# CUSTOMER MEMORY

# ============================================================


def get_customer_memory(
    phone: str,
    tenant_id=None,
) -> Dict[str, Any]:
    phone = normalize_customer_phone(phone)
    if not phone or tenant_id is None:
        return {}
    db = SessionLocal()
    try:
        lead = (
            db.query(Lead)
            .filter(Lead.tenant_id == tenant_id, Lead.phone == phone)
            .first()
        )
        if not lead:
            return {}
        fields = [
            "name", "email", "company", "business_type", "lead_volume",
            "interested_agent", "demo_date", "demo_time", "demo_datetime",
            "demo_status",
        ]
        raw_memory = {}
        changed = False
        for field in fields:
            value = getattr(lead, field, None)
            if not is_valid_memory_value(value):
                if value not in (None, "") and field != "demo_status":
                    try:
                        setattr(lead, field, None); changed = True
                    except Exception:
                        pass
                continue
            if field == "name" and not is_valid_customer_name(value):
                try:
                    lead.name = None; changed = True
                except Exception:
                    pass
                continue
            raw_memory[field] = value
        if changed:
            db.commit(); db.refresh(lead)
        return sanitize_customer_memory_data(raw_memory)
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to load customer memory | tenant=%s | phone=%s | error=%s", tenant_id, phone, exc)
        return {}
    finally:
        db.close()


def update_customer_memory(
    phone: str,
    new_data: Optional[Dict[str, Any]],
    tenant_id=None,
) -> Dict[str, Any]:
    phone = normalize_customer_phone(phone)
    if not phone or tenant_id is None:
        return {}
    new_data = sanitize_customer_memory_data(new_data or {})
    db = SessionLocal()
    try:
        lead = (
            db.query(Lead)
            .filter(Lead.tenant_id == tenant_id, Lead.phone == phone)
            .first()
        )
        if not lead:
            lead = Lead(tenant_id=tenant_id, phone=phone, status="new", demo_status="not_scheduled")
            db.add(lead); db.flush()
        fields = [
            "name", "email", "company", "business_type", "lead_volume",
            "interested_agent", "demo_date", "demo_time", "demo_datetime",
        ]
        for field in fields:
            value = new_data.get(field)
            if not is_valid_memory_value(value):
                continue
            if field == "name" and not is_valid_customer_name(value):
                continue
            setattr(lead, field, value)
        if new_data.get("demo_date") or new_data.get("demo_time") or new_data.get("demo_datetime"):
            lead.demo_status = "preferred_slot"
        if not is_valid_customer_name(getattr(lead, "name", None)):
            lead.name = None
        if not is_valid_memory_value(getattr(lead, "company", None)):
            lead.company = None
        db.commit(); db.refresh(lead)
        return get_customer_memory(phone, tenant_id)
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to save customer memory | tenant=%s | phone=%s | error=%s", tenant_id, phone, exc)
        return {}
    finally:
        db.close()
# ============================================================

# CHAT HISTORY

# ============================================================


def build_chat_history(
    db,
    sender_phone: str,
    limit: int = HISTORY_LIMIT,
    tenant_id=None,
) -> List[Dict[str, str]]:
    sender_phone = normalize_customer_phone(
        sender_phone
    )
    if not sender_phone:
        return []
    messages = (
        db.query(Message)
        .filter(
            Message.tenant_id == tenant_id,
            Message.sender_phone == sender_phone,
        )
        .order_by(
            Message.timestamp.desc()
        )
        .limit(limit)
        .all()
    )
    messages.reverse()
    history = []
    for message in messages:
        content = getattr(
            message,
            "content",
            None,
        )
        if not content:
            continue
        sender_type = getattr(
            message,
            "sender_type",
            None,
        )
        if sender_type == "assistant":
            role = "assistant"
        else:
            role = "user"
        history.append(
            {
                "role": role,
                "content": str(content).strip(),
            }
        )
    return normalize_history(history)
# ============================================================

# CUSTOMER MEMORY PROCESSING

# ============================================================


def process_customer_memory(
    sender_phone: str,
    user_message: str,
    history: Optional[List[Dict[str, str]]] = None,
    tenant_id=None,
) -> Dict[str, Any]:
    sender_phone = normalize_customer_phone(
        sender_phone
    )
    if not sender_phone:
        return {}
    if not user_message:
        return get_customer_memory(
            sender_phone, tenant_id
        )
    new_data = extract_lead_info(
        user_message,
        history=history or [],
    )
    return update_customer_memory(
        sender_phone,
        new_data,
        tenant_id=tenant_id,
    )
# ============================================================

# CUSTOMER CONTEXT

# ============================================================


def get_customer_context(
    sender_phone: str,
    tenant_id=None,
) -> str:
    memory = get_customer_memory(
        sender_phone, tenant_id
    )
    return memory_to_text(memory)
# ============================================================

# LEAD DATABASE

# ============================================================


def update_or_create_lead(
    db,
    sender_phone: str,
    lead_data: Optional[Dict[str, Any]],
    tenant_id=None,
) -> Optional[Lead]:
    sender_phone = normalize_customer_phone(sender_phone)
    if not sender_phone or tenant_id is None:
        return None
    lead_data = sanitize_customer_memory_data(lead_data or {})
    # The phone number itself identifies the customer. Therefore a Lead row
    # must still exist even when this particular message contains no
    # extractable field.
    lead = (
        db.query(Lead)
        .filter(Lead.tenant_id == tenant_id, Lead.phone == sender_phone)
        .first()
    )
    if not lead:
        lead = Lead(
            tenant_id=tenant_id,
            phone=sender_phone,
            name=lead_data.get("name"),
            email=lead_data.get("email"),
            company=lead_data.get("company"),
            business_type=lead_data.get("business_type"),
            lead_volume=lead_data.get("lead_volume"),
            interested_agent=lead_data.get("interested_agent"),
            demo_date=lead_data.get("demo_date"),
            demo_time=lead_data.get("demo_time"),
            demo_datetime=lead_data.get("demo_datetime"),
            demo_status=(
                "preferred_slot"
                if (
                    lead_data.get("demo_date")
                    or lead_data.get("demo_time")
                    or lead_data.get("demo_datetime")
                )
                else "not_scheduled"
            ),
            status="new",
        )
        db.add(lead)
    else:
        for field in [
            "name",
            "email",
            "company",
            "business_type",
            "lead_volume",
            "interested_agent",
            "demo_date",
            "demo_time",
            "demo_datetime",
        ]:
            value = lead_data.get(field)
            if not is_valid_memory_value(value):
                continue
            if field == "name" and not is_valid_customer_name(value):
                continue
            setattr(lead, field, value)
        if (
            lead_data.get("demo_date")
            or lead_data.get("demo_time")
            or lead_data.get("demo_datetime")
        ):
            lead.demo_status = "preferred_slot"
        if not is_valid_customer_name(getattr(lead, "name", None)):
            lead.name = None
        if not is_valid_memory_value(getattr(lead, "company", None)):
            lead.company = None
    db.commit()
    db.refresh(lead)
    logger.info(
        "XYTRALYN DB | lead upserted | phone=%s | lead_id=%s | "
        "name=%s | company=%s | business_type=%s | lead_volume=%s | "
        "interested_agent=%s | demo=%s %s",
        sender_phone,
        getattr(lead, "id", None),
        getattr(lead, "name", None) or "Not provided",
        getattr(lead, "company", None) or "Not provided",
        getattr(lead, "business_type", None) or "Not provided",
        getattr(lead, "lead_volume", None) or "Not provided",
        getattr(lead, "interested_agent", None) or "Not specified",
        getattr(lead, "demo_date", None) or "",
        getattr(lead, "demo_time", None) or "",
    )
    return lead
# ============================================================

# MESSAGE DATABASE

# ============================================================


def save_message(
    db,
    sender_phone: str,
    content: str,
    agent_name: Optional[str] = None,
    sender_type: str = "user",
    tenant_id=None,
):
    sender_phone = normalize_customer_phone(
        sender_phone
    )
    if not sender_phone or tenant_id is None:
        return None
    if not content:
        return None
    message = Message(
        tenant_id=tenant_id,
        sender_phone=sender_phone,
        content=content,
        agent_used=agent_name,
    )
    if hasattr(message, "sender_type"):
        message.sender_type = sender_type
    db.add(message)
    db.commit()
    db.refresh(message)
    logger.info(
        "XYTRALYN DB | message saved | phone=%s | sender_type=%s | "
        "message_id=%s",
        sender_phone,
        sender_type,
        getattr(message, "id", None),
    )
    return message
# ============================================================

# META SEND MESSAGE

# ============================================================


async def send_whatsapp_message(
    recipient_phone: str,
    message_text: str,
    tenant_id=None,
    phone_number_id=None,
) -> bool:
    phone_digits = normalize_customer_phone(recipient_phone)
    requested_phone_number_id = str(phone_number_id or "").strip()
    if not phone_digits or not message_text or tenant_id is None:
        logger.error(
            "WhatsApp send rejected | tenant=%s | phone=%s",
            tenant_id,
            recipient_phone,
        )
        return False
    db = SessionLocal()
    try:
        account_query = db.query(WhatsAppAccount).filter(
            WhatsAppAccount.tenant_id == tenant_id,
            WhatsAppAccount.status == "active",
        )
        if requested_phone_number_id:
            account_query = account_query.filter(
                WhatsAppAccount.phone_number_id == requested_phone_number_id
            )
        account = account_query.first()
        if not account:
            logger.error(
                "No active WhatsApp account for tenant=%s | phone_number_id=%s",
                tenant_id,
                requested_phone_number_id or "not supplied",
            )
            return False
        access_token = str(account.access_token or "").strip()
        resolved_phone_number_id = str(account.phone_number_id or "").strip()
        if not access_token or not resolved_phone_number_id:
            logger.error(
                "Incomplete WhatsApp credentials | tenant=%s",
                tenant_id,
            )
            return False
        url = (
            f"https://graph.facebook.com/"
            f"{META_GRAPH_VERSION}/{resolved_phone_number_id}/messages"
        )
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone_digits,
            "type": "text",
            "text": {"preview_url": False, "body": message_text},
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers=headers,
                json=payload,
            )
        if response.is_success:
            logger.info(
                "META WhatsApp send accepted | tenant=%s | status=%s",
                tenant_id,
                response.status_code,
            )
            return True
        if response.status_code == 401:
            logger.error(
                "META WhatsApp authentication failed | tenant=%s | "
                "phone_number_id=%s | check WhatsAppAccount.access_token",
                tenant_id,
                resolved_phone_number_id,
            )
        logger.error(
            "META WhatsApp send failed | tenant=%s | status=%s | response=%s",
            tenant_id,
            response.status_code,
            response.text,
        )
        return False
    except Exception as exc:
        logger.exception(
            "META WhatsApp send exception | tenant=%s | error=%s",
            tenant_id,
            exc,
        )
        return False
    finally:
        db.close()
# ============================================================

# GREEN-API ADMIN MESSAGE SENDER

# ============================================================


async def send_admin_whatsapp_message(
    message_text: str,
    admin_whatsapp_number: Optional[str] = None,
) -> bool:
    if not GREEN_API_INSTANCE_ID:
        logger.error(
            "GREEN_API_INSTANCE_ID is missing."
        )
        return False
    if not GREEN_API_TOKEN:
        logger.error(
            "GREEN_API_TOKEN is missing."
        )
        return False
    admin_number = str(admin_whatsapp_number or ADMIN_WHATSAPP_NUMBER or "").strip()
    if not admin_number:
        logger.error("Admin WhatsApp number is missing.")
        return False
    if not message_text:
        logger.error(
            "Admin message is empty."
        )
        return False
    admin_phone = normalize_customer_phone(
        admin_number
    )
    if not admin_phone:
        logger.error(
            "Invalid admin WhatsApp number."
        )
        return False
    chat_id = f"{admin_phone}@c.us"
    url = (
        f"{GREEN_API_BASE_URL}/"
        f"waInstance{GREEN_API_INSTANCE_ID}/"
        f"sendMessage/{GREEN_API_TOKEN}"
    )
    payload = {
        "chatId": chat_id,
        "message": message_text,
    }
    headers = {
        "Content-Type": "application/json"
    }
    try:
        async with httpx.AsyncClient(
            timeout=30.0
        ) as client:
            response = await client.post(
                url,
                headers=headers,
                json=payload,
            )
        if response.is_success:
            try:
                data = response.json()
            except Exception:
                data = {}
            logger.info(
                "GREEN-API ADMIN MESSAGE SENT | "
                "admin=%s | response=%s",
                chat_id,
                data,
            )
            return True
        logger.error(
            "GREEN-API ADMIN SEND FAILED | "
            "status=%s | response=%s",
            response.status_code,
            response.text,
        )
        return False
    except Exception as exc:
        logger.exception(
            "GREEN-API ADMIN SEND EXCEPTION: %s",
            exc,
        )
        return False
# ============================================================

# ADMIN LEAD NOTIFICATION

# ============================================================


async def notify_admin_new_lead(
    lead,
    sender_phone: str,
    lead_data: Optional[Dict[str, Any]] = None,
    notification_type: str = "NEW LEAD",
    admin_whatsapp_number: Optional[str] = None,
) -> bool:
    """Send a tenant-scoped admin alert for a meaningful lead event."""
    admin_number = str(admin_whatsapp_number or ADMIN_WHATSAPP_NUMBER or "").strip()
    if not admin_number:
        logger.warning("Admin WhatsApp number is not configured.")
        return False
    lead_data = lead_data or {}
    name = getattr(lead, "name", None) or lead_data.get("name") or "Not provided"
    company = getattr(lead, "company", None) or lead_data.get("company") or "Not provided"
    business_type = getattr(lead, "business_type", None) or lead_data.get("business_type") or "Not provided"
    lead_volume = getattr(lead, "lead_volume", None) or lead_data.get("lead_volume") or "Not provided"
    interested_agent = getattr(lead, "interested_agent", None) or lead_data.get("interested_agent") or "Not specified"
    demo_date = getattr(lead, "demo_date", None) or lead_data.get("demo_date")
    demo_time = getattr(lead, "demo_time", None) or lead_data.get("demo_time")
    demo_datetime = getattr(lead, "demo_datetime", None) or lead_data.get("demo_datetime")
    if demo_datetime:
        demo_text = str(demo_datetime)
    elif demo_date or demo_time:
        demo_text = f"{demo_date or ''} {demo_time or ''}".strip()
    else:
        demo_text = "Not scheduled"
    allowed_types = {
        "NEW LEAD",
        "UPDATED LEAD",
        "NEW DEMO LEAD",
        "UPDATED DEMO LEAD",
    }
    safe_notification_type = (
        notification_type if notification_type in allowed_types else "NEW LEAD"
    )
    demo_notice = ""
    if safe_notification_type in {"NEW DEMO LEAD", "UPDATED DEMO LEAD"}:
        demo_notice = (
            "\n⚠️ Customer has NOT been told that the demo is confirmed."
            "\n👉 Please contact the customer and confirm availability."
        )
    message = f"""
🚨 {safe_notification_type}

👤 Name: {name}

📱 Customer Phone: +{sender_phone}

🏢 Company: {company}

🏷️ Business Type: {business_type}

🎯 Interested Agent: {interested_agent}

📊 Lead Volume: {lead_volume}

📅 Preferred Demo: {demo_text}

📌 Status: Lead captured

{demo_notice}

""".strip()
    return await send_admin_whatsapp_message(
        message_text=message,
        admin_whatsapp_number=admin_number,
    )
# ============================================================

# ADMIN SUPPORT TICKET NOTIFICATION

# ============================================================


async def notify_admin_new_support_ticket(
    ticket: Dict[str, Any],
    customer_name: Optional[str],
    admin_whatsapp_number: Optional[str] = None,
) -> bool:
    """
    Notify the admin only after a NEW support ticket has been
    successfully persisted.
    Existing/duplicate tickets are intentionally not notified again.
    """
    if not isinstance(ticket, dict):
        logger.error(
            "Support ticket admin notification skipped | invalid ticket data."
        )
        return False
    ticket_number = str(
        ticket.get("ticket_number") or ""
    ).strip()
    if not ticket_number:
        logger.error(
            "Support ticket admin notification skipped | ticket number missing."
        )
        return False
    name = str(
        customer_name or "Not provided"
    ).strip() or "Not provided"
    phone = str(
        ticket.get("customer_phone") or "Not provided"
    ).strip()
    category = str(
        ticket.get("category") or "general"
    ).strip()
    priority = str(
        ticket.get("priority") or "medium"
    ).strip()
    status = str(
        ticket.get("status") or "open"
    ).strip()
    subject = str(
        ticket.get("subject") or "Xytralyn Support Request"
    ).strip()
    description = str(
        ticket.get("description") or "Not provided"
    ).strip()
    message = f"""
🚨 NEW SUPPORT TICKET

🎫 Ticket: #{ticket_number}

👤 Customer: {name}

📱 Phone: +{phone}

📂 Category: {category.title()}

🔥 Priority: {priority.upper()}

📌 Status: {status.replace("_", " ").title()}

📝 Subject:

{subject}

💬 Description:

{description}

👉 Please review the ticket and contact the customer if required.

""".strip()
    try:
        sent = await send_admin_whatsapp_message(
            message_text=message,
            admin_whatsapp_number=admin_whatsapp_number,
        )
        if sent:
            logger.info(
                "Support ticket admin notification sent | "
                "ticket=%s | phone=%s",
                ticket_number,
                phone,
            )
        else:
            logger.warning(
                "Support ticket admin notification failed | "
                "ticket=%s | phone=%s",
                ticket_number,
                phone,
            )
        return sent
    except Exception as exc:
        logger.exception(
            "Support ticket admin notification exception | "
            "ticket=%s | error=%s",
            ticket_number,
            exc,
        )
        return False
# ============================================================

# META INCOMING MESSAGE PARSER

# ============================================================


def parse_whatsapp_message(
    body: Dict[str, Any],
) -> Optional[Dict[str, str]]:
    try:
        if not isinstance(body, dict):
            return None
        if body.get("object") != (
            "whatsapp_business_account"
        ):
            logger.info(
                "META webhook ignored | object=%s",
                body.get("object"),
            )
            return None
        entries = body.get(
            "entry",
            [],
        )
        if not entries:
            return None
        for entry in entries:
            changes = entry.get(
                "changes",
                [],
            ) or []
            for change in changes:
                value = change.get(
                    "value",
                    {},
                ) or {}
                metadata = value.get("metadata", {}) or {}
                phone_number_id = str(metadata.get("phone_number_id") or "").strip()
                if not phone_number_id:
                    logger.warning("META webhook ignored | phone_number_id missing")
                    continue
                messages = value.get(
                    "messages",
                    [],
                ) or []
                if not messages:
                    continue
                for message in messages:
                    message_id = message.get(
                        "id",
                        "",
                    )
                    message_type = message.get(
                        "type",
                        "",
                    )
                    if message_type != "text":
                        logger.info(
                            "META message ignored | type=%s",
                            message_type,
                        )
                        continue
                    sender_phone = message.get(
                        "from",
                        "",
                    )
                    sender_phone = (
                        normalize_customer_phone(
                            sender_phone
                        )
                    )
                    if not sender_phone:
                        continue
                    text_data = message.get(
                        "text",
                        {},
                    ) or {}
                    message_text = text_data.get(
                        "body",
                        "",
                    )
                    message_text = str(
                        message_text or ""
                    ).strip()
                    if not message_text:
                        continue
                    logger.info(
                        "META incoming WhatsApp message | "
                        "type=%s | phone=%s",
                        message_type,
                        sender_phone,
                    )
                    return {
                        "message_id": str(
                            message_id or ""
                        ),
                        "sender_phone": sender_phone,
                        "message_text": message_text,
                        "phone_number_id": phone_number_id,
                    }
        return None
    except Exception as exc:
        logger.exception(
            "Failed to parse Meta WhatsApp webhook: %s",
            exc,
        )
        return None
# ============================================================

# DUPLICATE MESSAGE PROTECTION

# ============================================================

PROCESSED_MESSAGE_IDS = set()

PROCESSED_MESSAGE_ORDER: List[str] = []

MAX_PROCESSED_MESSAGE_IDS = 5000


def is_duplicate_message(message_id: str) -> bool:
    """Claim a message ID for processing and return True if already claimed."""
    message_id = str(message_id or "").strip()
    if not message_id:
        return False
    if message_id in PROCESSED_MESSAGE_IDS:
        return True
    PROCESSED_MESSAGE_IDS.add(message_id)
    PROCESSED_MESSAGE_ORDER.append(message_id)
    if len(PROCESSED_MESSAGE_ORDER) > MAX_PROCESSED_MESSAGE_IDS:
        oldest = PROCESSED_MESSAGE_ORDER.pop(0)
        PROCESSED_MESSAGE_IDS.discard(oldest)
    return False


def release_message_id(message_id: str) -> None:
    """Release a claimed ID when processing failed so Meta can retry it."""
    message_id = str(message_id or "").strip()
    if not message_id:
        return
    PROCESSED_MESSAGE_IDS.discard(message_id)
    try:
        PROCESSED_MESSAGE_ORDER.remove(message_id)
    except ValueError:
        pass
# ============================================================

# XYTRALYN CHAT ROUTE

# META WHATSAPP CLOUD API

# PART 2/2

# ============================================================

# ============================================================

# CUSTOMER MESSAGE HANDLER

# ============================================================


async def handle_customer_message(
    sender_phone: str,
    user_message: str,
    tenant_id=None,
    tenant_name: str = BUSINESS_NAME,
    admin_whatsapp_number: Optional[str] = None,
) -> Optional[str]:
    sender_phone = normalize_customer_phone(
        sender_phone
    )
    user_message = (
        user_message or ""
    ).strip()
    if not sender_phone:
        logger.error("Customer phone missing.")
        return None
    if tenant_id is None:
        logger.error("Tenant ID missing for customer message | phone=%s", sender_phone)
        return None
    if not user_message:
        return None
    db = SessionLocal()
    try:
        # ====================================================
        # 1. LOAD PREVIOUS CONVERSATION
        # ====================================================
        history = build_chat_history(
            db,
            sender_phone,
            HISTORY_LIMIT,
            tenant_id=tenant_id,
        )
        # ====================================================
        # 2. SNAPSHOT LEAD BEFORE THIS TURN
        # ====================================================
        # This MUST happen before memory/update so that a first demo slot
        # and a later demo correction can be detected correctly.
        snapshot_fields = [
            "name",
            "email",
            "company",
            "business_type",
            "lead_volume",
            "interested_agent",
            "demo_date",
            "demo_time",
            "demo_datetime",
        ]
        previous_lead = (
            db.query(Lead)
            .filter(Lead.tenant_id == tenant_id, Lead.phone == sender_phone)
            .first()
        )
        previous_snapshot = {
            field: (
                getattr(previous_lead, field, None)
                if previous_lead is not None
                else None
            )
            for field in snapshot_fields
        }
        # ====================================================
        # 3. UPDATE CUSTOMER MEMORY
        # ====================================================
        customer_memory = process_customer_memory(
            sender_phone,
            user_message,
            history=history,
            tenant_id=tenant_id,
        )
        customer_context = memory_to_text(
            customer_memory
        )
        # ====================================================
        # 4. AGENT DETECTION
        # ====================================================
        agent_name = detect_agent(
            user_message
        )
        # ====================================================
        # 5. LEAD EXTRACTION
        # ====================================================
        lead_data = extract_lead_info(
            user_message,
            history=history,
        )
        # ====================================================
        # 6. SAVE USER MESSAGE
        # ====================================================
        save_message(
            db=db,
            sender_phone=sender_phone,
            content=user_message,
            agent_name=agent_name,
            sender_type="user",
            tenant_id=tenant_id,
        )
        # ====================================================
        # 7. UPDATE LEAD
        # ====================================================
        # Merge persistent memory with the fields extracted from this turn.
        # Do not insert hard-coded customer examples.
        merged_lead_data = dict(
            customer_memory or {}
        )
        for field, value in (lead_data or {}).items():
            if is_valid_memory_value(value):
                if (
                    field != "name"
                    or is_valid_customer_name(value)
                ):
                    merged_lead_data[field] = value
        logger.info(
            "XYTRALYN LEAD | extracted | phone=%s | data=%s",
            sender_phone,
            merged_lead_data,
        )
        try:
            # Always upsert by phone, even if merged_lead_data is empty.
            # This guarantees that every WhatsApp customer has a Lead row.
            lead = update_or_create_lead(
                db=db,
                sender_phone=sender_phone,
                lead_data=merged_lead_data,
                tenant_id=tenant_id,
            )
        except Exception as exc:
            logger.exception(
                "Lead update failed | phone=%s | data=%s | error=%s",
                sender_phone,
                merged_lead_data,
                exc,
            )
            lead = (
                db.query(Lead)
                .filter(Lead.tenant_id == tenant_id, Lead.phone == sender_phone)
                .first()
            )
        # ====================================================
        # 8. ADMIN LEAD NOTIFICATION
        # ====================================================
        # Notify only when meaningful lead data changed. Demo events
        # receive their dedicated NEW/UPDATED DEMO labels. Repeating
        # the same information does not create another alert.
        if lead is not None:
            current_snapshot = {
                field: getattr(lead, field, None)
                for field in snapshot_fields
            }
            def _snapshot_value(value: Any) -> str:
                if value is None:
                    return ""
                return str(value).strip()
            changed_fields = [
                field
                for field in snapshot_fields
                if _snapshot_value(previous_snapshot.get(field))
                != _snapshot_value(current_snapshot.get(field))
            ]
            has_demo_slot = any(
                _snapshot_value(current_snapshot.get(field))
                for field in ("demo_date", "demo_time", "demo_datetime")
            )
            had_previous_demo = any(
                _snapshot_value(previous_snapshot.get(field))
                for field in ("demo_date", "demo_time", "demo_datetime")
            )
            demo_changed = any(
                _snapshot_value(previous_snapshot.get(field))
                != _snapshot_value(current_snapshot.get(field))
                for field in ("demo_date", "demo_time", "demo_datetime")
            )
            had_meaningful_previous_lead = any(
                _snapshot_value(previous_snapshot.get(field))
                for field in snapshot_fields
            )
            if changed_fields:
                if has_demo_slot and not had_previous_demo:
                    notification_type = "NEW DEMO LEAD"
                elif has_demo_slot and had_previous_demo and demo_changed:
                    notification_type = "UPDATED DEMO LEAD"
                elif not had_meaningful_previous_lead:
                    notification_type = "NEW LEAD"
                else:
                    notification_type = "UPDATED LEAD"
                try:
                    admin_notified = await notify_admin_new_lead(
                        lead=lead,
                        sender_phone=sender_phone,
                        lead_data=merged_lead_data,
                        notification_type=notification_type,
                        admin_whatsapp_number=admin_whatsapp_number,
                    )
                    if admin_notified:
                        lead.status = "admin_notified"
                        db.commit()
                        db.refresh(lead)
                        logger.info(
                            "Lead admin notification sent | type=%s | phone=%s | changed=%s",
                            notification_type,
                            sender_phone,
                            changed_fields,
                        )
                    else:
                        logger.warning(
                            "Lead admin notification failed | type=%s | phone=%s",
                            notification_type,
                            sender_phone,
                        )
                except Exception as exc:
                    logger.exception(
                        "Lead admin notification exception | phone=%s | error=%s",
                        sender_phone,
                        exc,
                    )
        # ====================================================
        # 9. AI REPLY
        # ====================================================
        #
        # SUPPORT gets its own dedicated service.
        # Other agents keep the existing production path.
        # ====================================================
        logger.info(
            "AI processing started | phone=%s | agent=%s",
            sender_phone,
            agent_name,
        )
        ticket_result = None
        if agent_name == "support":
            # support_agent.py currently uses the synchronous Groq client.
            # Run it in a worker thread so the async webhook is not blocked.
            support_result = await asyncio.to_thread(
                generate_support_reply,
                user_message,
                history,
                customer_memory.get("name"),
            )
            if not isinstance(support_result, dict):
                logger.error(
                    "Support agent returned invalid result | phone=%s",
                    sender_phone,
                )
                return None
            reply = str(
                support_result.get("reply") or ""
            ).strip()
            # ------------------------------------------------
            # SUPPORT TICKET CREATION
            # ------------------------------------------------
            if support_result.get("create_ticket"):
                try:
                    ticket_result = create_ticket(
                        db=db,
                        customer_phone=sender_phone,
                        subject=support_result.get(
                            "subject"
                        ) or "Xytralyn Support Request",
                        description=support_result.get(
                            "description"
                        ) or user_message,
                        category=support_result.get(
                            "category"
                        ) or "general",
                        priority=support_result.get(
                            "priority"
                        ) or "medium",
                        user_id=getattr(
                            lead,
                            "user_id",
                            None,
                        ),
                        prevent_duplicate=True,
                        tenant_id=tenant_id,
                    )
                except Exception as exc:
                    logger.exception(
                        "Support ticket creation failed | "
                        "phone=%s | error=%s",
                        sender_phone,
                        exc,
                    )
                    ticket_result = {
                        "success": False,
                        "created": False,
                        "duplicate": False,
                        "ticket": None,
                        "error": str(exc),
                    }
                # Never claim a ticket exists unless the DB operation
                # actually succeeded.
                if (
                    isinstance(ticket_result, dict)
                    and ticket_result.get("success")
                    and ticket_result.get("ticket")
                ):
                    ticket = ticket_result["ticket"]
                    ticket_number = (
                        ticket.get("ticket_number")
                        or "N/A"
                    )
                    if ticket_result.get("created"):
                        ticket_confirmation = (
                            f"Support ticket #{ticket_number} "
                            "create ho gaya hai. Support team "
                            "aapki request check karegi."
                        )
                    else:
                        ticket_confirmation = (
                            f"Aapka support ticket #{ticket_number} "
                            "already open hai. Aapki latest message "
                            "usi request ke context mein handle ki ja rahi hai."
                        )
                    if reply:
                        reply = (
                            f"{reply}\n\n"
                            f"{ticket_confirmation}"
                        )
                    else:
                        reply = ticket_confirmation
                    # ------------------------------------------------
                    # NEW TICKET -> ADMIN WHATSAPP NOTIFICATION
                    # ------------------------------------------------
                    # Notify the admin only when this request created
                    # a brand-new ticket. Existing/duplicate tickets
                    # must not generate repeated admin alerts.
                    if ticket_result.get("created"):
                        admin_ticket_notified = (
                            await notify_admin_new_support_ticket(
                                ticket=ticket,
                                customer_name=customer_memory.get("name"),
                                admin_whatsapp_number=admin_whatsapp_number,
                            )
                        )
                        if admin_ticket_notified:
                            logger.info(
                                "XYTRALYN TICKET | admin notified | "
                                "phone=%s | ticket=%s",
                                sender_phone,
                                ticket_number,
                            )
                        else:
                            # The ticket remains persisted even if the
                            # admin WhatsApp notification fails.
                            logger.warning(
                                "XYTRALYN TICKET | admin notification failed | "
                                "phone=%s | ticket=%s",
                                sender_phone,
                                ticket_number,
                            )
                    logger.info(
                        "XYTRALYN TICKET | customer notification prepared | "
                        "phone=%s | ticket=%s | created=%s | duplicate=%s",
                        sender_phone,
                        ticket_number,
                        ticket_result.get("created"),
                        ticket_result.get("duplicate"),
                    )
                else:
                    logger.warning(
                        "Support ticket was requested but was not persisted | "
                        "phone=%s",
                        sender_phone,
                    )
            if not reply:
                logger.error(
                    "Support agent returned empty reply | phone=%s",
                    sender_phone,
                )
                return None
        else:
            # ------------------------------------------------
            # EXISTING AI FLOW — UNCHANGED
            # ------------------------------------------------
            reply = await generate_agent_reply(
                user_message=user_message,
                history=history,
                customer_memory=customer_context,
                agent_name=agent_name,
                business_name=tenant_name or BUSINESS_NAME,
            )
            if not reply:
                logger.error(
                    "AI returned empty reply | phone=%s",
                    sender_phone,
                )
                return None
            reply = str(reply).strip()
            if not reply:
                return None
        # ====================================================
        # 10. SAVE ASSISTANT MESSAGE
        # ====================================================
        save_message(
            db=db,
            sender_phone=sender_phone,
            content=reply,
            agent_name=agent_name,
            sender_type="assistant",
            tenant_id=tenant_id,
        )
        logger.info(
            "AI reply generated | phone=%s",
            sender_phone,
        )
        return reply
    except Exception as exc:
        db.rollback()
        logger.exception(
            "Customer message processing failed | "
            "phone=%s | error=%s",
            sender_phone,
            exc,
        )
        return None
    finally:
        db.close()
# ============================================================

# META WEBHOOK VERIFICATION

# ============================================================

@router.get("/webhook")


async def verify_meta_webhook(
    request: Request,
):
    params = request.query_params
    mode = params.get(
        "hub.mode"
    )
    verify_token = params.get(
        "hub.verify_token"
    )
    challenge = params.get(
        "hub.challenge"
    )
    logger.info(
        "META webhook verification request | mode=%s",
        mode,
    )
    if (
        mode == "subscribe"
        and verify_token == WHATSAPP_VERIFY_TOKEN
    ):
        logger.info(
            "META webhook verification successful."
        )
        return PlainTextResponse(
            content=challenge or "",
            status_code=200,
        )
    logger.warning(
        "META webhook verification failed."
    )
    return PlainTextResponse(
        content="Forbidden",
        status_code=403,
    )
# ============================================================

# META WEBHOOK

# ============================================================

@router.post("/webhook")


async def meta_whatsapp_webhook(
    request: Request,
):
    logger.warning(
        "XYTRALYN META DEBUG 1 | webhook received"
    )
    try:
        body = await request.json()
    except Exception as exc:
        logger.exception(
            "Failed to read Meta webhook JSON: %s",
            exc,
        )
        return PlainTextResponse(
            content="OK",
            status_code=200,
        )
    # ========================================================
    # SAFE DIAGNOSTICS
    # ========================================================
    if isinstance(body, dict):
        logger.warning(
            "XYTRALYN META DEBUG | keys=%s",
            list(body.keys()),
        )
        logger.warning(
            "XYTRALYN META DEBUG | object=%s",
            body.get("object"),
        )
    # ========================================================
    # PARSE MESSAGE
    # ========================================================
    parsed = parse_whatsapp_message(
        body
    )
    if not parsed:
        logger.info(
            "META webhook received but no "
            "customer text message found."
        )
        return PlainTextResponse(
            content="EVENT_RECEIVED",
            status_code=200,
        )
    message_id = parsed.get(
        "message_id",
        "",
    )
    sender_phone = parsed.get(
        "sender_phone",
        "",
    )
    user_message = parsed.get(
        "message_text",
        "",
    )
    phone_number_id = parsed.get("phone_number_id", "")
    # ========================================================
    # DUPLICATE PROTECTION
    # ========================================================
    if is_duplicate_message(
        message_id
    ):
        logger.info(
            "Duplicate Meta message ignored | id=%s",
            message_id,
        )
        return PlainTextResponse(
            content="EVENT_RECEIVED",
            status_code=200,
        )
    # ========================================================
    # TENANT RESOLUTION
    # ========================================================
    db = SessionLocal()
    try:
        account, tenant = resolve_whatsapp_context(db, phone_number_id)
        if not account or not tenant:
            logger.error("Unknown/inactive WhatsApp tenant | phone_number_id=%s", phone_number_id)
            return PlainTextResponse(content="EVENT_RECEIVED", status_code=200)
        tenant_id = tenant.id
        tenant_name = tenant_value(tenant, "name", BUSINESS_NAME)
        admin_whatsapp_number = str(getattr(account, "admin_whatsapp_number", "") or "").strip()
    finally:
        db.close()
    logger.info("XYTRALYN TENANT RESOLVED | tenant=%s | tenant_id=%s | phone_number_id=%s", tenant_name, tenant_id, phone_number_id)
    # ========================================================
    # AI PROCESSING
    # ========================================================
    logger.warning(
        "XYTRALYN META DEBUG | "
        "AI processing | phone=%s",
        sender_phone,
    )
    reply = await handle_customer_message(
        sender_phone=sender_phone,
        user_message=user_message,
        tenant_id=tenant_id,
        tenant_name=tenant_name,
        admin_whatsapp_number=admin_whatsapp_number,
    )
    if not reply:
        release_message_id(message_id)
        logger.error(
            "AI reply was empty | phone=%s",
            sender_phone,
        )
        return PlainTextResponse(
            content="EVENT_RECEIVED",
            status_code=200,
        )
    # ========================================================
    # SEND REPLY THROUGH META
    # ========================================================
    logger.warning(
        "XYTRALYN META DEBUG | "
        "sending reply | phone=%s",
        sender_phone,
    )
    sent = await send_whatsapp_message(
    recipient_phone=sender_phone,
    message_text=reply,
    tenant_id=tenant_id,
    phone_number_id=phone_number_id,
)
    logger.warning(
        "XYTRALYN META DEBUG | send_result=%s",
        sent,
    )
    if not sent:
        # Do not permanently consume a message that failed to send.
        # Meta can retry the webhook and the message can be processed again.
        release_message_id(message_id)
    return PlainTextResponse(
        content="EVENT_RECEIVED",
        status_code=200,
    )
# ============================================================

# HEALTH

# ============================================================

@router.get("/health")


async def chat_health():
    return {
        "status": "ok",
        "service": "Xytralyn WhatsApp AI",
        "meta_api": bool(
            WHATSAPP_TOKEN
            and WHATSAPP_PHONE_NUMBER_ID
        ),
        "green_api": bool(
            GREEN_API_INSTANCE_ID
            and GREEN_API_TOKEN
            and ADMIN_WHATSAPP_NUMBER
        ),
        "twilio": False,
    }
# ============================================================

# DEBUG CUSTOMER

# ============================================================

@router.get(
    "/debug/customer/{phone}"
)


async def debug_customer(
    phone: str,
    phone_number_id: str,
):
    if not DEBUG_ROUTES_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")
    normalized_phone = normalize_customer_phone(phone)
    if not normalized_phone:
        raise HTTPException(status_code=400, detail="Invalid phone number")
    db = SessionLocal()
    try:
        account, tenant = resolve_whatsapp_context(db, phone_number_id)
        if not account or not tenant:
            raise HTTPException(status_code=404, detail="WhatsApp tenant not found")
        memory = get_customer_memory(normalized_phone, tenant.id)
        return {"phone": normalized_phone, "tenant_id": str(tenant.id), "tenant_name": tenant.name, "memory": memory}
    finally:
        db.close()
# ============================================================

# CLEAR CUSTOMER MEMORY

# ============================================================

@router.delete(
    "/debug/customer/{phone}"
)


async def clear_customer_memory(
    phone: str,
    phone_number_id: str,
):
    if not DEBUG_ROUTES_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")
    normalized_phone = normalize_customer_phone(phone)
    if not normalized_phone:
        return {"status": "invalid_phone", "phone": normalized_phone}
    db = SessionLocal()
    try:
        account, tenant = resolve_whatsapp_context(db, phone_number_id)
        if not account or not tenant:
            raise HTTPException(status_code=404, detail="WhatsApp tenant not found")
        lead = (
            db.query(Lead)
            .filter(Lead.tenant_id == tenant.id, Lead.phone == normalized_phone)
            .first()
        )
        if not lead:
            return {"status": "not_found", "phone": normalized_phone}
        for field in [
            "name", "email", "company", "business_type", "lead_volume",
            "interested_agent", "demo_date", "demo_time", "demo_datetime",
        ]:
            setattr(lead, field, None)
        lead.demo_status = "not_scheduled"
        db.commit()
        return {"status": "cleared", "phone": normalized_phone, "tenant_id": str(tenant.id), "memory": {}}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to clear customer memory | error=%s", exc)
        raise HTTPException(status_code=500, detail="Failed to clear customer memory")
    finally:
        db.close()
