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
    generate_agent_reply,
    is_potential_lead,
    normalize_history,
    merge_customer_memory,
    memory_to_text,
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

META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
META_PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID")
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN")

META_GRAPH_VERSION = os.getenv(
    "META_GRAPH_VERSION",
    "v26.0",
)


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


# ============================================================
# CUSTOMER MEMORY
# ============================================================

def get_customer_memory(
    phone: str,
) -> Dict[str, Any]:

    phone = normalize_customer_phone(phone)

    if not phone:
        return {}

    return CUSTOMER_MEMORY.get(
        phone,
        {},
    ).copy()


def update_customer_memory(
    phone: str,
    new_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:

    phone = normalize_customer_phone(phone)

    if not phone:
        return {}

    old_memory = get_customer_memory(phone)

    updated_memory = merge_customer_memory(
        old_memory,
        new_data or {},
    )

    CUSTOMER_MEMORY[phone] = updated_memory

    return updated_memory


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

        from app.services.ai_agent import (
            extract_demo_datetime,
        )

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

    sender_phone = normalize_customer_phone(
        sender_phone
    )

    if not sender_phone:
        return None

    if not lead_data:
        return None

    lead = (
        db.query(Lead)
        .filter(
            Lead.phone == sender_phone
        )
        .first()
    )

    if not lead:

        lead = Lead(
            phone=sender_phone,
            name=lead_data.get("name"),
            email=lead_data.get("email"),
            company=lead_data.get("company"),
            status="new",
            source="whatsapp",
        )

        db.add(lead)

    else:

        if lead_data.get("name"):
            lead.name = lead_data["name"]

        if lead_data.get("email"):
            lead.email = lead_data["email"]

        if lead_data.get("company"):
            lead.company = lead_data["company"]

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
        f"{META_GRAPH_VERSION}/"
        f"{META_PHONE_NUMBER_ID}/messages"
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

        customer_memory = (
            process_customer_memory(
                sender_phone,
                user_message,
            )
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
        # 6. UPDATE LEAD
        # ====================================================

        if is_potential_lead(
            user_message
        ):

            try:

                update_or_create_lead(
                    db=db,
                    sender_phone=sender_phone,
                    lead_data=lead_data,
                )

            except Exception as exc:

                logger.exception(
                    "Lead update failed: %s",
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
        "green_api": False,
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

    normalized_phone = (
        normalize_customer_phone(
            phone
        )
    )

    if normalized_phone in CUSTOMER_MEMORY:

        del CUSTOMER_MEMORY[
            normalized_phone
        ]

        return {
            "status": "cleared",
            "phone": normalized_phone,
        }

    return {
        "status": "not_found",
        "phone": normalized_phone,
    }