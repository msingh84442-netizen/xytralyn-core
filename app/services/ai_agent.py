import os
import re
from typing import Optional, Dict, List

from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """
You are the official AI Assistant for Xytralyn chatting on WhatsApp.

About Xytralyn:
We provide Multi-Agent AI SaaS & business automation (Sales, Support, HR, Accountant, Research agents) and WhatsApp automation for businesses.

Official Pricing Structure:
- Starter: ₹2,499/month (1 AI Agent + WhatsApp integration)
- Growth: ₹4,999/month (Up to 3 AI Agents + CRM)
- Enterprise: ₹9,999/month (Full custom automation)

Strict WhatsApp Guidelines:
- Reply in natural, friendly Hinglish (Hindi + English).
- Limit responses strictly to 1-3 complete sentences.
- DIVERSITY & NATURAL TONE: DO NOT start every message with "Sure!" or "Sure! Our pricing". Reply like a real human.
- GREETING RESET: If the user says "Hi", "Hello", or "Apni details batao", greet them warmly and introduce Xytralyn's services fresh. Do NOT cling to older topics (like store pricing) unless the user brings it up again.
- PRICING: If asked about price, mention the starting range (₹2,499/mo) and customize from there. Never use dummy placeholders like ₹X.
- Strictly NO email signatures or footers.
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
        
        preferred_order = [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "openai/gpt-oss-20b",
            "openai/gpt-oss-120b"
        ]
        sorted_models = [m for m in preferred_order if m in chat_models] + [m for m in chat_models if m not in preferred_order]
        
        return sorted_models if sorted_models else ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    except Exception as e:
        print(f"[GROQ LIST MODELS ERROR]: {e}")
        return ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

async def generate_agent_reply(user_message: str, history: Optional[List[Dict[str, str]]] = None) -> str:
    if not user_message or not user_message.strip():
        return "Namaste! 👋 Main Xytralyn AI assistant hoon. Aapki kya sahayata kar sakta hoon?"

    client = get_async_groq_client()
    if client is None:
        return "Dhanyavaad! 🙏 Hamari team aapki query check karke aapse jaldi contact karegi."

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if history and isinstance(history, list):
        for msg in history[-8:]:
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
                # Sirf trailing newline sign-offs hatane ke liye (beech ke text ko bina kaate):
                cleaned_reply = re.sub(r'(?i)\n+(regards|sincerely|best regards)[\s\S]*$', '', reply.strip()).strip()
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
    
    # Casual greetings ko ignore karein
    greetings = ["hi", "hello", "hey", "namaste", "hlo", "hii", "hiii"]
    if text in greetings:
        return False

    lead_keywords = [
        "price", "pricing", "cost", "demo", "interested", "buy",
        "purchase", "service", "automation", "whatsapp bot", "ai agent",
        "website", "web development", "need", "requirement", "business"
    ]
    return any(keyword in text for keyword in lead_keywords)