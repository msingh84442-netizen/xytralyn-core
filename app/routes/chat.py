import os
import re
import requests
from fastapi import APIRouter, Form, Depends, Response, Request, Query, HTTPException
from sqlalchemy.orm import Session
from twilio.twiml.messaging_response import MessagingResponse

from app.database import get_db
from app.models import Lead, Message
from app.services.ai_agent import extract_lead_info, is_potential_lead, generate_agent_reply
from app.services.notifier import send_admin_alert

router = APIRouter(tags=["Chat"])

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "xytralyn_secret_verify_token_2026")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "1359104453944965")


def build_chat_history(db: Session, sender_phone: str, limit: int = 6):
    """Client ke past messages nikalta hai taaki chahe kal baat hui ho ya 1 saal pehle, context bana rahe."""
    history = []
    try:
        records = (
            db.query(Message)
            .filter(Message.sender_phone == sender_phone)
            .order_by(Message.id.desc())
            .limit(limit)
            .all()
        )
        records = sorted(records, key=lambda x: x.id)

        for rec in records:
            if rec.content:
                history.append({"role": "user", "content": rec.content})
            if hasattr(rec, "agent_reply") and rec.agent_reply:
                history.append({"role": "assistant", "content": rec.agent_reply})
    except Exception as err:
        print(f"[HISTORY FETCH ERROR]: {err}")
    return history


def send_meta_whatsapp_message(to_phone: str, message_text: str):
    """Meta WhatsApp Cloud API ke through user ko response bhejta hai."""
    token = os.getenv("WHATSAPP_TOKEN") or WHATSAPP_TOKEN
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID") or WHATSAPP_PHONE_NUMBER_ID

    if not token or not phone_id:
        print("\033[91m[META SEND ERROR]: Missing WHATSAPP_TOKEN or WHATSAPP_PHONE_NUMBER_ID\033[0m")
        return

    url = f"https://graph.facebook.com/v20.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
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
        print(f"\033[92m[META DISPATCH RESULT]:\033[0m Phone={to_phone} Status={r.status_code} Body={r.text}")
    except Exception as err:
        print(f"\033[91m[META SEND EXCEPTION]:\033[0m {err}")


