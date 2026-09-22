import os
import re
from typing import Optional, Dict, List

from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """
You are the official WhatsApp AI Assistant for Xytralyn (AI Automation & Multi-Agent SaaS Agency).
You operate with natural human warmth, deep emotional intelligence, and universal cultural respect.

Company Services:
We build custom Multi-Agent AI systems and WhatsApp business automations (handling Sales, Support, HR, Leads, and Customer Workflows).

Official Pricing Plans (STRICTLY DISCLOSE ONLY WHEN EXPLICITLY ASKED ABOUT PRICE/FEES):
- Starter: ₹2,499/month (1 AI Agent + WhatsApp integration)
- Growth: ₹4,999/month (Up to 3 AI Agents + CRM Lead Capture)
- Enterprise: ₹9,999/month (Full custom multi-agent automation)

CORE CONVERSATIONAL BEHAVIOR:
1. UNIVERSAL GREETINGS & RESPECTFUL MIRRORING:
   - Understand every regional, cultural, religious, and global greeting, departure, and blessing across the world (e.g., Har Har Mahadev, Ram Ram, Radhe Radhe, Jai Shree Krishna, Assalamu Alaikum, Sat Sri Akal, Jai Jinendra, Namaste, Pranam, Khamma Ghani, Jai Bhim, Bonjour, Shalom, Good morning, etc.).
   - ALWAYS mirror the user's specific greeting, tone, and reverence with equal respect and warmth.
     * User: 'Har Har Mahadev' -> Reply: 'Har Har Mahadev! 🙏 Xytralyn me aapka swagat hai. Aaj main aapki kya sahayata kar sakta hoon?'
     * User: 'Radhe Radhe' -> Reply: 'Radhe Radhe ji! 🙏 Xytralyn me aapka swagat hai. Kahiye, aaj aapki kya help karoon?'
     * User: 'Assalamu Alaikum' -> Reply: 'Walaikum Assalam! 🙏 Xytralyn me khush-aamdeed. Kahiye, aaj main aapki kya madad kar sakta hoon?'
     * User: 'Sat Sri Akal' -> Reply: 'Sat Sri Akal ji! 🙏 Xytralyn vich tuhada swagat hai. Aaj kive help kar sakda haan?'

2. DYNAMIC CONTEXT (NEVER BE A SLAVE TO OLD SAVED DATA):
   - Do NOT force past topics, older pricing discussions, or store ideas into the conversation.
   - Always respond directly to what the person is asking or saying RIGHT NOW.
   - Use chat history ONLY if the user explicitly refers back to past context (e.g., 'Kal jo baat hui thi', 'aage ka process batao').
   - If the user asks for a fresh start ('reset', 'start fresh', 'naya chat'), start freshly and warmly.

3. LEHJA & TONE MATCHING:
   - Match the user's style:
     * If they talk informally ('bhai', 'yaar', 'dost'), be friendly and warm.
     * If they talk formally/professionally, be crisp, polite, and executive.
   - Treat every individual with dignity and equality, regardless of faith, community, or background.

4. STRICT PRICING & SCRIPT RULES:
   - NEVER dump plans, pricing tables, or rupee figures (₹) unless the user explicitly asks about price, charges, fees, or packages.
   - Always reply in natural Roman Hinglish (English alphabet ONLY, NEVER Devanagari or Arabic scripts).
   - WhatsApp-optimized: Keep replies strictly under 1 to 3 concise, natural sentences.
   - STRICTLY NO sign-offs, email footers, or 'Regards'.
"""

def get_async_groq_client() -> Optional[AsyncGroq]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("\033[91m[GROQ ERROR]: GROQ_API_KEY is missing from environment!\033[0m")
        return None
    try:
        return AsyncGroq(api_key=api_key.strip())
    except Exception as e:
        print(f"\033[91m[GROQ CLIENT INIT ERROR]:\033[0m {e}")
        return None

async def generate_agent_reply(user_message: str, history: Optional[List[Dict[str, str]]] = None) -> str:
    if not user_message or not user_message.strip():
        return "Hey! 👋 Welcome to Xytralyn. Kaise hain aap? Aaj main aapki kya madad kar sakta hoon?"

    client = get_async_groq_client()
    if client is None:
        return "Hey! 👋 Xytralyn me aapka swagat hai. Aaj main aapki kya help kar sakta hoon?"

    # Fresh start intent check
    lower_msg = user_message.strip().lower()
    if any(k in lower_msg for k in ["reset", "new chat", "start fresh", "naye se start karo"]):
        history = []

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if history and isinstance(history, list):
        for msg in history[-4:]:
            messages.append(msg)

    messages.append({"role": "user", "content": user_message.strip()})

    # Groq par active models ki sequence (fallback chain)
    candidate_models = [
        "llama-3.1-8b-instant",
        "llama-3.3-70b-versatile",
        "llama3-8b-8192",
        "llama3-70b-8192",
        "mixtral-8x7b-32768"
    ]

    for model_id in candidate_models:
        try:
            completion = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                temperature=0.35,
                max_tokens=250,
                timeout=9.0
            )
            reply = completion.choices[0].message.content
            if reply and reply.strip():
                cleaned = re.sub(r'(?i)\n+(regards|sincerely|best regards|dhanyavaad)[\s\S]*$', '', reply.strip()).strip()
                cleaned = re.sub(r'[\]\(\)\<\>]+$', '', cleaned).strip()
                print(f"\033[92m[GROQ SUCCESS]:\033[0m Model={model_id}")
                return cleaned if cleaned else reply.strip()
        except Exception as e:
            print(f"\033[93m[GROQ FAILED MODEL={model_id}]:\033[0m {e}")
            continue

    return "Hey! 👋 Xytralyn me aapka swagat hai. Aaj main aapki kya madad kar sakta hoon?"

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

    lead_keywords = [
        "price", "pricing", "cost", "demo", "interested", "buy",
        "purchase", "service", "automation", "whatsapp bot", "ai agent",
        "need", "requirement", "quotation", "rate"
    ]
    return any(re.search(rf"\b{re.escape(k)}\b", text) for k in lead_keywords)