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

Your Guidelines:
- Reply in clear, polite, and natural Hinglish (Hindi + English).
- Strictly keep responses within 2-3 short sentences.
- Explain how Xytralyn helps automate business operations and WhatsApp workflows.
- Encourage interested customers to share requirements or book a demo.
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
    """Dynamically fetch all active text-chat models from Groq account."""
    try:
        models_data = client.models.list()
        active_ids = [m.id for m in models_data.data if m.active]
        # Prefer llama or mistral chat models, ignore whisper/audio/embeddings
        chat_models = [m for m in active_ids if "whisper" not in m and "vision" not in m]
        print(f"[GROQ AVAILABLE MODELS]: {chat_models}")
        return chat_models
    except Exception as e:
        print(f"[GROQ LIST MODELS ERROR]: {e}")
        return ["mixtral-8x7b-32768"]

def generate_agent_reply(user_message: str) -> str:
    if not user_message or not user_message.strip():
        return "Namaste! 👋 Main Xytralyn AI assistant hoon. Aapko kis service ya agent ke baare mein janna hai?"

    client = get_groq_client()
    if client is None:
        return "Dhanyavaad! 🙏 Hamari team aapki query check karke aapse jaldi contact karegi."

    available_models = get_available_chat_models(client)

    for model_id in available_models:
        try:
            print(f"[GROQ ATTEMPT]: Trying model {model_id}")
            completion = client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message.strip()}
                ],
                temperature=0.6,
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