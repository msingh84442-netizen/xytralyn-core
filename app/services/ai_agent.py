import os
import re
from typing import Optional, Dict, List

from groq import Groq
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """
You are Xytralyn AI Sales & Assistance Agent for a Multi-Agent AI SaaS & Automation platform.

About Xytralyn:
We build and deploy specialized autonomous AI agents and WhatsApp automation for businesses:
1. Sales Agent: 24/7 lead qualification, booking demos, customer questions
2. Support Agent: FAQ answering, issue logging, ticket creation
3. HR Agent: Automated screening, interview questions, internal queries
4. Accountant Agent: Invoice processing, GST calculations, expense tracking
5. Research Agent: Market analysis, competitor research, content generation

Strict Memory & Context Rules:
- If the customer has ALREADY provided their name, phone number, or email in previous messages, NEVER ask for them again. Acknowledge and confirm their details.
- Reply in clear, polite, and natural Hinglish (Hindi + English).
- Strictly keep responses within 2-3 short sentences.
- When scheduling a demo, confirm the time directly (e.g., "Demo booked for tomorrow at 3:00 PM. We will send the Google Meet link to your shared email.")
- Never make up fake prices, features, or guarantees.
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

    # Messages array with System Prompt
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Agar previous conversation history provide ki gayi ho, toh use context mein add karein
    if history and isinstance(history, list):
        for msg in history[-6:]:  # Last 6 messages for context
            messages.append(msg)

    # Current user message
    messages.append({"role": "user", "content": user_message.strip()})

    available_models = get_available_chat_models(client)

    for model_id in available_models:
        try:
            print(f"[GROQ ATTEMPT]: Trying model {model_id}")
            completion = client.chat.completions.create(
                model=model_id,
                messages=messages,
                temperature=0.5,
                max_tokens=220
            )
            reply = completion.choices[0].message.content
            if reply and reply.strip():
                print(f"[GROQ SUCCESS]: Reply generated using {model_id}")
                return reply.strip()
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