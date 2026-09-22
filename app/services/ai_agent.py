import os
import re
from typing import Optional, Dict, List

from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """
You are the official AI Assistant for Xytralyn on WhatsApp.

About Xytralyn:
We provide Multi-Agent AI SaaS & business automation (Sales, Support, HR, Accountant, Research) and WhatsApp automation for businesses.

Official Plans:
- Starter: ₹2,499/month
- Growth: ₹4,999/month
- Enterprise: ₹9,999/month

Strict Guidelines:
1. FOCUS ONLY ON THE LATEST MESSAGE: Never bring up older topics (like stores, quotes, or pricing) unless the user's latest message specifically asks about them.
2. BREVITY: Keep answers strictly under 2 concise sentences.
3. CONVERSATIONAL: Speak in natural, friendly Hinglish.
4. NO DUMMY VALUES: Always use exact pricing (₹2,499/mo, etc.). Never use placeholders like ₹X or [price].
5. NO SIGN-OFFS: Strictly NO email footers, sign-offs, or signatures (never write 'Regards', 'Sincerely', or 'Xytralyn AI Assistant' at the end).
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
    """Dynamically fetch and prioritize active production chat models."""
    fallback_models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    try:
        models_data = await client.models.list()
        active_ids = [m.id for m in models_data.data if getattr(m, 'active', True)]
        
        ignore_keywords = ["whisper", "vision", "guard", "audio", "embed"]
        chat_models = [m for m in active_ids if not any(k in m.lower() for k in ignore_keywords)]
        
        preferred_order = [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "llama-3.1-70b-versatile",
            "mixtral-8x7b-32768"
        ]
        sorted_models = [m for m in preferred_order if m in chat_models] + [m for m in chat_models if m not in preferred_order]
        return sorted_models if sorted_models else fallback_models
    except Exception as e:
        print(f"[GROQ LIST MODELS ERROR]: {e}")
        return fallback_models

async def generate_agent_reply(user_message: str, history: Optional[List[Dict[str, str]]] = None) -> str:
    if not user_message or not user_message.strip():
        return "Namaste! 👋 Main Xytralyn AI assistant hoon. Aaj aapki kya sahayata kar sakta hoon?"

    client = get_async_groq_client()
    if client is None:
        return "Dhanyavaad! 🙏 Hamari team aapki query check karke aapse jaldi contact karegi."

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Only include recent context to avoid topic lock
    if history and isinstance(history, list):
        for msg in history[-4:]:
            messages.append(msg)

    messages.append({"role": "user", "content": user_message.strip()})

    available_models = await get_available_chat_models(client)

    for model_id in available_models:
        try:
            completion = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                temperature=0.3,
                max_tokens=600
            )
            reply = completion.choices[0].message.content
            if reply and reply.strip():
                # Strip trailing sign-offs without cutting genuine body sentences
                cleaned_reply = re.sub(r'(?i)\n+(regards|sincerely|best regards|thanks & regards)[\s\S]*$', '', reply.strip()).strip()
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
    text = user_message.lower().strip()
    
    # Ignore purely casual greetings or single-word texts
    greetings = {"hi", "hello", "hey", "namaste", "hlo", "hii", "hiii", "yo", "kya haal hai"}
    if text in greetings:
        return False

    lead_keywords = [
        "price", "pricing", "cost", "demo", "interested", "buy",
        "purchase", "service", "automation", "whatsapp bot", "ai agent",
        "website", "web development", "need", "requirement", "quotation"
    ]
    return any(re.search(rf"\b{re.escape(keyword)}\b", text) for keyword in lead_keywords)