# ==========================================
# 1. WEBHOOK GET VERIFICATION HANDSHAKE
# ==========================================
@router.get("/webhook")
@router.get("/chat/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    print(f"\033[93m[HANDSHAKE ATTEMPT]:\033[0m mode={hub_mode}, token={hub_verify_token}")
    expected_token = os.getenv("WHATSAPP_VERIFY_TOKEN", VERIFY_TOKEN)
    if hub_mode == "subscribe" and hub_verify_token == expected_token:
        print("\033[92m[HANDSHAKE SUCCESS]\033[0m")
        return Response(content=hub_challenge, media_type="text/plain")

    print("\033[91m[HANDSHAKE FORBIDDEN]\033[0m")
    raise HTTPException(status_code=403, detail="Verification token mismatch")


# ==========================================
# 2. WEBHOOK POST RECEIVER (META & GREEN-API)
# ==========================================
@router.post("/webhook")
@router.post("/chat/webhook")
async def webhook_receiver(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
    except Exception as e:
        print(f"[WEBHOOK RAW READ ERROR]: {e}")
        return {"status": "ignored"}

    print(f"\033[95m[INCOMING WEBHOOK RAW BODY]:\033[0m {data}")

    if "typeWebhook" in data:
        return await handle_green_api(data, db)

    sender_phone = None
    user_message = ""

    try:
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        val = changes.get("value", {})
        messages = val.get("messages", [])

        if not messages:
            statuses = val.get("statuses", [])
            if statuses:
                print(f"[META STATUS UPDATE]: {statuses[0].get('status')}")
            return {"status": "ok", "reason": "no_message_body"}

        first_msg = messages[0]
        sender_phone = first_msg.get("from", "").strip()

        msg_type = first_msg.get("type", "text")
        if msg_type == "text":
            user_message = first_msg.get("text", {}).get("body", "").strip()
        elif msg_type == "button":
            user_message = first_msg.get("button", {}).get("text", "").strip()
        elif msg_type == "interactive":
            inter = first_msg.get("interactive", {})
            if "button_reply" in inter:
                user_message = inter["button_reply"].get("title", "")
            elif "list_reply" in inter:
                user_message = inter["list_reply"].get("title", "")

    except Exception as parse_err:
        print(f"[META PARSE ERROR]: {parse_err}")
        return {"status": "parse_error"}

    print(f"\033[96m[USER INCOMING PARSED]:\033[0m Phone={sender_phone} Msg='{user_message}'")

    if not sender_phone or not user_message:
        return {"status": "empty_sender_or_message"}

    # 1. Lead extraction aur Intent check
    extracted = extract_lead_info(user_message)
    high_intent = is_potential_lead(user_message)

    # 2. Database Lead entry
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

    # 3. Admin notification (Only genuine lead info / high intent)
    has_contact = bool(extracted.get("phone") or extracted.get("email"))
    if has_contact or high_intent:
        try:
            send_admin_alert(
                lead_name=getattr(target_lead, "name", "Lead Customer"),
                company=getattr(target_lead, "company", "N/A"),
                phone=sender_phone
            )
            print(f"\033[92m[ADMIN ALERT DISPATCHED]:\033[0m Lead from {sender_phone}")
        except Exception as alert_err:
            print(f"[ALERT WARNING]: {alert_err}")
    else:
        print(f"[CASUAL MESSAGE]: '{user_message}' - Admin alert skipped.")

    # 4. Check for user-requested Fresh Start
    clean_raw = re.sub(r"[^\w\s]", "", user_message).strip().lower()
    reset_triggers = {"reset", "new chat", "start fresh", "clear", "naye se start karo"}
    
    if clean_raw in reset_triggers:
        chat_history = []
        ai_response = "Zaroor! Nayi conversation start karte hain. 😊 Bataiye, aaj main aapki kya help kar sakta hoon?"
    else:
        chat_history = build_chat_history(db, sender_phone, limit=6)
        try:
            ai_response = await generate_agent_reply(user_message, history=chat_history)
        except Exception as agent_err:
            print(f"[AI AGENT ERROR]: {agent_err}")
            c_name = target_lead.company if target_lead.company and target_lead.company != "N/A" else "Customer"
            ai_response = f"Dhanyavaad, {c_name}! Aapka message mil gaya hai. Hum jaldi contact karenge."

    # 5. Save message record
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
        print(f"[DB RECORD SAVE ERROR]: {db_err}")

    # 6. Dispatch reply back to WhatsApp
    send_meta_whatsapp_message(to_phone=sender_phone, message_text=ai_response)

    return {"status": "success"}


async def handle_green_api(data: dict, db: Session):
    """Green-API webhook handler fallback."""
    if data.get("typeWebhook") != "incomingMessageReceived":
        return {"status": "ignored"}

    msg_data = data.get("messageData", {})
    sender_data = data.get("senderData", {})
    raw_sender = sender_data.get("sender", "") or sender_data.get("chatId", "")
    sender_phone = raw_sender.replace("@c.us", "").replace("@s.whatsapp.net", "").strip()

    user_message = ""
    if "textMessageData" in msg_data:
        user_message = msg_data.get("textMessageData", {}).get("textMessage", "")
    elif "extendedTextMessageData" in msg_data:
        user_message = msg_data.get("extendedTextMessageData", {}).get("text", "")

    user_message = str(user_message).strip()
    if not user_message or not sender_phone:
        return {"status": "no_text"}

    extracted = extract_lead_info(user_message)
    high_intent = is_potential_lead(user_message)

    target_lead = db.query(Lead).filter(Lead.phone == sender_phone).first()
    if not target_lead:
        target_lead = Lead(phone=sender_phone, name=extracted.get("name") or "Lead Customer", company="N/A", status="New")
        db.add(target_lead)
        db.commit()
        db.refresh(target_lead)

    has_contact = bool(extracted.get("phone") or extracted.get("email"))
    if has_contact or high_intent:
        try:
            send_admin_alert(
                lead_name=getattr(target_lead, "name", "Lead Customer"),
                company="N/A",
                phone=sender_phone
            )
        except Exception:
            pass

    chat_history = build_chat_history(db, sender_phone, limit=6)
    try:
        ai_response = await generate_agent_reply(user_message, history=chat_history)
    except Exception:
        ai_response = "Aapka message mil gaya hai."

    inst_id = os.getenv("GREEN_API_INSTANCE_ID")
    tok = os.getenv("GREEN_API_TOKEN")
    if inst_id and tok:
        requests.post(
            f"https://7107.api.greenapi.com/waInstance{inst_id}/sendMessage/{tok}",
            json={"chatId": f"{sender_phone}@c.us", "message": ai_response},
            timeout=12
        )
    return {"status": "success"}


# ==========================================
# 3. TWILIO COMPATIBILITY
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
    high_intent = is_potential_lead(user_message)

    target_lead = db.query(Lead).filter(Lead.phone == sender_phone).first()
    if not target_lead:
        target_lead = Lead(phone=sender_phone, name=extracted.get("name") or "Lead Customer", company="N/A", status="New")
        db.add(target_lead)
        db.commit()
        db.refresh(target_lead)

    has_contact = bool(extracted.get("phone") or extracted.get("email"))
    if has_contact or high_intent:
        try:
            send_admin_alert(
                lead_name=getattr(target_lead, "name", "Lead Customer"),
                company="N/A",
                phone=sender_phone
            )
        except Exception:
            pass

    chat_history = build_chat_history(db, sender_phone, limit=6)
    try:
        ai_response = await generate_agent_reply(user_message, history=chat_history)
    except Exception:
        ai_response = "Dhanyavaad! Message prapt hua."

    resp = MessagingResponse()
    resp.message(str(ai_response))
    return Response(content=str(resp), media_type="application/xml")