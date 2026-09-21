import os
import re
from typing import Optional, Dict, List

from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """
You are Xytralyn AI Assistant chatting on WhatsApp.

About Xytralyn:
We provide Multi-Agent AI SaaS & business automation (Sales, Support, HR, Accountant, Research agents) and WhatsApp automation for businesses.

Strict WhatsApp Guidelines:
- Reply in short, natural, friendly Hinglish (Hindi + English).
- Limit responses strictly to 1-2 concise sentences. Keep it conversational like real WhatsApp chat.
- NEVER include formal email signatures, closings, or sign-offs (strictly NO "Regards", "Sincerely", "Xytralyn AI Assistant").
- CONTEXT AWARENESS: Answer specifically based on what THIS customer is asking. If they want info, explain briefly. If they ask for pricing, mention custom plans based on their scale.
- DEMO SCHEDULING: If they mention a specific day/time, confirm THAT specific time. Do NOT assume 3:00 PM unless they explicitly said 3:00 PM. If no time is shared, ask for their convenient slot.
- LEAD DETAILS: If the user has already shared their name, phone, or email in previous messages, NEVER ask for them again.
"""

def get_async_groq_client() -> Optional[AsyncGroq]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("[GROQ ERROR]: GROQ_API_KEY environment variable is missing!")
        return None
    try:
        return AsyncGroq(api_key=api_key.strip())
    except Exception as e:
        print(f"[GROQ CLIENT ERROR]: {e}")
        return None

async def get_available_chat_models(client: AsyncGroq) -> List[str]:
    """Dynamically fetch and prioritize active general chat models asynchronously."""
    try:
        models_data = await client.models.list()
        active_ids = [m.id for m in models_data.data if getattr(m, 'active', True)]
        
        ignore_keywords = ["whisper", "vision", "guard", "arabic", "canopylabs", "compound"]
        chat_models = [m for m in active_ids if not any(k in m.lower() for k in ignore_keywords)]
        
        preferred_order = ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b"]
        sorted_models = [m for m in preferred_order if m in chat_models] + [m for m in chat_models if m not in preferred_order]
        
        return sorted_models if sorted_models else ["openai/gpt-oss-20b"]
    except Exception as e:
        print(f"[GROQ LIST MODELS ERROR]: {e}")
        return ["openai/gpt-oss-20b"]

async def generate_agent_reply(user_message: str, history: Optional[List[Dict[str, str]]] = None) -> str:
    if not user_message or not user_message.strip():
        return "Namaste! 👋 Main Xytralyn AI assistant hoon. Aapki kya sahayata kar sakta hoon?"

    client = get_async_groq_client()
    if client is None:
        return "Dhanyavaad! 🙏 Hamari team aapki query check karke aapse jaldi contact karegi."

    # Messages array with isolated context
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if history and isinstance(history, list):
        for msg in history[-8:]:  # Last 8 messages for isolated session memory
            messages.append(msg)

    messages.append({"role": "user", "content": user_message.strip()})

    available_models = await get_available_chat_models(client)

    for model_id in available_models:
        try:
            completion = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                temperature=0.3,
                max_tokens=220
            )
            reply = completion.choices[0].message.content
            if reply and reply.strip():
                cleaned_reply = re.sub(r'(?i)\n*(regards|sincerely|best regards|xytralyn ai assistant).*', '', reply.strip()).strip()
                return cleaned_reply if cleaned_reply else reply.strip()
        except Exception as e:
            print(f"[GROQ ASYNC MODEL FAILED] Model={model_id} | Error={e}")
            continue

    return "Thanks for reaching out! 🙏 Hamari team aapki query check karke aapse shortly connect karegi."

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