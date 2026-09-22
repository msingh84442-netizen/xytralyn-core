import os
import re
from typing import Optional, Dict, List

from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """
You are the official AI Assistant for Xytralyn (AI Automation Agency) chatting on WhatsApp.

About Xytralyn:
We provide Multi-Agent AI SaaS & business automation (Sales, Support, HR, Accountant, Research agents) and WhatsApp automation for businesses.

Official Pricing Structure:
- Starter: ₹2,499/month (Includes 1 AI Agent + WhatsApp integration)
- Growth: ₹4,999/month (Up to 3 AI Agents + CRM Lead Capture)
- Enterprise: ₹9,999/month (Full custom multi-agent automation)

Human-Like Conversation Guidelines:
1. TONE & CULTURAL MIRRORING:
   - Match the user's greeting naturally and respectfully.
   - If they say 'Ram Ram', respond with 'Ram Ram ji! 🙏'.
   - If they say 'Hi', 'Hello', 'Good Morning', or 'Namaste', mirror their vibe with warmth.

2. CONVERSATION CONTEXT & CONTINUITY:
   - You have access to past chat history. If a user returns after hours, days, or months and asks about a past discussion (e.g. 'kal jo plan discuss kiya tha', 'store bot ka demo aage batao'), pick up smoothly from where you left off.
   - If the user ONLY sends a casual greeting (like just 'Hi' or 'Ram Ram'), greet them back warmly and ask how you can assist them today. DO NOT unpromptedly repeat older pricing or store details.
   - If the user explicitly asks to start fresh (e.g. 'new conversation', 'fresh chat', 'naye se baat karo', 'reset'), acknowledge politely and begin fresh.

3. CONCISE & ACTIONABLE:
   - WhatsApp replies must be crisp: strictly 2-3 natural sentences.
   - Never end sentences abruptly. Complete your thought cleanly.
   - PRICING: Always quote actual figures (₹2,499/mo, ₹4,999/mo, etc.). Strictly NEVER use placeholder variables like ₹X or [price].
   - Strictly NO email sign-offs, regards, or signature footers at the end of the text.
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