# ============================================================
# XYTRALYN CHAT ROUTE - PART 1
# Imports + Config + Memory + DB Helpers
# + GREEN-API Sender + GREEN-API Parser
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
# GREEN-API CONFIG
# ============================================================

GREEN_API_INSTANCE_ID = os.getenv(
    "GREEN_API_INSTANCE_ID"
)

GREEN_API_TOKEN = os.getenv(
    "GREEN_API_TOKEN"
)


# ============================================================
# TWILIO CONFIG
# ============================================================

TWILIO_ACCOUNT_SID = os.getenv(
    "TWILIO_ACCOUNT_SID"
)

TWILIO_AUTH_TOKEN = os.getenv(
    "TWILIO_AUTH_TOKEN"
)

TWILIO_WHATSAPP_FROM = os.getenv(
    "TWILIO_WHATSAPP_FROM"
)


# ============================================================
# CUSTOMER MEMORY
# ============================================================

CUSTOMER_MEMORY: Dict[str, Dict[str, Any]] = {}


def normalize_customer_phone(
    phone: str,
) -> str:
    """
    Normalize Indian WhatsApp phone number.

    Examples:

        +91 98765 43210
        919876543210
        9876543210

    Result:

        919876543210
    """

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


def get_customer_memory(
    phone: str,
) -> Dict[str, Any]:
    """
    Get memory for one customer only.
    """

    phone = normalize_customer_phone(
        phone
    )

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
    """
    Merge latest confirmed customer information.
    """

    phone = normalize_customer_phone(
        phone
    )

    if not phone:
        return {}

    old_memory = get_customer_memory(
        phone
    )

    updated_memory = merge_customer_memory(
        old_memory,
        new_data or {},
    )

    CUSTOMER_MEMORY[phone] = (
        updated_memory
    )

    return updated_memory


# ============================================================
# CHAT HISTORY
# ============================================================

def build_chat_history(
    db,
    sender_phone: str,
    limit: int = HISTORY_LIMIT,
) -> List[Dict[str, str]]:
    """
    Build recent conversation history
    for one customer only.
    """

    sender_phone = normalize_customer_phone(
        sender_phone
    )

    if not sender_phone:
        return []

    messages = (
        db.query(Message)
        .filter(
            Message.sender_phone
            == sender_phone
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

        elif sender_type == "user":
            role = "user"

        else:
            role = "user"

        history.append(
            {
                "role": role,
                "content": str(
                    content
                ).strip(),
            }
        )

    return normalize_history(
        history
    )


# ============================================================
# CUSTOMER MEMORY PROCESSING
# ============================================================

def process_customer_memory(
    sender_phone: str,
    user_message: str,
) -> Dict[str, Any]:
    """
    Extract information only from the
    current customer message.
    """

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

    return update_customer_memory(
        sender_phone,
        new_data,
    )


def get_customer_context(
    sender_phone: str,
) -> str:
    """
    Return confirmed customer context
    for the AI agent.
    """

    memory = get_customer_memory(
        sender_phone
    )

    return memory_to_text(
        memory
    )


# ============================================================
# LEAD DATABASE
# ============================================================

def update_or_create_lead(
    db,
    sender_phone: str,
    lead_data: Optional[Dict[str, Any]],
) -> Optional[Lead]:
    """
    Create or update lead using
    customer phone number.
    """

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
            Lead.phone
            == sender_phone
        )
        .first()
    )

    if not lead:

        lead = Lead(
            phone=sender_phone,
            name=lead_data.get(
                "name"
            ),
            email=lead_data.get(
                "email"
            ),
            company=lead_data.get(
                "company"
            ),
            status="new",
            source="whatsapp",
        )

        db.add(lead)

    else:

        if lead_data.get("name"):
            lead.name = lead_data[
                "name"
            ]

        if lead_data.get("email"):
            lead.email = lead_data[
                "email"
            ]

        if lead_data.get("company"):
            lead.company = lead_data[
                "company"
            ]

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
    """
    Save one message.

    sender_type:
        user
        assistant
    """

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

    if hasattr(
        message,
        "sender_type",
    ):
        message.sender_type = (
            sender_type
        )

    db.add(message)
    db.commit()
    db.refresh(message)

    return message


