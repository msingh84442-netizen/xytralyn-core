# ============================================================
# XYTRALYN CHAT ROUTE
# META WHATSAPP CLOUD API
# PART 1/2
# ============================================================

import os
import re
import logging
from typing import Optional, Dict, Any, List

import httpx

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from app.database import SessionLocal
from app.models import Lead, Message

from app.services.ai_agent import (
    detect_agent,
    extract_lead_info,
    extract_demo_datetime,
    generate_agent_reply,
    normalize_history,
    merge_customer_memory,
    memory_to_text,
    is_valid_customer_name,
    is_valid_memory_value,
)

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

META_ACCESS_TOKEN = (os.getenv("META_ACCESS_TOKEN") or "").strip()
META_PHONE_NUMBER_ID = (os.getenv("META_PHONE_NUMBER_ID") or "").strip()
META_VERIFY_TOKEN = (os.getenv("META_VERIFY_TOKEN") or "").strip()
META_GRAPH_VERSION = (
    os.getenv("META_GRAPH_VERSION") or "v26.0"
).strip()

ADMIN_WHATSAPP_NUMBER = (
    os.getenv("ADMIN_WHATSAPP_NUMBER") or ""
).strip()

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
# CUSTOMER MEMORY
# ============================================================

CUSTOMER_MEMORY: Dict[str, Dict[str, Any]] = {}


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
) -> Dict[str, Any]:

    phone = normalize_customer_phone(phone)

    if not phone:
        return {}

    db = SessionLocal()

    try:
        lead = (
            db.query(Lead)
            .filter(Lead.phone == phone)
            .first()
        )

        if not lead:
            return {}

        fields = [
            "name",
            "email",
            "company",
            "business_type",
            "lead_volume",
            "interested_agent",
            "demo_date",
            "demo_time",
            "demo_datetime",
            "demo_status",
        ]

        raw_memory = {}
        changed = False

        for field in fields:
            value = getattr(lead, field, None)

            if not is_valid_memory_value(value):
                # Remove stale placeholder values from the database.
                if value not in (None, "") and field != "demo_status":
                    try:
                        setattr(lead, field, None)
                        changed = True
                    except Exception:
                        pass
                continue

            if field == "name" and not is_valid_customer_name(value):
                try:
                    lead.name = None
                    changed = True
                except Exception:
                    pass
                continue

            raw_memory[field] = value

        if changed:
            db.commit()
            db.refresh(lead)

        return sanitize_customer_memory_data(raw_memory)

    except Exception as exc:
        db.rollback()
        logger.exception(
            "Failed to load customer memory: %s",
            exc,
        )
        return {}

    finally:
        db.close()


