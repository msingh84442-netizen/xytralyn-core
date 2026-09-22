import os
import re
from typing import Optional, Dict, List

from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """
You are the WhatsApp AI Assistant for Xytralyn (AI Automation Agency).

About Xytralyn:
We build Multi-Agent AI SaaS and WhatsApp automation for businesses (Sales, Support, HR, Leads).

Pricing (ONLY IF ASKED):
- Starter: ₹2,499/mo (1 Agent + WhatsApp)
- Growth: ₹4,999/mo (3 Agents + CRM)
- Enterprise: ₹9,999/mo (Custom multi-agent)

CRITICAL BEHAVIOR RULES:
1. NEVER DUMP PRICING UNASKED: Strictly DO NOT mention pricing, plans, or rupees (₹) UNLESS the user explicitly asks about price, cost, or charges. Mentioning pricing during simple greetings or random questions is strictly prohibited.
2. NATURAL GREETINGS:
   - If user says 'Salam' / 'Ashlaa valekum' -> Reply warmly: 'Walaikum Assalam bhai! Kaise hain aap? Xytralyn me aapka swagat hai. Aaj aapki kya help kar sakta hoon?'
   - If user says 'Ram Ram' -> Reply: 'Ram Ram ji! 🙏 Xytralyn me swagat hai. Aaj aapki kya help kar sakta hoon?'
   - If user says 'Hi' / 'Hii' / 'Hello' -> Reply: 'Hey! 👋 Welcome to Xytralyn. How can I help you today?'
3. LANGUAGE: Always reply in natural, casual Roman Hinglish (English alphabet only, NEVER Devanagari script).
4. LENGTH: Strictly 1 to 2 short sentences. No long essays.
5. NO FOOTERS: Never add 'Regards', 'Sincerely', or assistant sign-offs.
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
        return "Namaste! 🙏 Main Xytralyn AI assistant hoon. Aaj aapki kya sahayata kar sakta hoon?"

    client = get_async_groq_client()
    if client is None:
        return "Dhanyavaad! 🙏 Hamari team aapki query check karke aapse jaldi contact karegi."

    # Check for explicit reset intent
    lower_msg = user_message.strip().lower()
    reset_keywords = ["reset", "new chat", "clear history", "start fresh", "naye se start karo"]
    if any(k in lower_msg for k in reset_keywords):
        history = []

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if history and isinstance(history, list):
        for msg in history[-8:]:  # Memory depth for ongoing context
            messages.append(msg)

    messages.append({"role": "user", "content": user_message.strip()})

    available_models = await get_available_chat_models(client)

    for model_id in available_models:
        try:
            completion = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                temperature=0.35,
                max_tokens=600
            )
            reply = completion.choices[0].message.content
            if reply and reply.strip():
                # Strip trailing sign-offs & broken brackets safely
                cleaned_reply = re.sub(r'(?i)\n+(regards|sincerely|best regards|thanks & regards)[\s\S]*$', '', reply.strip()).strip()
                cleaned_reply = re.sub(r'[\]\(\)\<\>]+$', '', cleaned_reply).strip()
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
    
    # Casual greetings list to ignore
    casual_words = {
        "hi", "hello", "hey", "namaste", "hlo", "hii", "hiii", "yo", "hola",
        "ram ram", "radhe radhe", "jai shree ram", "pranam", "kya haal hai", "good morning"
    }
    cleaned_input = re.sub(r"[^\w\s]", "", text).strip()
    if cleaned_input in casual_words:
        return False

    lead_keywords = [
        "price", "pricing", "cost", "demo", "interested", "buy",
        "purchase", "service", "automation", "whatsapp bot", "ai agent",
        "website", "web development", "need", "requirement", "quotation"
    ]
    return any(re.search(rf"\b{re.escape(k)}\b", text) for k in lead_keywords)