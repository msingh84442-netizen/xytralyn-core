import os
import re
import requests
from fastapi import APIRouter, Form, Depends, Response, Request, Query, HTTPException
from sqlalchemy.orm import Session
from twilio.twiml.messaging_response import MessagingResponse

from app.database import get_db
from app.models import Lead, Message
from app.services.ai_agent import extract_lead_info, generate_agent_reply
from app.services.notifier import send_admin_alert

router = APIRouter(tags=["Chat"])

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "xytralyn_secret_verify_token_2026")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")


def build_chat_history(db: Session, sender_phone: str, limit: int = 6):
    """Database se isolated user ke recent messages nikal kar context build karta hai."""
    history = []
    try:
        records = (
            db.query(Message)
            .filter(Message.sender_phone == sender_phone)
            .order_by(Message.id.desc())
            .limit(limit)
            .all()
        )
        records.reverse()

        for rec in records:
            if rec.content:
                history.append({"role": "user", "content": rec.content})
            if hasattr(rec, "agent_reply") and rec.agent_reply:
                history.append({"role": "assistant", "content": rec.agent_reply})
    except Exception as err:
        print(f"[HISTORY FETCH ERROR]: {err}")
    return history


def send_meta_whatsapp_message(to_phone: str, message_text: str):
    """Meta WhatsApp Cloud API ke zariye customer ko reply bhejne ka function."""
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        print("[CONFIG ERROR]: WHATSAPP_TOKEN ya WHATSAPP_PHONE_NUMBER_ID missing hai!")
        return

    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"body": message_text},
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=12)
        print(f"\033[92m[META DISPATCH SUCCESS]:\033[0m User={to_phone} Status={r.status_code}")
    except Exception as e:
        print(f"\033[91m[META SEND ERROR]:\033[0m {e}")


# ==========================================
# 1. META CLOUD API WEBHOOK HANDSHAKE (GET)
# ==========================================
@router.get("/webhook")
@router.get("/chat/webhook")
async def verify_meta_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    print(f"\033[93m[WEBHOOK HANDSHAKE ATTEMPT]:\033[0m mode={hub_mode}, token={hub_verify_token}")
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        print("\033[92m[WEBHOOK HANDSHAKE VERIFIED SUCCESSFULLY]\033[0m")
        return Response(content=hub_challenge, media_type="text/plain")
    
    print("\033[91m[WEBHOOK HANDSHAKE FAILED]: Token mismatch\033[0m")
    raise HTTPException(status_code=403, detail="Verification token mismatch")


