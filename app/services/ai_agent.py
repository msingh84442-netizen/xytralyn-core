import os
import re
from groq import Groq

def get_groq_client():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    return Groq(api_key=api_key)

def generate_agent_reply(user_message: str) -> str:
    client = get_groq_client()
    if not client:
        return "Dhanyavaad! Hamari team aapko jald hi contact karegi."

    prompt = (
        "You are a helpful AI assistant for an AI agency. "
        "Answer the customer's query clearly, politely, and concisely in Hinglish (Hindi + English). "
        "Explain services like AI automation, WhatsApp bots, and web development. Keep it under 2-3 sentences."
    )

    try:
        completion = client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7,
            max_tokens=200
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"[GROQ ERROR]: {e}")
        try:
            fallback_res = client.chat.completions.create(
                model="llama3-8b-8192",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.7,
                max_tokens=150
            )
            return fallback_res.choices[0].message.content.strip()
        except Exception as fb_e:
            print(f"[GROQ FALLBACK ERROR]: {fb_e}")
            return "Thanks for reaching out! Our team will contact you shortly."

def extract_lead_info(user_message: str) -> dict:
    lead_data = {"name": None, "phone": None, "email": None}
    
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', user_message)
    if email_match:
        lead_data["email"] = email_match.group(0)

    phone_match = re.search(r'(\+?\d{10,13})', user_message)
    if phone_match:
        lead_data["phone"] = phone_match.group(0)

    return lead_data