import os
import re
import requests
from fastapi import APIRouter, Form, Depends, Response, Request
from sqlalchemy.orm import Session
from twilio.twiml.messaging_response import MessagingResponse

from app.database import get_db
from app.models import Lead, Message
from app.services.ai_agent import extract_lead_info, generate_agent_reply
from app.services.notifier import send_admin_alert

router = APIRouter(prefix="/chat", tags=["Chat"])

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


# 1. Verification GET route
@router.get("/incoming")
async def incoming_chat_get():
    return Response(content="<Response/>", media_type="application/xml")


# 2. Twilio WhatsApp Webhook POST route
@router.post("/incoming")
async def incoming_chat(
    From: str = Form(...),
    Body: str = Form(...),
    db: Session = Depends(get_db)
):
    sender_phone = From.replace("whatsapp:", "").strip()
    user_message = Body.strip()

    print(f"\033[96m[TWILIO USER MSG]:\033[0m {user_message} (From: {sender_phone})")

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


# 3. Direct Reliable Green-API Webhook
@router.post("/webhook")
async def green_api_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
    except Exception as e:
        print(f"[WEBHOOK JSON ERROR]: {e}")
        return {"status": "ignored", "reason": "invalid json"}

    print(f"\033[93m[FULL INCOMING WEBHOOK DATA]:\033[0m {data}")

    type_webhook = data.get("typeWebhook")
    if type_webhook != "incomingMessageReceived":
        print(f"[SKIPPED TYPE]: {type_webhook}")
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
    print(f"\033[96m[GREEN-API INCOMING]:\033[0m Phone={sender_phone} | Msg='{user_message}'")

    if not user_message or not sender_phone:
        print(f"[GREEN-API SKIP]: Empty fields | phone='{sender_phone}', msg='{user_message}'")
        return {"status": "no_message_or_phone"}

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

    # 7. Green-API Dispatch
    instance_id = os.getenv("GREEN_API_INSTANCE_ID")
    token = os.getenv("GREEN_API_TOKEN")

    if instance_id and token:
        send_url = f"https://7107.api.greenapi.com/waInstance{instance_id}/sendMessage/{token}"
        payload = {
            "chatId": f"{sender_phone}@c.us",
            "message": ai_response
        }
        try:
            r = requests.post(send_url, json=payload, timeout=12)
            print(f"\033[92m[GREEN-API DISPATCH SUCCESS]:\033[0m User={sender_phone} Status={r.status_code}")
        except Exception as send_err:
            print(f"[GREEN-API SEND ERROR]: {send_err}")
    else:
        print("[CONFIG ERROR]: GREEN_API_INSTANCE_ID ya GREEN_API_TOKEN missing hain!")

    return {"status": "success", "phone": sender_phone}