# ============================================================
# GREEN-API SEND MESSAGE
# ============================================================

async def send_whatsapp_message(
    recipient_phone: str,
    message_text: str,
) -> bool:
    """
    Send WhatsApp message through GREEN-API.
    """

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

    phone_digits = (
        normalize_customer_phone(
            recipient_phone
        )
    )

    if not phone_digits:
        logger.error(
            "Invalid recipient phone: %s",
            recipient_phone,
        )
        return False

    chat_id = (
        f"{phone_digits}@c.us"
    )

    url = (
        "https://api.green-api.com/"
        f"waInstance{GREEN_API_INSTANCE_ID}/"
        f"sendMessage/{GREEN_API_TOKEN}"
    )

    payload = {
        "chatId": chat_id,
        "message": message_text,
    }

    headers = {
        "Content-Type": "application/json",
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

            logger.info(
                "GREEN-API message sent successfully | chat=%s",
                chat_id,
            )

            return True

        logger.error(
            "GREEN-API send error | "
            "status=%s | response=%s",
            response.status_code,
            response.text,
        )

        return False

    except Exception as exc:

        logger.exception(
            "GREEN-API WhatsApp send failed: %s",
            exc,
        )

        return False


# ============================================================
# GREEN-API INCOMING MESSAGE PARSER
# ============================================================

def parse_whatsapp_message(
    body: Dict[str, Any],
) -> Optional[Dict[str, str]]:
    """
    Parse incoming GREEN-API WhatsApp messages.

    Supports:
    - textMessage
    - extendedTextMessage
    """

    try:

        # ----------------------------------------------------
        # 1. Only process incoming messages
        # ----------------------------------------------------
        if body.get("typeWebhook") != "incomingMessageReceived":
            return None

        # ----------------------------------------------------
        # 2. Message ID
        # ----------------------------------------------------
        message_id = body.get(
            "idMessage",
            "",
        )

        # ----------------------------------------------------
        # 3. Sender data
        # ----------------------------------------------------
        sender_data = body.get(
            "senderData",
            {},
        ) or {}

        chat_id = sender_data.get(
            "chatId",
            "",
        )

        if not chat_id:
            return None

        # ----------------------------------------------------
        # 4. Ignore WhatsApp groups
        # ----------------------------------------------------
        if "@g.us" in chat_id:
            return None

        # ----------------------------------------------------
        # 5. Message data
        # ----------------------------------------------------
        message_data = body.get(
            "messageData",
            {},
        ) or {}

        message_type = message_data.get(
            "typeMessage",
            "",
        )

        # ----------------------------------------------------
        # 6. Extract message text
        # ----------------------------------------------------
        message_text = ""

        # Normal text message
        if message_type == "textMessage":

            text_data = message_data.get(
                "textMessageData",
                {},
            ) or {}

            message_text = text_data.get(
                "textMessage",
                "",
            )

        # Extended text message
        elif message_type == "extendedTextMessage":

            extended_data = message_data.get(
                "extendedTextMessageData",
                {},
            ) or {}

            message_text = extended_data.get(
                "text",
                "",
            )

        # Unsupported message type
        else:

            logger.info(
                "GREEN-API message ignored | type=%s",
                message_type,
            )

            return None

        # ----------------------------------------------------
        # 7. Validate message text
        # ----------------------------------------------------
        if not message_text:
            return None

        message_text = str(
            message_text
        ).strip()

        if not message_text:
            return None

        # ----------------------------------------------------
        # 8. Extract sender phone
        # ----------------------------------------------------
        sender_phone = chat_id.split(
            "@",
            1,
        )[0]

        sender_phone = normalize_customer_phone(
            sender_phone
        )

        if not sender_phone:
            return None

        # ----------------------------------------------------
        # 9. Return normalized message
        # ----------------------------------------------------
        logger.info(
            "GREEN-API incoming message | type=%s | phone=%s",
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

    except Exception as exc:

        logger.exception(
            "Failed to parse GREEN-API message: %s",
            exc,
        )

        return None
    # ============================================================
# XYTRALYN CHAT ROUTE - PART 2
# Duplicate Protection
# Customer Handler
# GREEN-API Webhook
# TWILIO Webhook
# Health + Debug
# ============================================================


# ============================================================
# DUPLICATE MESSAGE PROTECTION
# ============================================================

PROCESSED_MESSAGE_IDS = set()


def is_duplicate_message(
    message_id: str,
) -> bool:
    """
    Prevent the same WhatsApp message
    from being processed more than once.
    """

    if not message_id:
        return False

    if message_id in PROCESSED_MESSAGE_IDS:
        return True

    PROCESSED_MESSAGE_IDS.add(
        message_id
    )

    # Keep memory bounded.
    if len(PROCESSED_MESSAGE_IDS) > 5000:

        # Simple cleanup.
        PROCESSED_MESSAGE_IDS.clear()

        # Keep current message marked as processed.
        PROCESSED_MESSAGE_IDS.add(
            message_id
        )

    return False


# ============================================================
# CUSTOMER MESSAGE HANDLER
# ============================================================

async def handle_customer_message(
    sender_phone: str,
    user_message: str,
) -> Optional[str]:
    """
    Complete customer -> AI -> response flow.

    Flow:

        Customer
            ↓
        Customer Memory
            ↓
        Chat History
            ↓
        Lead Detection
            ↓
        AI Agent
            ↓
        Save Assistant Reply
            ↓
        Return Reply
    """

    sender_phone = normalize_customer_phone(
        sender_phone
    )

    user_message = (
        user_message or ""
    ).strip()

    if not sender_phone:

        logger.error(
            "Customer phone is missing."
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
            db=db,
            sender_phone=sender_phone,
            limit=HISTORY_LIMIT,
        )

        # ====================================================
        # 2. UPDATE CUSTOMER MEMORY
        # ====================================================

        customer_memory = (
            process_customer_memory(
                sender_phone=sender_phone,
                user_message=user_message,
            )
        )

        customer_context = (
            memory_to_text(
                customer_memory
            )
        )

        # ====================================================
        # 3. DETECT AGENT
        # ====================================================

        agent_name = detect_agent(
            user_message
        )

        if not agent_name:
            agent_name = "sales"

        # ====================================================
        # 4. EXTRACT LEAD INFORMATION
        # ====================================================

        lead_data = extract_lead_info(
            user_message
        )

        # ====================================================
        # 5. SAVE CUSTOMER MESSAGE
        # ====================================================

        save_message(
            db=db,
            sender_phone=sender_phone,
            content=user_message,
            agent_name=agent_name,
            sender_type="user",
        )

        # ====================================================
        # 6. CREATE / UPDATE LEAD
        # ====================================================

        has_lead_data = any(
            value
            for value in lead_data.values()
            if value
        )

        if (
            is_potential_lead(
                user_message
            )
            or has_lead_data
        ):

            update_or_create_lead(
                db=db,
                sender_phone=sender_phone,
                lead_data=lead_data,
            )

        # ====================================================
        # 7. GENERATE AI RESPONSE
        # ====================================================

        reply = await generate_agent_reply(
            user_message=user_message,
            history=history,
            agent_name=agent_name,
            business_name=BUSINESS_NAME,
            customer_memory=customer_context,
        )

        if not reply:

            logger.error(
                "AI agent returned empty reply."
            )

            return None

        reply = str(
            reply
        ).strip()

        if not reply:
            return None

        # ====================================================
        # 8. SAVE AI RESPONSE
        # ====================================================

        save_message(
            db=db,
            sender_phone=sender_phone,
            content=reply,
            agent_name=agent_name,
            sender_type="assistant",
        )

        return reply

    except Exception as exc:

        logger.exception(
            "Customer message handling failed: %s",
            exc,
        )

        return None

    finally:

        db.close()


# ============================================================
# GREEN-API WEBHOOK
# ============================================================

@router.post("/webhook")
async def whatsapp_webhook(
    request: Request,
):
    """
    GREEN-API incoming WhatsApp webhook.

    Diagnostic version:
    Tracks exactly where the message flow stops.
    """

    try:

        # ====================================================
        # 1. WEBHOOK RECEIVED
        # ====================================================

        logger.warning(
            "XYTRALYN DEBUG 1 | GREEN-API webhook received"
        )

        # ====================================================
        # 2. READ JSON
        # ====================================================

        body = await request.json()

        logger.warning(
            "XYTRALYN DEBUG PAYLOAD KEYS | keys=%s",
            list(body.keys()) if isinstance(body, dict) else type(body).__name__,
        )

        logger.warning(
            "XYTRALYN DEBUG BODY TYPE | type=%s",
            type(body).__name__,
        )

        logger.warning(
            "XYTRALYN DEBUG 2 | JSON received | webhook_type=%s",
            body.get("typeWebhook"),
        )

        # ====================================================
        # 3. CHECK MESSAGE TYPE
        # ====================================================

        message_data = body.get(
            "messageData",
            {},
        ) or {}

        logger.warning(
            "XYTRALYN DEBUG 3 | message_type=%s",
            message_data.get("typeMessage"),
        )

        # ====================================================
        # 4. PARSE MESSAGE
        # ====================================================

        parsed = parse_whatsapp_message(
            body
        )

        if not parsed:

            logger.warning(
                "XYTRALYN DEBUG 4 | PARSER RETURNED NONE"
            )

            return {
                "status": "ignored",
                "reason": "parser_returned_none",
            }

        logger.warning(
            "XYTRALYN DEBUG 4 | MESSAGE PARSED SUCCESSFULLY"
        )

        # ====================================================
        # 5. EXTRACT DATA
        # ====================================================

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

        logger.warning(
            "XYTRALYN DEBUG 5 | sender=%s | message_length=%s",
            sender_phone,
            len(user_message),
        )

        if not sender_phone:

            logger.warning(
                "XYTRALYN DEBUG 5A | INVALID SENDER"
            )

            return {
                "status": "invalid_sender"
            }

        if not user_message:

            logger.warning(
                "XYTRALYN DEBUG 5B | EMPTY MESSAGE"
            )

            return {
                "status": "invalid_message"
            }

        # ====================================================
        # 6. DUPLICATE CHECK
        # ====================================================

        if message_id:

            if is_duplicate_message(
                message_id
            ):

                logger.warning(
                    "XYTRALYN DEBUG 6 | DUPLICATE MESSAGE"
                )

                return {
                    "status": "duplicate_ignored"
                }

        logger.warning(
            "XYTRALYN DEBUG 6 | DUPLICATE CHECK PASSED"
        )

        # ====================================================
        # 7. AI PROCESSING
        # ====================================================

        logger.warning(
            "XYTRALYN DEBUG 7 | STARTING AI PROCESSING"
        )

        reply = await handle_customer_message(
            sender_phone=sender_phone,
            user_message=user_message,
        )

        # ====================================================
        # 8. AI REPLY CHECK
        # ====================================================

        if not reply:

            logger.error(
                "XYTRALYN DEBUG 8 | AI RETURNED EMPTY REPLY"
            )

            return {
                "status": "no_reply"
            }

        logger.warning(
            "XYTRALYN DEBUG 8 | AI REPLY GENERATED | length=%s",
            len(str(reply)),
        )

        # ====================================================
        # 9. SEND THROUGH GREEN API
        # ====================================================

        logger.warning(
            "XYTRALYN DEBUG 9 | SENDING REPLY THROUGH GREEN-API"
        )

        sent = await send_whatsapp_message(
            recipient_phone=sender_phone,
            message_text=reply,
        )

        # ====================================================
        # 10. SEND RESULT
        # ====================================================

        if not sent:

            logger.error(
                "XYTRALYN DEBUG 10 | GREEN-API SEND FAILED"
            )

            return {
                "status": "reply_generated",
                "message_sent": False,
            }

        logger.warning(
            "XYTRALYN DEBUG 10 | GREEN-API SEND SUCCESS"
        )

        # ====================================================
        # 11. SUCCESS
        # ====================================================

        logger.warning(
            "XYTRALYN DEBUG 11 | XYTRALYN AI FLOW COMPLETED"
        )

        return {
            "status": "success",
            "message_sent": True,
        }

    except Exception as exc:

        logger.exception(
            "XYTRALYN DEBUG ERROR | webhook processing failed: %s",
            exc,
        )

        # Temporary diagnostic response
        return PlainTextResponse(
            "Webhook processing failed",
            status_code=500,
        )

# ============================================================
# TWILIO WHATSAPP WEBHOOK
# ============================================================

@router.post("/incoming")
async def twilio_whatsapp_webhook(
    request: Request,
):
    """
    Existing Twilio WhatsApp webhook.

    IMPORTANT:
    Twilio is preserved as an optional/secondary flow.

    GREEN-API is the primary WhatsApp flow
    through /webhook.
    """

    try:

        # ----------------------------------------------------
        # Twilio sends form data
        # ----------------------------------------------------

        form = await request.form()

        sender = form.get(
            "From",
            "",
        )

        body = form.get(
            "Body",
            "",
        )

        sender = str(
            sender or ""
        ).strip()

        body = str(
            body or ""
        ).strip()

        # ----------------------------------------------------
        # Remove Twilio WhatsApp prefix
        #
        # whatsapp:+919876543210
        # ->
        # +919876543210
        # ----------------------------------------------------

        if sender.startswith(
            "whatsapp:"
        ):

            sender = sender[
                len("whatsapp:"):
            ]

        sender_phone = (
            normalize_customer_phone(
                sender
            )
        )

        if not sender_phone:
            return PlainTextResponse(
                "Invalid sender",
                status_code=400,
            )

        if not body:
            return PlainTextResponse(
                "Empty message",
                status_code=400,
            )

        # ----------------------------------------------------
        # Process through same AI engine
        # ----------------------------------------------------

        reply = await handle_customer_message(
            sender_phone=sender_phone,
            user_message=body,
        )

        if not reply:
            reply = (
                "Dhanyavaad! "
                "Hamari team aapko jald "
                "contact karegi."
            )

        # ----------------------------------------------------
        # Twilio expects TwiML
        # ----------------------------------------------------

        safe_reply = (
            str(reply)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f"<Message>{safe_reply}</Message>"
            "</Response>"
        )

        return PlainTextResponse(
            content=twiml,
            media_type="application/xml",
        )

    except Exception as exc:

        logger.exception(
            "Twilio WhatsApp webhook failed: %s",
            exc,
        )

        return PlainTextResponse(
            "Internal server error",
            status_code=500,
        )


# ============================================================
# HEALTH CHECK
# ============================================================

@router.get("/health")
async def chat_health():
    """
    Health check for chat service.
    """

    return {
        "status": "ok",
        "service": "Xytralyn WhatsApp AI",
        "green_api": bool(
            GREEN_API_INSTANCE_ID
            and GREEN_API_TOKEN
        ),
        "twilio": bool(
            TWILIO_ACCOUNT_SID
            and TWILIO_AUTH_TOKEN
            and TWILIO_WHATSAPP_FROM
        ),
    }


# ============================================================
# DEBUG CUSTOMER MEMORY
# ============================================================

@router.get(
    "/debug/customer/{phone}"
)
async def debug_customer(
    phone: str,
):
    """
    Development-only customer memory check.

    Remove or protect this endpoint before
    production if it exposes sensitive information.
    """

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

def clear_customer_memory(
    sender_phone: str,
) -> None:
    """
    Clear temporary in-process memory
    for one customer.
    """

    sender_phone = normalize_customer_phone(
        sender_phone
    )

    if sender_phone:

        CUSTOMER_MEMORY.pop(
            sender_phone,
            None,
        )