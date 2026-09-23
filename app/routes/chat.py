import os
import logging
from typing import List, Dict, Any, Optional, Tuple

import requests
from fastapi import (
    APIRouter,
    Depends,
    Response,
    Request,
    Query,
    HTTPException,
    BackgroundTasks,
)
from sqlalchemy.orm import Session
from twilio.twiml.messaging_response import MessagingResponse

from app.database import get_db, SessionLocal
from app.models import Lead, Message
from app.services.ai_agent import (
    extract_lead_info,
    is_potential_lead,
    detect_agent,
    generate_agent_reply,
)
from app.services.notifier import send_admin_alert


router = APIRouter(tags=["Chat"])

logger = logging.getLogger(__name__)


VERIFY_TOKEN = os.getenv(
    "WHATSAPP_VERIFY_TOKEN",
    "xytralyn_secret_verify_token_2026",
)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")

WHATSAPP_PHONE_NUMBER_ID = os.getenv(
    "WHATSAPP_PHONE_NUMBER_ID",
    "1359104453944965",
)


def build_chat_history(
    db: Session,
    sender_phone: str,
    limit: int = 6,
) -> List[Dict[str, str]]:
    history: List[Dict[str, str]] = []

    try:
        records = (
            db.query(Message)
            .filter(Message.sender_phone == sender_phone)
            .order_by(Message.id.desc())
            .limit(limit)
            .all()
        )

        for record in reversed(records):
            user_message = getattr(record, "content", None)
            agent_reply = getattr(record, "agent_reply", None)

            if user_message:
                history.append(
                    {
                        "role": "user",
                        "content": str(user_message).strip(),
                    }
                )

            if agent_reply:
                history.append(
                    {
                        "role": "assistant",
                        "content": str(agent_reply).strip(),
                    }
                )

    except Exception:
        logger.exception("Could not fetch chat history")

    return history[-limit:]


def send_meta_whatsapp_message(
    to_phone: str,
    message_text: str,
) -> bool:
    token = os.getenv("WHATSAPP_TOKEN") or WHATSAPP_TOKEN
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID") or WHATSAPP_PHONE_NUMBER_ID

    if not token or not phone_id:
        logger.error("WhatsApp token or phone ID is missing")
        return False

    url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {
            "body": message_text,
        },
    }

    try:
        result = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=15,
        )

        logger.info(
            "WhatsApp send status=%s body=%s",
            result.status_code,
            result.text[:500],
        )

        result.raise_for_status()
        return True

    except requests.RequestException:
        logger.exception("WhatsApp message sending failed")
        return False


def parse_meta_message(
    data: Dict[str, Any],
) -> Tuple[Optional[str], str, Optional[str]]:
    try:
        entry = data.get("entry", [])
        if not entry:
            return None, "", None

        changes = entry[0].get("changes", [])
        if not changes:
            return None, "", None

        value = changes[0].get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return None, "", None

        first_message = messages[0]

        sender_phone = str(first_message.get("from", "")).strip()
        message_id = first_message.get("id")
        message_type = first_message.get("type", "text")

        user_message = ""

        if message_type == "text":
            user_message = str(first_message.get("text", {}).get("body", "")).strip()

        elif message_type == "button":
            user_message = str(first_message.get("button", {}).get("text", "")).strip()

        elif message_type == "interactive":
            interactive = first_message.get("interactive", {})

            if "button_reply" in interactive:
                user_message = str(interactive["button_reply"].get("title", "")).strip()

            elif "list_reply" in interactive:
                user_message = str(interactive["list_reply"].get("title", "")).strip()

        return (
            sender_phone,
            user_message,
            message_id,
        )

    except Exception:
        logger.exception("Could not parse Meta message")
        return None, "", None


def is_duplicate_message(
    db: Session,
    message_id: Optional[str],
) -> bool:
    if not message_id:
        return False

    if not hasattr(Message, "whatsapp_message_id"):
        return False

    try:
        existing = (
            db.query(Message)
            .filter(Message.whatsapp_message_id == message_id)
            .first()
        )
        return existing is not None

    except Exception:
        logger.exception("Duplicate message check failed")
        return False


def update_or_create_lead(
    db: Session,
    sender_phone: str,
    extracted: Dict[str, Any],
):
    lead = (
        db.query(Lead)
        .filter(Lead.phone == sender_phone)
        .first()
    )

    if not lead:
        lead = Lead(
            phone=sender_phone,
            name=extracted.get("name") or "Lead Customer",
            company=extracted.get("company") or "N/A",
            status="New",
        )
        db.add(lead)
    else:
        if extracted.get("name"):
            lead.name = extracted["name"]
        if extracted.get("company"):
            lead.company = extracted["company"]

    db.commit()
    db.refresh(lead)
    return lead


