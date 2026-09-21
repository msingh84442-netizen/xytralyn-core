import os
import re
from typing import Optional, Dict, List

from groq import Groq
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """
You are Xytralyn AI Assistant chatting on WhatsApp.

About Xytralyn:
We provide Multi-Agent AI SaaS & business automation (Sales, Support, HR, Accountant, Research agents) and WhatsApp automation.

Strict WhatsApp Chat Guidelines:
- Reply in short, natural, friendly Hinglish (Hindi + English).
- Limit your response to 1-2 complete sentences.
- Never write formal email signatures, closings, or sign-offs (strictly NO "Regards", "Sincerely", "Xytralyn AI Assistant").
- If the customer asks about their demo timing and 3:00 PM was previously discussed or booked, directly confirm: "Aapka demo kal dopahar 3:00 PM par Google Meet par scheduled hai."
- If the customer has already provided their name, phone number, or email in previous messages, do NOT ask for them again.
- Always finish your thoughts completely—never leave sentences half-written.
"""

def get_groq_client() -> Optional[Groq]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("[GROQ ERROR]: GROQ_API_KEY environment variable is missing!")
        return None
    try:
        return Groq(api_key=api_key.strip())
    except Exception as e:
        print(f"[GROQ CLIENT ERROR]: {e}")
        return None

def get_available_chat_models(client: Groq) -> List[str]:
    """Dynamically fetch and prioritize active general chat models."""
    try:
        models_data = client.models.list()
        active_ids = [m.id for m in models_data.data if getattr(m, 'active', True)]
        
        ignore_keywords = ["whisper", "vision", "guard", "arabic", "canopylabs", "compound"]
        chat_models = [m for m in active_ids if not any(k in m.lower() for k in ignore_keywords)]
        
        preferred_order = ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b"]
        sorted_models = [m for m in preferred_order if m in chat_models] + [m for m in chat_models if m not in preferred_order]
        
        return sorted_models if sorted_models else ["openai/gpt-oss-20b"]
    except Exception as e:
        print(f"[GROQ LIST MODELS ERROR]: {e}")
        return ["openai/gpt-oss-20b"]

def generate_agent_reply(user_message: str, history: Optional[List[Dict[str, str]]] = None) -> str:
    if not user_message or not user_message.strip():
        return "Namaste! 👋 Main Xytralyn AI assistant hoon. Aapko kis service ya agent ke baare mein janna hai?"

    client = get_groq_client()
    if client is None:
        return "Dhanyavaad! 🙏 Hamari team aapki query check karke aapse jaldi contact karegi."

    # Messages payload with system instructions
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Pichle conversation context ko append karein
    if history and isinstance(history, list):
        for msg in history[-8:]:  # Last 8 messages for full context
            messages.append(msg)

    # Current user message
    messages.append({"role": "user", "content": user_message.strip()})

    available_models = get_available_chat_models(client)

    for model_id in available_models:
        try:
            completion = client.chat.completions.create(
                model=model_id,
                messages=messages,
                temperature=0.3,
                max_tokens=250
            )
            reply = completion.choices[0].message.content
            if reply and reply.strip():
                # Cleanup if model outputs email closings by accident
                cleaned_reply = re.sub(r'(?i)\n*(regards|sincerely|best regards|xytralyn ai assistant).*', '', reply.strip()).strip()
                return cleaned_reply if cleaned_reply else reply.strip()
        except Exception as e:
            print(f"[GROQ MODEL FAILED] Model={model_id} | Error={e}")
            continue

    return "Thanks for reaching out! 🙏 Hamari team aapki query check karke aapse shortly contact karegi."

def extract_lead_info(user_message: str) -> Dict[str, Optional[str]]:
    lead_data = {"name": None, "phone": None, "email": None}
    if not user_message:
        return lead_data

    text = user_message.strip()

    email_match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text)
    if email_match:
        lead_data["email"] = email_match.group(0).lower()

    phone_matches = re.findall(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)", text)
    if phone_matches:
        phone = re.sub(r"[^\d]", "", phone_matches[0])
        if len(phone) == 12 and phone.startswith("91"):
            phone = phone[2:]
        if len(phone) == 10:
            lead_data["phone"] = phone

    name_patterns = [
        r"\bmy name is\s+([A-Za-z][A-Za-z .'-]{1,50})",
        r"\bmera naam\s+([A-Za-z][A-Za-z .'-]{1,50})",
        r"\bname\s*[:\-]\s*([A-Za-z][A-Za-z .'-]{1,50})",
        r"\bnaam\s*[:\-]\s*([A-Za-z][A-Za-z .'-]{1,50})",
        r"\bi am\s+([A-Za-z][A-Za-z .'-]{1,50})",
        r"\bi'm\s+([A-Za-z][A-Za-z .'-]{1,50})",
    ]

    for pattern in name_patterns:
        name_match = re.search(pattern, text, re.IGNORECASE)
        if name_match:
            name = name_match.group(1).strip()
            name = re.sub(r"\s+(and|aur|my|mera|phone|email|number)\s*$", "", name, flags=re.IGNORECASE)
            lead_data["name"] = name.title()
            break

    return lead_data

def is_potential_lead(user_message: str) -> bool:
    if not user_message:
        return False
    text = user_message.lower()
    lead_keywords = [
        "price", "pricing", "cost", "demo", "interested", "buy",
        "purchase", "service", "automation", "whatsapp bot", "ai agent",
        "website", "web development", "need", "requirement", "business"
    ]
    return any(keyword in text for keyword in lead_keywords)