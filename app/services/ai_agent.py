import os
import re
from typing import Optional, Dict, List

from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """
You are the official WhatsApp AI Assistant for Xytralyn (AI Automation Agency).

About Xytralyn:
We build Multi-Agent AI SaaS and WhatsApp automation for businesses.

Official Pricing (ONLY IF SPECIFICALLY ASKED):
- Starter: ₹2,499/mo (1 Agent + WhatsApp)
- Growth: ₹4,999/mo (3 Agents + CRM)
- Enterprise: ₹9,999/mo (Custom multi-agent)

CRITICAL RULES:
1. LANGUAGE: Always reply in Roman English / Hinglish using English alphabet ONLY. Never use Arabic or Devanagari script.
2. NO UNASKED PRICING: Strictly DO NOT mention pricing, plans, or rupees (₹) UNLESS the user explicitly asks about price, cost, or plans.
3. BREVITY: Keep answers strictly under 2 concise, natural sentences.
4. NO SIGN-OFFS: Never end with Regards, Sincerely, or name footers.
"""

def get_async_groq_client() -> Optional[AsyncGroq]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("[GROQ ERROR]: GROQ_API_KEY is missing!")
        return None
    try:
        return AsyncGroq(api_key=api_key.strip())
    except Exception as e:
        print(f"[GROQ CLIENT INIT ERROR]: {e}")
        return None

async def generate_agent_reply(user_message: str, history: Optional[List[Dict[str, str]]] = None) -> str:
    if not user_message or not user_message.strip():
        return "Hey! 👋 Welcome to Xytralyn. How can I help you today?"

    client = get_async_groq_client()
    if client is None:
        return "Hey! 👋 Welcome to Xytralyn. Hum business automation provide karte hain. Aaj aapki kya help kar sakta hoon?"

    # Check for reset intent
    lower_msg = user_message.strip().lower()
    if any(k in lower_msg for k in ["reset", "new chat", "start fresh"]):
        history = []

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if history and isinstance(history, list):
        for msg in history[-4:]:
            messages.append(msg)

    messages.append({"role": "user", "content": user_message.strip()})

    # Sabse fast aur reliable Groq models
    candidate_models = ["llama-3.1-8b-instant", "llama-3.3-70b-versatile"]

    for model_id in candidate_models:
        try:
            completion = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                temperature=0.2,
                max_tokens=250,
                timeout=8.0
            )
            reply = completion.choices[0].message.content
            if reply and reply.strip():
                cleaned = re.sub(r'(?i)\n+(regards|sincerely|best regards)[\s\S]*$', '', reply.strip()).strip()
                cleaned = re.sub(r'[\]\(\)\<\>]+$', '', cleaned).strip()
                return cleaned if cleaned else reply.strip()
        except Exception as e:
            print(f"\033[91m[GROQ FAILED FOR MODEL {model_id}]:\033[0m {e}")
            continue

    # Clean default fallback agar API down bhi ho:
    return "Hey! 👋 Xytralyn me aapka swagat hai. Hum WhatsApp & AI automation banate hain. Aap kis requirement ke liye check kar rahe hain?"

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

    return lead_data

def is_potential_lead(user_message: str) -> bool:
    if not user_message:
        return False
    text = user_message.lower().strip()
    
    casual_words = {
        "hi", "hello", "hey", "namaste", "hlo", "hii", "hiii", "yo",
        "ram ram", "radhe radhe", "jai shree ram", "ashlaa valekum", "walaikum assalam"
    }
    cleaned_input = re.sub(r"[^\w\s]", "", text).strip()
    if cleaned_input in casual_words:
        return False

    lead_keywords = [
        "price", "pricing", "cost", "demo", "interested", "buy",
        "purchase", "service", "automation", "whatsapp bot", "ai agent",
        "need", "requirement"
    ]
    return any(re.search(rf"\b{re.escape(k)}\b", text) for k in lead_keywords)