def save_message(
    db: Session,
    sender_phone: str,
    user_message: str,
    ai_response: str,
    agent_used: str,
    whatsapp_message_id: Optional[str] = None,
):
    try:
        record_kwargs = {
            "sender_phone": sender_phone,
            "content": user_message,
            "agent_used": agent_used,
        }

        if hasattr(Message, "whatsapp_message_id"):
            record_kwargs["whatsapp_message_id"] = whatsapp_message_id

        record = Message(**record_kwargs)

        if hasattr(record, "agent_reply"):
            record.agent_reply = ai_response

        db.add(record)
        db.commit()

    except Exception:
        db.rollback()
        logger.exception("Could not save message")


async def handle_async_meta_message(
    sender_phone: str,
    user_message: str,
    whatsapp_message_id: Optional[str] = None,
):
    db: Session = SessionLocal()

    try:
        if is_duplicate_message(db, whatsapp_message_id):
            logger.info("Duplicate WhatsApp message skipped: %s", whatsapp_message_id)
            return

        selected_agent = detect_agent(user_message)
        extracted = extract_lead_info(user_message)
        high_intent = is_potential_lead(user_message)

        lead = None

        if selected_agent == "sales" or high_intent:
            try:
                lead = update_or_create_lead(
                    db=db,
                    sender_phone=sender_phone,
                    extracted=extracted,
                )
            except Exception:
                db.rollback()
                logger.exception("Lead processing failed")

        has_contact = bool(extracted.get("phone") or extracted.get("email"))

        if selected_agent == "sales" and (has_contact or high_intent):
            try:
                send_admin_alert(
                    lead_name=getattr(lead, "name", "Lead Customer"),
                    company=getattr(lead, "company", "N/A"),
                    phone=sender_phone,
                )
            except Exception:
                logger.exception("Admin notification failed")

        history = build_chat_history(
            db=db,
            sender_phone=sender_phone,
            limit=6,
        )

        try:
            ai_response = await generate_agent_reply(
                user_message=user_message,
                history=history,
                agent_name=selected_agent,
                business_name="AstaLynx",
            )
        except Exception:
            logger.exception("AI generation failed")
            ai_response = (
                "Mujhe is waqt response generate karne mein temporary issue aa raha hai. "
                "Kripya ek pal baad dobara try karein."
            )

        save_message(
            db=db,
            sender_phone=sender_phone,
            user_message=user_message,
            ai_response=ai_response,
            agent_used=selected_agent,
            whatsapp_message_id=whatsapp_message_id,
        )

        send_meta_whatsapp_message(
            to_phone=sender_phone,
            message_text=ai_response,
        )

    except Exception:
        db.rollback()
        logger.exception("Background WhatsApp processing failed")

    finally:
        db.close()


@router.get("/webhook")
@router.get("/chat/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    expected_token = os.getenv("WHATSAPP_VERIFY_TOKEN", VERIFY_TOKEN)

    if hub_mode == "subscribe" and hub_verify_token == expected_token:
        return Response(
            content=hub_challenge or "",
            media_type="text/plain",
        )

    raise HTTPException(
        status_code=403,
        detail="Verification token mismatch",
    )


@router.post("/webhook")
@router.post("/chat/webhook")
async def webhook_receiver(
    request: Request,
    background_tasks: BackgroundTasks,
):
    try:
        data = await request.json()
    except Exception:
        logger.exception("Could not read webhook JSON")
        return {"status": "ignored"}

    (
        sender_phone,
        user_message,
        whatsapp_message_id,
    ) = parse_meta_message(data)

    if not sender_phone or not user_message:
        return {
            "status": "ok",
            "reason": "no_message",
        }

    background_tasks.add_task(
        handle_async_meta_message,
        sender_phone,
        user_message,
        whatsapp_message_id,
    )

    return {"status": "success"}


@router.post("/incoming")
@router.post("/chat/incoming")
async def incoming_chat(
    request: Request,
    db: Session = Depends(get_db),
):
    form_data = await request.form()

    sender_phone = str(form_data.get("From", "")).replace("whatsapp:", "").strip()
    user_message = str(form_data.get("Body", "")).strip()

    if not sender_phone or not user_message:
        twilio_response = MessagingResponse()
        return Response(
            content=str(twilio_response),
            media_type="application/xml",
        )

    selected_agent = detect_agent(user_message)
    history = build_chat_history(
        db=db,
        sender_phone=sender_phone,
        limit=6,
    )

    try:
        ai_response = await generate_agent_reply(
            user_message=user_message,
            history=history,
            agent_name=selected_agent,
            business_name="AstaLynx",
        )
    except Exception:
        logger.exception("Twilio AI generation failed")
        ai_response = (
            "Mujhe is waqt response generate karne mein temporary issue aa raha hai. "
            "Kripya ek pal baad dobara try karein."
        )

    save_message(
        db=db,
        sender_phone=sender_phone,
        user_message=user_message,
        ai_response=ai_response,
        agent_used=selected_agent,
    )

    twilio_response = MessagingResponse()
    twilio_response.message(str(ai_response))

    return Response(
        content=str(twilio_response),
        media_type="application/xml",
    )