# ==========================================
# 2. META CLOUD API INCOMING MESSAGES (POST)
# ==========================================
@router.post("/webhook")
@router.post("/chat/webhook")
async def meta_webhook_receiver(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
    except Exception as e:
        print(f"[WEBHOOK JSON ERROR]: {e}")
        return {"status": "invalid json"}

    # Green-API compatibility fallback
    if "typeWebhook" in data:
        return await handle_green_api_data(data, db)

    # Meta Cloud API Payload Parser
    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        
        if not messages:
            # Status update notifications (delivered, read, etc.)
            return {"status": "ok", "message": "no chat message payload"}

        msg_obj = messages[0]
        sender_phone = msg_obj.get("from", "").strip()
        user_message = ""

        if msg_obj.get("type") == "text":
            user_message = msg_obj.get("text", {}).get("body", "").strip()
        elif msg_obj.get("type") == "button":
            user_message = msg_obj.get("button", {}).get("text", "").strip()
        elif msg_obj.get("type") == "interactive":
            interactive = msg_obj.get("interactive", {})
            if "button_reply" in interactive:
                user_message = interactive["button_reply"].get("title", "")
            elif "list_reply" in interactive:
                user_message = interactive["list_reply"].get("title", "")

        print(f"\033[96m[META INCOMING MSG]:\033[0m Phone={sender_phone} | Msg='{user_message}'")

        if not user_message or not sender_phone:
            return {"status": "skipped", "reason": "empty content"}

        # 1. Lead extraction
        extracted = extract_lead_info(user_message)

        # 2. Database Lead Record
        target_lead = db.query(Lead).filter(Lead.phone == sender_phone).first()
        if not target_lead:
            target_lead = Lead(
                phone=sender_phone,
                name=extracted.get("name") or "Lead Customer",
                company=extracted.get("company") or "N/A",
                status="New"
            )
            db.add(target_lead)
            db.commit()
            db.refresh(target_lead)
        else:
            if extracted.get("name") and extracted.get("name") != "Lead Customer":
                target_lead.name = extracted.get("name")
            if extracted.get("company") and extracted.get("company") != "N/A":
                target_lead.company = extracted.get("company")
            db.commit()
            db.refresh(target_lead)

        # 3. Admin Notification
        try:
            send_admin_alert(
                lead_name=getattr(target_lead, "name", "Lead Customer"),
                company=getattr(target_lead, "company", "N/A"),
                phone=sender_phone
            )
        except Exception as alert_err:
            print(f"[ALERT WARNING]: Failed to notify admin: {alert_err}")

        # 4. Context History
        chat_history = build_chat_history(db, sender_phone, limit=6)

        # 5. Generate AI Reply
        try:
            ai_response = await generate_agent_reply(user_message, history=chat_history)
        except Exception as agent_err:
            print(f"[AI AGENT ERROR]: {agent_err}")
            company_name = target_lead.company if target_lead.company and target_lead.company != "N/A" else "Customer"
            ai_response = f"Dhanyavaad, {company_name}! Aapki query note kar li gayi hai."

        # 6. Save Message Record
        try:
            msg_record = Message(
                sender_phone=sender_phone,
                content=user_message,
                agent_used="lead-extractor"
            )
            if hasattr(msg_record, "agent_reply"):
                msg_record.agent_reply = ai_response
            db.add(msg_record)
            db.commit()
        except Exception as db_err:
            print(f"[DB SAVE ERROR]: {db_err}")

        # 7. Meta Dispatch
        send_meta_whatsapp_message(to_phone=sender_phone, message_text=ai_response)

        return {"status": "success"}

    except Exception as e:
        print(f"[META WEBHOOK ERROR]: {e}")
        return {"status": "error", "detail": str(e)}


async def handle_green_api_data(data: dict, db: Session):
    """Green-API payload compatibility helper."""
    type_webhook = data.get("typeWebhook")
    if type_webhook != "incomingMessageReceived":
        return {"status": "ignored", "type": type_webhook}

    message_data = data.get("messageData", {})
    sender_data = data.get("senderData", {})
    raw_sender = sender_data.get("sender", "") or sender_data.get("chatId", "")
    sender_phone = raw_sender.replace("@c.us", "").replace("@s.whatsapp.net", "").strip()

    user_message = ""
    if "textMessageData" in message_data:
        user_message = message_data.get("textMessageData", {}).get("textMessage", "")
    elif "extendedTextMessageData" in message_data:
        user_message = message_data.get("extendedTextMessageData", {}).get("text", "")
    elif isinstance(message_data, str):
        user_message = message_data

    user_message = str(user_message).strip()
    if not user_message or not sender_phone:
        return {"status": "no_message_or_phone"}

    extracted = extract_lead_info(user_message)
    target_lead = db.query(Lead).filter(Lead.phone == sender_phone).first()
    if not target_lead:
        target_lead = Lead(
            phone=sender_phone,
            name=extracted.get("name") or "Lead Customer",
            company=extracted.get("company") or "N/A",
            status="New"
        )
        db.add(target_lead)
        db.commit()
        db.refresh(target_lead)
    else:
        if extracted.get("name") and extracted.get("name") != "Lead Customer":
            target_lead.name = extracted.get("name")
        if extracted.get("company") and extracted.get("company") != "N/A":
            target_lead.company = extracted.get("company")
        db.commit()
        db.refresh(target_lead)

    try:
        send_admin_alert(
            lead_name=getattr(target_lead, "name", "Lead Customer"),
            company=getattr(target_lead, "company", "N/A"),
            phone=sender_phone
        )
    except Exception as alert_err:
        print(f"[ALERT WARNING]: Failed to notify admin: {alert_err}")

    chat_history = build_chat_history(db, sender_phone, limit=6)

    try:
        ai_response = await generate_agent_reply(user_message, history=chat_history)
    except Exception as agent_err:
        print(f"[AI AGENT ERROR]: {agent_err}")
        company_name = target_lead.company if target_lead.company and target_lead.company != "N/A" else "Customer"
        ai_response = f"Dhanyavaad, {company_name}! Aapki query note kar li gayi hai."

    try:
        msg_record = Message(
            sender_phone=sender_phone,
            content=user_message,
            agent_used="lead-extractor"
        )
        if hasattr(msg_record, "agent_reply"):
            msg_record.agent_reply = ai_response
        db.add(msg_record)
        db.commit()
    except Exception as db_err:
        print(f"[DB SAVE ERROR]: {db_err}")

    instance_id = os.getenv("GREEN_API_INSTANCE_ID")
    token = os.getenv("GREEN_API_TOKEN")
    if instance_id and token:
        send_url = f"https://7107.api.greenapi.com/waInstance{instance_id}/sendMessage/{token}"
        payload = {"chatId": f"{sender_phone}@c.us", "message": ai_response}
        try:
            requests.post(send_url, json=payload, timeout=12)
        except Exception as send_err:
            print(f"[GREEN-API SEND ERROR]: {send_err}")

    return {"status": "success", "phone": sender_phone}


# ==========================================
# 3. TWILIO FALLBACK ROUTES
# ==========================================
@router.get("/incoming")
@router.get("/chat/incoming")
async def incoming_chat_get():
    return Response(content="<Response/>", media_type="application/xml")


@router.post("/incoming")
@router.post("/chat/incoming")
async def incoming_chat(
    From: str = Form(...),
    Body: str = Form(...),
    db: Session = Depends(get_db)
):
    sender_phone = From.replace("whatsapp:", "").strip()
    user_message = Body.strip()

    extracted = extract_lead_info(user_message)
    target_lead = db.query(Lead).filter(Lead.phone == sender_phone).first()
    if not target_lead:
        target_lead = Lead(
            phone=sender_phone,
            name=extracted.get("name") or "Lead Customer",
            company=extracted.get("company") or "N/A",
            status="New"
        )
        db.add(target_lead)
        db.commit()
        db.refresh(target_lead)
    else:
        if extracted.get("name") and extracted.get("name") != "Lead Customer":
            target_lead.name = extracted.get("name")
        if extracted.get("company") and extracted.get("company") != "N/A":
            target_lead.company = extracted.get("company")
        db.commit()
        db.refresh(target_lead)

    phone_pattern = r'(?:(?:\+91|0)?[ -]?)?([6-9]\d{9})\b'
    phone_match = re.search(phone_pattern, user_message)
    final_contact_phone = phone_match.group(1).strip() if phone_match else target_lead.phone

    try:
        send_admin_alert(
            lead_name=getattr(target_lead, "name", "Lead Customer"),
            company=getattr(target_lead, "company", "N/A"),
            phone=final_contact_phone
        )
    except Exception as alert_err:
        print(f"\033[91m[ALERT WARNING]: Failed to notify admin: {alert_err}\033[0m")

    chat_history = build_chat_history(db, sender_phone, limit=6)

    try:
        ai_response = await generate_agent_reply(user_message, history=chat_history)
    except Exception as agent_err:
        print(f"[AI AGENT ERROR]: {agent_err}")
        company_name = target_lead.company if target_lead.company and target_lead.company != "N/A" else "Customer"
        ai_response = f"Dhanyavaad, {company_name}! Aapki details note kar li gayi hain."

    msg_record = Message(
        sender_phone=sender_phone,
        content=user_message,
        agent_used="lead-extractor"
    )
    if hasattr(msg_record, "agent_reply"):
        msg_record.agent_reply = ai_response
    db.add(msg_record)
    db.commit()

    resp = MessagingResponse()
    resp.message(str(ai_response))
    return Response(content=str(resp), media_type="application/xml")