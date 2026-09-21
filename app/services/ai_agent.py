import os
from groq import Groq

def get_groq_client():
    # Environment variable ka exact naam yahan aayega
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
            model="llama-3.3-70b-versatile",
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
        # Secondary fallback model
        try:
            fallback_res = client.chat.completions.create(
                model="llama-3.1-8b-instant",
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