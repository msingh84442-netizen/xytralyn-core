# ============================================================
# CHAT ROUTE - PART 1
# Imports + Constants
# ============================================================

import os
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

META_ACCESS_TOKEN = os.getenv(
    "META_ACCESS_TOKEN"
)

META_PHONE_NUMBER_ID = os.getenv(
    "META_PHONE_NUMBER_ID"
)

META_VERIFY_TOKEN = os.getenv(
    "META_VERIFY_TOKEN"
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

# Temporary in-process memory.
#
# Key:
#     customer phone number
#
# Value:
#     structured customer profile
#
# IMPORTANT:
# This is customer-specific.
# Customer A's memory will never be used for Customer B.
#
# Later we can move this to PostgreSQL/Redis for production.
#
CUSTOMER_MEMORY: Dict[str, Dict[str, Any]] = {}


def get_customer_memory(
    phone: str,
) -> Dict[str, Any]:
    """
    Get memory for ONE customer only.
    """

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
    Merge latest customer information into
    this customer's existing memory.
    """

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
# CHAT HISTORY + CUSTOMER MEMORY - PART 2
# ============================================================

def build_chat_history(
    db,
    sender_phone: str,
    limit: int = HISTORY_LIMIT,
) -> List[Dict[str, str]]:
    """
    Build recent conversation history for ONE customer.

    Only this phone number's messages are loaded.
    """

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

        # ----------------------------------------------------
        # Determine message role
        # ----------------------------------------------------

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
            # Existing database schema may not have
            # sender_type. In that case use a safe fallback.
            role = "user"

        history.append(
            {
                "role": role,
                "content": str(content).strip(),
            }
        )

    return normalize_history(
        history
    )


def process_customer_memory(
    sender_phone: str,
    user_message: str,
) -> Dict[str, Any]:
    """
    Extract information ONLY from the current
    customer message and merge it into that customer's
    existing memory.
    """

    if not sender_phone:
        return {}

    if not user_message:
        return get_customer_memory(
            sender_phone
        )

    # --------------------------------------------------------
    # Extract ONLY from customer message
    # --------------------------------------------------------

    new_data = extract_lead_info(
        user_message
    )

    # --------------------------------------------------------
    # Extract demo information
    # --------------------------------------------------------

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
        new_data["demo_date"] = (
            demo_date
        )

    if demo_time:
        new_data["demo_time"] = (
            demo_time
        )

    if demo_datetime:
        new_data["demo_datetime"] = (
            demo_datetime
        )

    # --------------------------------------------------------
    # Merge with existing customer memory
    # --------------------------------------------------------

    return update_customer_memory(
        sender_phone,
        new_data,
    )


def get_customer_context(
    sender_phone: str,
) -> str:
    """
    Return compact confirmed customer context
    for the AI agent.
    """

    memory = get_customer_memory(
        sender_phone
    )

    return memory_to_text(
        memory
    )
# ============================================================
# LEAD + MESSAGE DATABASE HELPERS - PART 3
# ============================================================

def update_or_create_lead(
    db,
    sender_phone: str,
    lead_data: Optional[Dict[str, Any]],
) -> Optional[Lead]:
    """
    Create or update a lead using the customer's phone number.
    """

    if not sender_phone:
        return None

    if not lead_data:
        return None

    # --------------------------------------------------------
    # Find existing lead
    # --------------------------------------------------------

    lead = (
        db.query(Lead)
        .filter(
            Lead.phone
            == sender_phone
        )
        .first()
    )

    # --------------------------------------------------------
    # Create new lead
    # --------------------------------------------------------

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

        # ----------------------------------------------------
        # Update ONLY fields actually provided
        # by the customer.
        # ----------------------------------------------------

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
        user      -> customer message
        assistant -> AI response
    """

    if not sender_phone:
        return None

    if not content:
        return None

    message = Message(
        sender_phone=sender_phone,
        content=content,
        agent_used=agent_name,
    )

    # --------------------------------------------------------
    # If your Message model contains sender_type,
    # save it.
    #
    # getattr is used so the code doesn't crash if the
    # existing SQLAlchemy model does not yet have this field.
    # --------------------------------------------------------

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
# META WHATSAPP HELPERS - PART 4
# ============================================================

async def send_meta_whatsapp_message(
    recipient_phone: str,
    message_text: str,
) -> bool:
    """
    Send a WhatsApp message through Meta Cloud API.
    """

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
        return False

    if not message_text:
        return False

    url = (
        "https://graph.facebook.com/v23.0/"
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
        "to": recipient_phone,
        "type": "text",
        "text": {
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

            if response.is_success:
                return True

            logger.error(
                "Meta WhatsApp API error: %s",
                response.text,
            )

            return False

    except Exception as exc:

        logger.exception(
            "Failed to send Meta WhatsApp message: %s",
            exc,
        )

        return False


def parse_meta_message(
    body: Dict[str, Any],
) -> Optional[Dict[str, str]]:
    """
    Extract sender phone and text from Meta webhook payload.
    """

    try:

        entries = body.get(
            "entry",
            [],
        )

        if not entries:
            return None

        changes = entries[0].get(
            "changes",
            [],
        )

        if not changes:
            return None

        value = changes[0].get(
            "value",
            {},
        )

        messages = value.get(
            "messages",
            [],
        )

        if not messages:
            return None

        message = messages[0]

        sender_phone = (
            message.get(
                "from"
            )
        )

        message_type = (
            message.get(
                "type"
            )
        )

        # ----------------------------------------------------
        # Currently process text messages only
        # ----------------------------------------------------

        if message_type != "text":
            return None

        text_data = message.get(
            "text",
            {},
        )

        message_text = (
            text_data.get(
                "body"
            )
        )

        if not sender_phone:
            return None

        if not message_text:
            return None

        return {
            "sender_phone": (
                sender_phone
            ),
            "message_text": (
                message_text.strip()
            ),
        }

    except Exception as exc:

        logger.exception(
            "Failed to parse Meta message: %s",
            exc,
        )

        return None
    # ============================================================
# MAIN CUSTOMER MESSAGE FLOW - PART 5
# ============================================================

async def handle_customer_message(
    sender_phone: str,
    user_message: str,
) -> Optional[str]:
    """
    Complete customer conversation flow.

    Flow:

    Customer message
          ↓
    Customer memory update
          ↓
    Lead update
          ↓
    Recent history
          ↓
    AI response
          ↓
    Save AI response
          ↓
    Return response
    """

    if not sender_phone:
        return None

    if not user_message:
        return None

    db = SessionLocal()

    try:

        # ====================================================
        # 1. CUSTOMER MEMORY
        # ====================================================

        customer_memory = (
            process_customer_memory(
                sender_phone,
                user_message,
            )
        )

        logger.info(
            "Customer memory updated for %s: %s",
            sender_phone,
            customer_memory,
        )

        # ====================================================
        # 2. LEAD INFORMATION
        # ====================================================

        lead_data = extract_lead_info(
            user_message
        )

        if is_potential_lead(
            user_message
        ):
            try:

                update_or_create_lead(
                    db,
                    sender_phone,
                    lead_data,
                )

            except Exception as exc:

                logger.exception(
                    "Lead update failed: %s",
                    exc,
                )

                db.rollback()

        # ====================================================
        # 3. RECENT CONVERSATION HISTORY
        # ====================================================

        history = build_chat_history(
            db,
            sender_phone,
            HISTORY_LIMIT,
        )

        # ====================================================
        # 4. DETECT AGENT
        # ====================================================

        agent_name = detect_agent(
            user_message
        )

        # ====================================================
        # 5. CUSTOMER MEMORY → AI CONTEXT
        # ====================================================

        customer_context = (
            memory_to_text(
                customer_memory
            )
        )

        # ====================================================
        # 6. GENERATE AI RESPONSE
        # ====================================================

        reply = await generate_agent_reply(
            user_message=user_message,
            history=history,
            agent_name=agent_name,
            business_name=BUSINESS_NAME,
            customer_memory=customer_context,
        )

        if not reply:

            reply = (
                "Thoda technical issue aa gaya hai. "
                "Ek baar phir message kar dijiye."
            )

        # ====================================================
        # 7. SAVE CUSTOMER MESSAGE
        # ====================================================

        save_message(
            db=db,
            sender_phone=sender_phone,
            content=user_message,
            agent_name=agent_name,
            sender_type="user",
        )

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

        db.rollback()

        return (
            "Sorry, thoda technical issue aa gaya hai. "
            "Please ek baar phir message kar dijiye."
        )

    finally:

        db.close()
        # ============================================================
# META WHATSAPP WEBHOOK - PART 6 FINAL
# ============================================================

@router.get("/webhook")
async def verify_meta_webhook(
    request: Request,
):
    """
    Meta WhatsApp webhook verification.
    """

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

    if (
        mode == "subscribe"
        and verify_token == META_VERIFY_TOKEN
    ):
        return PlainTextResponse(
            challenge or ""
        )

    return PlainTextResponse(
        "Verification failed",
        status_code=403,
    )


@router.post("/webhook")
async def meta_webhook(
    request: Request,
):
    """
    Receive incoming WhatsApp messages from Meta.

    Flow:

        Meta WhatsApp
              ↓
        Parse message
              ↓
        Duplicate check
              ↓
        Customer memory
              ↓
        AI response
              ↓
        Save messages
              ↓
        Send WhatsApp reply
    """

    try:

        # ====================================================
        # 1. READ META WEBHOOK
        # ====================================================

        body = await request.json()

        parsed = parse_meta_message(
            body
        )

        # ----------------------------------------------------
        # Ignore:
        # - status updates
        # - unsupported message types
        # - empty messages
        # ----------------------------------------------------

        if not parsed:

            return {
                "status": "ignored"
            }

        # ====================================================
        # 2. GET MESSAGE ID
        # ====================================================

        message_id = parsed.get(
            "message_id"
        )

        # ====================================================
        # 3. DUPLICATE MESSAGE PROTECTION
        # ====================================================

        if message_id:

            if is_duplicate_message(
                message_id
            ):

                logger.info(
                    "Duplicate Meta message ignored: %s",
                    message_id,
                )

                return {
                    "status": "duplicate_ignored"
                }

        # ====================================================
        # 4. GET CUSTOMER + MESSAGE
        # ====================================================

        sender_phone = parsed[
            "sender_phone"
        ]

        user_message = parsed[
            "message_text"
        ]

        logger.info(
            "Incoming Meta WhatsApp message | "
            "phone=%s | message=%s",
            sender_phone,
            user_message,
        )

        # ====================================================
        # 5. PROCESS CUSTOMER MESSAGE
        # ====================================================

        reply = await handle_customer_message(
            sender_phone=sender_phone,
            user_message=user_message,
        )

        # ====================================================
        # 6. NO RESPONSE
        # ====================================================

        if not reply:

            logger.warning(
                "No AI reply generated for %s",
                sender_phone,
            )

            return {
                "status": "no_reply"
            }

        # ====================================================
        # 7. SEND AI RESPONSE TO WHATSAPP
        # ====================================================

        sent = await send_meta_whatsapp_message(
            recipient_phone=sender_phone,
            message_text=reply,
        )

        # ====================================================
        # 8. MESSAGE SEND FAILED
        # ====================================================

        if not sent:

            logger.error(
                "Failed to send Meta WhatsApp reply "
                "to %s",
                sender_phone,
            )

            return {
                "status": "reply_generated",
                "message_sent": False,
            }

        # ====================================================
        # 9. SUCCESS
        # ====================================================

        logger.info(
            "Meta WhatsApp reply sent successfully "
            "to %s",
            sender_phone,
        )

        return {
            "status": "success",
            "message_sent": True,
        }

    except Exception as exc:

        logger.exception(
            "Meta WhatsApp webhook error: %s",
            exc,
        )

        # ----------------------------------------------------
        # Return a response instead of crashing the webhook.
        # ----------------------------------------------------

        return {
            "status": "error"
        }
    # ============================================================
# TWILIO WHATSAPP WEBHOOK - PART 7
# ============================================================

from fastapi.responses import Response


@router.post("/incoming")
async def twilio_incoming(
    request: Request,
):
    """
    Twilio WhatsApp webhook.

    Twilio se incoming message receive karke
    same customer-memory + AI flow use karta hai.
    """

    try:

        form = await request.form()

        sender = str(
            form.get(
                "From",
                "",
            )
        ).strip()

        user_message = str(
            form.get(
                "Body",
                "",
            )
        ).strip()

        if not sender:
            return Response(
                content="",
                media_type="text/xml",
            )

        if not user_message:
            return Response(
                content="",
                media_type="text/xml",
            )

        # ----------------------------------------------------
        # Twilio sender format:
        #
        # whatsapp:+919876543210
        #
        # Our memory system needs a stable customer key.
        # ----------------------------------------------------

        sender_phone = sender

        if sender_phone.startswith(
            "whatsapp:"
        ):
            sender_phone = (
                sender_phone[
                    len("whatsapp:") :
                ]
            )

        logger.info(
            "Incoming Twilio message from %s: %s",
            sender_phone,
            user_message,
        )

        # ----------------------------------------------------
        # Generate AI response
        # ----------------------------------------------------

        reply = await handle_customer_message(
            sender_phone=sender_phone,
            user_message=user_message,
        )

        if not reply:
            reply = (
                "Sorry, thoda technical issue aa gaya hai."
            )

        # ----------------------------------------------------
        # Twilio XML response
        # ----------------------------------------------------

        escaped_reply = (
            reply
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f"<Message>{escaped_reply}</Message>"
            "</Response>"
        )

        return Response(
            content=twiml,
            media_type="text/xml",
        )

    except Exception as exc:

        logger.exception(
            "Twilio webhook error: %s",
            exc,
        )

        return Response(
            content=(
                '<?xml version="1.0" encoding="UTF-8"?>'
                "<Response></Response>"
            ),
            media_type="text/xml",
        )
    # ============================================================
# FINAL CHAT ROUTE HELPERS - PART 8
# ============================================================

def clear_customer_memory(
    sender_phone: str,
) -> None:
    """
    Clear only one customer's temporary memory.
    """

    if not sender_phone:
        return

    CUSTOMER_MEMORY.pop(
        sender_phone,
        None,
    )


def get_customer_debug_info(
    sender_phone: str,
) -> Dict[str, Any]:
    """
    Useful for local debugging/testing.
    """

    if not sender_phone:
        return {
            "phone": None,
            "memory": {},
        }

    return {
        "phone": sender_phone,
        "memory": get_customer_memory(
            sender_phone
        ),
    }
# ============================================================
# DUPLICATE MESSAGE PROTECTION - PART 10
# ============================================================

PROCESSED_MESSAGE_IDS = set()


def is_duplicate_message(
    message_id: Optional[str],
) -> bool:
    """
    Check whether a Meta/Twilio message was already processed.

    This prevents duplicate AI replies when a webhook is
    delivered more than once.
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

        oldest_ids = list(
            PROCESSED_MESSAGE_IDS
        )[:1000]

        for old_id in oldest_ids:

            PROCESSED_MESSAGE_IDS.discard(
                old_id
            )

    return False
# ============================================================
# META MESSAGE PARSER - PART 10A FINAL
# ============================================================

def parse_meta_message(
    body: Dict[str, Any],
) -> Optional[Dict[str, str]]:
    """
    Parse incoming Meta WhatsApp webhook payload.

    Extracts:

        message_id
        sender_phone
        message_text

    IMPORTANT:
        message_id is used by the duplicate protection
        system to prevent processing the same WhatsApp
        message more than once.
    """

    try:

        # ====================================================
        # 1. ENTRY
        # ====================================================

        entries = body.get(
            "entry",
            [],
        )

        if not entries:
            return None

        # ====================================================
        # 2. CHANGES
        # ====================================================

        changes = entries[0].get(
            "changes",
            [],
        )

        if not changes:
            return None

        # ====================================================
        # 3. VALUE
        # ====================================================

        value = changes[0].get(
            "value",
            {},
        )

        # ====================================================
        # 4. MESSAGES
        # ====================================================

        messages = value.get(
            "messages",
            [],
        )

        # Status updates normally don't contain
        # messages, so safely ignore them.

        if not messages:
            return None

        # ====================================================
        # 5. FIRST MESSAGE
        # ====================================================

        message = messages[0]

        # ====================================================
        # 6. UNIQUE MESSAGE ID
        # ====================================================

        message_id = (
            message.get(
                "id"
            )
        )

        # ====================================================
        # 7. CUSTOMER PHONE
        # ====================================================

        sender_phone = (
            message.get(
                "from"
            )
        )

        # ====================================================
        # 8. MESSAGE TYPE
        # ====================================================

        message_type = (
            message.get(
                "type"
            )
        )

        # ----------------------------------------------------
        # Currently process text messages only.
        # ----------------------------------------------------

        if message_type != "text":
            return None

        # ====================================================
        # 9. TEXT DATA
        # ====================================================

        text_data = message.get(
            "text",
            {},
        )

        message_text = (
            text_data.get(
                "body"
            )
        )

        # ====================================================
        # 10. VALIDATION
        # ====================================================

        if not sender_phone:
            return None

        if not message_text:
            return None

        message_text = (
            str(message_text)
            .strip()
        )

        if not message_text:
            return None

        # ====================================================
        # 11. RETURN PARSED MESSAGE
        # ====================================================

        return {
            "message_id": (
                message_id or ""
            ),
            "sender_phone": (
                sender_phone
            ),
            "message_text": (
                message_text
            ),
        }

    except Exception as exc:

        logger.exception(
            "Failed to parse Meta WhatsApp message: %s",
            exc,
        )

        return None