def update_customer_memory(
    phone: str,
    new_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:

    phone = normalize_customer_phone(phone)

    if not phone:
        return {}

    new_data = sanitize_customer_memory_data(new_data or {})

    db = SessionLocal()

    try:
        lead = (
            db.query(Lead)
            .filter(Lead.phone == phone)
            .first()
        )

        if not lead:
            lead = Lead(
                phone=phone,
                status="new",
                demo_status="not_scheduled",
            )
            db.add(lead)
            db.flush()

        fields = [
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

        for field in fields:
            value = new_data.get(field)
            if not is_valid_memory_value(value):
                continue

            if field == "name" and not is_valid_customer_name(value):
                continue

            setattr(lead, field, value)

        if (
            new_data.get("demo_date")
            or new_data.get("demo_time")
            or new_data.get("demo_datetime")
        ):
            lead.demo_status = "preferred_slot"

        # Clean old placeholder identity values even if this turn
        # did not contain a new name/company.
        if not is_valid_customer_name(getattr(lead, "name", None)):
            lead.name = None

        if not is_valid_memory_value(getattr(lead, "company", None)):
            lead.company = None

        db.commit()
        db.refresh(lead)

        return get_customer_memory(phone)

    except Exception as exc:
        db.rollback()
        logger.exception(
            "Failed to save customer memory: %s",
            exc,
        )
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
) -> List[Dict[str, str]]:

    sender_phone = normalize_customer_phone(
        sender_phone
    )

    if not sender_phone:
        return []

    messages = (
        db.query(Message)
        .filter(
            Message.sender_phone == sender_phone
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
) -> Dict[str, Any]:

    sender_phone = normalize_customer_phone(
        sender_phone
    )

    if not sender_phone:
        return {}

    if not user_message:
        return get_customer_memory(
            sender_phone
        )

    new_data = extract_lead_info(
        user_message
    )

    try:

        (
            demo_date,
            demo_time,
            demo_datetime,
        ) = extract_demo_datetime(
            user_message
        )

        if demo_date:
            new_data["demo_date"] = demo_date

        if demo_time:
            new_data["demo_time"] = demo_time

        if demo_datetime:
            new_data["demo_datetime"] = (
                demo_datetime
            )

    except Exception as exc:

        logger.warning(
            "Demo datetime extraction failed: %s",
            exc,
        )

    return update_customer_memory(
        sender_phone,
        new_data,
    )


# ============================================================
# CUSTOMER CONTEXT
# ============================================================

def get_customer_context(
    sender_phone: str,
) -> str:

    memory = get_customer_memory(
        sender_phone
    )

    return memory_to_text(memory)


# ============================================================
# LEAD DATABASE
# ============================================================

def update_or_create_lead(
    db,
    sender_phone: str,
    lead_data: Optional[Dict[str, Any]],
) -> Optional[Lead]:

    sender_phone = normalize_customer_phone(sender_phone)

    if not sender_phone:
        return None

    lead_data = sanitize_customer_memory_data(lead_data or {})

    if not lead_data:
        return None

    lead = (
        db.query(Lead)
        .filter(Lead.phone == sender_phone)
        .first()
    )

    if not lead:
        lead = Lead(
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
):

    sender_phone = normalize_customer_phone(
        sender_phone
    )

    if not sender_phone:
        return None

    if not content:
        return None

    message = Message(
        sender_phone=sender_phone,
        content=content,
        agent_used=agent_name,
    )

    if hasattr(message, "sender_type"):

        message.sender_type = sender_type

    db.add(message)
    db.commit()
    db.refresh(message)

    return message


# ============================================================
# META SEND MESSAGE
# ============================================================

async def send_whatsapp_message(
    recipient_phone: str,
    message_text: str,
) -> bool:

    if not META_ACCESS_TOKEN:

        logger.error(
            "META_ACCESS_TOKEN is missing."
        )

        return False

    if not META_PHONE_NUMBER_ID:

        logger.error(
            "META_PHONE_NUMBER_ID is missing."
        )

        return False

    if not recipient_phone:

        logger.error(
            "Recipient phone is missing."
        )

        return False

    if not message_text:

        logger.error(
            "Message text is missing."
        )

        return False

    phone_digits = normalize_customer_phone(
        recipient_phone
    )

    if not phone_digits:

        logger.error(
            "Invalid recipient phone."
        )

        return False

    url = (
    f"https://graph.facebook.com/"
    f"{META_GRAPH_VERSION.strip()}/"
    f"{META_PHONE_NUMBER_ID.strip()}/messages"
)

    headers = {
        "Authorization": (
            f"Bearer {META_ACCESS_TOKEN}"
        ),
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone_digits,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message_text,
        },
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

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        if response.is_success:

            logger.info(
                "META WhatsApp send accepted | "
                "status=%s | response=%s",
                response.status_code,
                response.text,
            )

            return True

        # ----------------------------------------------------
        # META API ERROR
        # ----------------------------------------------------

        logger.error(
            "META WhatsApp send failed | "
            "status=%s | response=%s",
            response.status_code,
            response.text,
        )

        return False

    except Exception as exc:

        logger.exception(
            "META WhatsApp send exception: %s",
            exc,
        )

        return False
# ============================================================
# GREEN-API ADMIN MESSAGE SENDER
# ============================================================

async def send_admin_whatsapp_message(
    message_text: str,
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

    if not ADMIN_WHATSAPP_NUMBER:
        logger.error(
            "ADMIN_WHATSAPP_NUMBER is missing."
        )
        return False

    if not message_text:
        logger.error(
            "Admin message is empty."
        )
        return False

    admin_phone = normalize_customer_phone(
        ADMIN_WHATSAPP_NUMBER
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
) -> bool:

    if not ADMIN_WHATSAPP_NUMBER:
        logger.warning(
            "ADMIN_WHATSAPP_NUMBER is not configured."
        )
        return False

    lead_data = lead_data or {}

    name = (
        getattr(lead, "name", None)
        or lead_data.get("name")
        or "Not provided"
    )

    company = (
        getattr(lead, "company", None)
        or lead_data.get("company")
        or "Not provided"
    )

    business_type = (
        getattr(lead, "business_type", None)
        or lead_data.get("business_type")
        or "Not provided"
    )

    lead_volume = (
        getattr(lead, "lead_volume", None)
        or lead_data.get("lead_volume")
        or "Not provided"
    )

    interested_agent = (
        getattr(lead, "interested_agent", None)
        or lead_data.get("interested_agent")
        or "Not specified"
    )

    demo_date = (
        getattr(lead, "demo_date", None)
        or lead_data.get("demo_date")
    )

    demo_time = (
        getattr(lead, "demo_time", None)
        or lead_data.get("demo_time")
    )

    demo_datetime = (
        getattr(lead, "demo_datetime", None)
        or lead_data.get("demo_datetime")
    )

    if demo_datetime:

        demo_text = str(
            demo_datetime
        )

    elif demo_date or demo_time:

        demo_text = (
            f"{demo_date or ''} "
            f"{demo_time or ''}"
        ).strip()

    else:

        demo_text = "Not scheduled"

    message = f"""
🚨 NEW DEMO LEAD

👤 Name: {name}
📱 Customer Phone: +{sender_phone}

🏢 Company: {company}
🏷️ Business Type: {business_type}

🎯 Interested Agent: {interested_agent}
📊 Lead Volume: {lead_volume}

📅 Preferred Demo: {demo_text}

📌 Status: Preferred Slot

⚠️ Customer has NOT been told that the demo is confirmed.

👉 Please contact the customer and confirm availability.
""".strip()

    return await send_admin_whatsapp_message(
        message_text=message
    )
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


def is_duplicate_message(
    message_id: str,
) -> bool:

    if not message_id:
        return False

    if message_id in PROCESSED_MESSAGE_IDS:
        return True

    PROCESSED_MESSAGE_IDS.add(
        message_id
    )

    if len(PROCESSED_MESSAGE_IDS) > 5000:

        PROCESSED_MESSAGE_IDS.clear()

        PROCESSED_MESSAGE_IDS.add(
            message_id
        )

    return False
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
) -> Optional[str]:

    sender_phone = normalize_customer_phone(
        sender_phone
    )

    user_message = (
        user_message or ""
    ).strip()

    if not sender_phone:

        logger.error(
            "Customer phone missing."
        )

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
        )

                # ====================================================
        # 2. UPDATE CUSTOMER MEMORY
        # ====================================================

        customer_memory = process_customer_memory(
            sender_phone,
            user_message,
        )

        customer_context = memory_to_text(
            customer_memory
        )

        
        # ====================================================
        # 3. AGENT DETECTION
        # ====================================================

        agent_name = detect_agent(
            user_message
        )

        # ====================================================
        # 4. LEAD EXTRACTION
        # ====================================================

        lead_data = extract_lead_info(
            user_message
        )

        # ====================================================
        # 5. SAVE USER MESSAGE
        # ====================================================

        save_message(
            db=db,
            sender_phone=sender_phone,
            content=user_message,
            agent_name=agent_name,
            sender_type="user",
        )

                # ====================================================
        # 6. UPDATE LEAD + DEMO-READY ADMIN NOTIFICATION
        # ====================================================

        lead = None

        # process_customer_memory() has already persisted the latest
        # customer information, including demo date/time.
        # Use the complete persistent memory so older fields are not lost.
        merged_lead_data = dict(customer_memory or {})
        merged_lead_data.update(lead_data or {})

        # Explicitly persist the extracted demo slot from this message.
        try:

            (
                current_demo_date,
                current_demo_time,
                current_demo_datetime,
            ) = extract_demo_datetime(user_message)

            if current_demo_date:
                merged_lead_data["demo_date"] = (
                    current_demo_date
                )

            if current_demo_time:
                merged_lead_data["demo_time"] = (
                    current_demo_time
                )

            if current_demo_datetime:
                merged_lead_data["demo_datetime"] = (
                    current_demo_datetime
                )

        except Exception as exc:

            logger.warning(
                "Lead demo extraction failed: %s",
                exc,
            )

        if merged_lead_data:

            try:

                lead = update_or_create_lead(
                    db=db,
                    sender_phone=sender_phone,
                    lead_data=merged_lead_data,
                )

            except Exception as exc:

                logger.exception(
                    "Lead update failed: %s",
                    exc,
                )

        # ----------------------------------------------------
        # DEMO-READY CONDITION
        # ----------------------------------------------------
        # A preferred slot is enough to notify the admin.
        # Name/company are included when available, but are not
        # required for notification.

        if lead is None:

            lead = (
                db.query(Lead)
                .filter(
                    Lead.phone == sender_phone
                )
                .first()
            )

        if lead is not None:

            lead_demo_date = getattr(
                lead,
                "demo_date",
                None,
            )

            lead_demo_time = getattr(
                lead,
                "demo_time",
                None,
            )

            lead_demo_datetime = getattr(
                lead,
                "demo_datetime",
                None,
            )

            has_demo_slot = bool(
                lead_demo_datetime
                or (
                    lead_demo_date
                    and lead_demo_time
                )
            )

            if (
                has_demo_slot
                and getattr(
                    lead,
                    "status",
                    None,
                ) != "admin_notified"
            ):

                try:

                    admin_notified = (
                        await notify_admin_new_lead(
                            lead=lead,
                            sender_phone=sender_phone,
                            lead_data=merged_lead_data,
                        )
                    )

                    if admin_notified:

                        # IMPORTANT:
                        # admin_notified means the admin received
                        # the lead. It does NOT mean the demo is
                        # confirmed/booked.

                        lead.status = (
                            "admin_notified"
                        )

                        db.commit()
                        db.refresh(lead)

                        logger.info(
                            "Demo-ready lead sent to admin | phone=%s",
                            sender_phone,
                        )

                    else:

                        logger.warning(
                            "Admin notification failed | phone=%s",
                            sender_phone,
                        )

                except Exception as exc:

                    logger.exception(
                        "Demo-ready admin notification failed: %s",
                        exc,
                    )

        # ====================================================
        # 7. AI REPLY
        # ====================================================

        logger.info(
            "AI processing started | phone=%s",
            sender_phone,
        )

        reply = await generate_agent_reply(
            user_message=user_message,
            history=history,
            customer_memory=customer_context,
            agent_name=agent_name,
            business_name=BUSINESS_NAME,
        )

        if not reply:

            logger.error(
                "AI returned empty reply."
            )

            return None

        reply = str(reply).strip()

        if not reply:
            return None

        # ====================================================
        # 8. SAVE ASSISTANT MESSAGE
        # ====================================================

        save_message(
            db=db,
            sender_phone=sender_phone,
            content=reply,
            agent_name=agent_name,
            sender_type="assistant",
        )

        logger.info(
            "AI reply generated | phone=%s",
            sender_phone,
        )

        return reply

    except Exception as exc:

        logger.exception(
            "Customer message processing failed: %s",
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
        and verify_token == META_VERIFY_TOKEN
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
    )

    if not reply:

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
    )

    logger.warning(
        "XYTRALYN META DEBUG | send_result=%s",
        sent,
    )

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
            META_ACCESS_TOKEN
            and META_PHONE_NUMBER_ID
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
):

    normalized_phone = (
        normalize_customer_phone(
            phone
        )
    )

    return {
        "phone": normalized_phone,
        "memory": get_customer_memory(
            normalized_phone
        ),
    }


# ============================================================
# CLEAR CUSTOMER MEMORY
# ============================================================

@router.delete(
    "/debug/customer/{phone}"
)
async def clear_customer_memory(
    phone: str,
):

    normalized_phone = normalize_customer_phone(phone)

    if not normalized_phone:
        return {
            "status": "invalid_phone",
            "phone": normalized_phone,
        }

    db = SessionLocal()

    try:
        lead = (
            db.query(Lead)
            .filter(Lead.phone == normalized_phone)
            .first()
        )

        if not lead:
            return {
                "status": "not_found",
                "phone": normalized_phone,
            }

        # Clear customer memory while preserving the lead record.
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
            if hasattr(lead, field):
                setattr(lead, field, None)

        if hasattr(lead, "demo_status"):
            lead.demo_status = "not_scheduled"

        db.commit()

        return {
            "status": "cleared",
            "phone": normalized_phone,
            "memory": {},
        }

    except Exception as exc:
        db.rollback()
        logger.exception(
            "Failed to clear customer memory: %s",
            exc,
        )
        return {
            "status": "error",
            "phone": normalized_phone,
        }

    finally:
        db.close()
