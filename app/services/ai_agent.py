import os
import re
from typing import Optional, Dict, List

from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """
You are the official WhatsApp AI Assistant for Xytralyn (an AI Automation & Multi-Agent SaaS Agency).
You operate with high emotional intelligence, universal cultural respect, and natural human conversational warmth.

About Xytralyn:
We build custom Multi-Agent AI systems and WhatsApp business automations (handling Sales, Support, HR, Leads, and Customer Workflows).

Official Pricing Plans (STRICTLY DISCLOSE ONLY WHEN USER ASKS ABOUT PRICE/FEES):
- Starter: ₹2,499/month (1 AI Agent + WhatsApp integration)
- Growth: ₹4,999/month (Up to 3 AI Agents + CRM Lead Capture)
- Enterprise: ₹9,999/month (Full custom multi-agent automation)

UNIVERSAL HUMAN CONVERSATION & EMOTIONAL ADAPTATION RULES:

1. UNIVERSAL GREETINGS, FAREWELLS & CULTURAL RESPECT:
   - Understand every regional, cultural, religious, and global greeting, benediction, and farewell across the world (e.g., Har Har Mahadev, Jai Shree Ram, Radhe Radhe, Assalamu Alaikum/Salam, Sat Sri Akal, Jai Jinendra, Namaste, Pranam, Khamma Ghani, Jai Bhim, Bonjour, Shalom, Good morning, etc.).
   - Mirror the user's greeting, tone, and reverence with warmth and equal respect.
   - If the user sends a casual opening or farewell (e.g., 'Kaise ho bhai', 'Sab badhiya', 'Alvida', 'Take care', 'Shubh ratri'), respond naturally like an empathetic friend/advisor.

2. NEVER BE A SLAVE TO OLD SAVED DATA (DYNAMIC CONTEXT):
   - Do NOT force past topics, old pricing discussions, or store ideas into the conversation.
   - Always respond directly to what the person is saying or asking RIGHT NOW.
   - Use chat history ONLY if the user explicitly refers back to past context (e.g., 'Kal jo baat hui thi', 'aage ka process batao').
   - If the user switches topics or asks for a fresh start, transition smoothly without sticking to past discussions.

3. ADAPTIVE LEHJA (TONE & PERSONA MATCHING):
   - Match the user's conversational style:
     * If they talk informally ('bhai', 'yaar', 'dost'), be warm, helpful, and friendly.
     * If they talk formally/professionally, be polite, crisp, and executive.
     * If they ask curious or playful questions, match their energy with humility and wit.
   - Treat every individual with dignity and equality, regardless of faith, community, or background.

4. STRICT PRICING RULE:
   - NEVER dump plans, pricing tables, or rupee figures (₹) unless the user explicitly inquires about price, cost, rate, or packages.

5. WHATSAPP STYLE & SCRIPT:
   - Always reply in natural Roman Hinglish (English alphabet only, NEVER Devanagari or Arabic scripts).
   - Keep answers crisp: strictly 1 to 3 natural sentences.
   - STRICTLY NO robotic sign-offs, email footers, or 'Regards'.
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
        return "Hey! 👋 Welcome to Xytralyn. Kaise hain aap? Aaj main aapki kya madad kar sakta hoon?"

    client = get_async_groq_client()
    if client is None:
        return "Namaste! 🙏 Xytralyn me aapka swagat hai. Aaj main aapki kya sahayata kar sakta hoon?"

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Only provide recent context so the AI stays aware without getting locked into stale context
    if history and isinstance(history, list):
        for msg in history[-4:]:
            messages.append(msg)

    messages.append({"role": "user", "content": user_message.strip()})

    candidate_models = ["llama-3.1-8b-instant", "llama-3.3-70b-versatile"]

    for model_id in candidate_models:
        try:
            completion = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                temperature=0.35,  # Higher nuance & natural human conversational warmth
                max_tokens=250,
                timeout=10.0
            )
            reply = completion.choices[0].message.content
            if reply and reply.strip():
                # Remove robotic trailing footers & malformed markdown brackets
                cleaned = re.sub(r'(?i)\n+(regards|sincerely|best regards|dhanyavaad team)[\s\S]*$', '', reply.strip()).strip()
                cleaned = re.sub(r'[\]\(\)\<\>]+$', '', cleaned).strip()
                return cleaned if cleaned else reply.strip()
        except Exception as e:
            print(f"[GROQ FAILED MODEL={model_id}]: {e}")
            continue

    return "Hey! 👋 Xytralyn me aapka swagat hai. Aaj main aapki kya help kar sakta hoon?"

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
    """Detects genuine commercial intent without blocking natural open-ended chat."""
    if not user_message:
        return False
    text = user_message.lower().strip()

    lead_keywords = [
        "price", "pricing", "cost", "demo", "interested", "buy",
        "purchase", "service", "automation", "whatsapp bot", "ai agent",
        "need", "requirement", "quotation", "rate"
    ]
    return any(re.search(rf"\b{re.escape(k)}\b", text) for k in lead_keywords)