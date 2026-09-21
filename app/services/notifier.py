import requests

# Verified Green-API Endpoint
URL = "https://7107.api.greenapi.com/waInstance710722741454/sendMessage/96a0163ea636448298b3fa9c7b96c8b6c4ecf8f021a04f59b2"
ADMIN_CHAT_ID = "917380930501@c.us"

def send_admin_alert(lead_name: str, company: str, phone: str):
    """
    Sends instant WhatsApp lead alert to Admin via Green-API.
    """
    alert_text = (
        f"🚨 *NEW HOT LEAD DETECTED* 🚨\n\n"
        f"👤 *Name:* {lead_name}\n"
        f"🏢 *Company:* {company}\n"
        f"📞 *Phone:* {phone}\n\n"
        f"⚡ *Status:* Instant Follow-up Required"
    )

    payload = {
        "chatId": ADMIN_CHAT_ID,
        "message": alert_text
    }

    headers = {
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(URL, json=payload, headers=headers, timeout=10)
        data = response.json()
        
        if response.status_code == 200 and "idMessage" in data:
            print(f"\033[92m[ADMIN NOTIFIED VIA WHATSAPP SUCCESSFULLY]: ID={data['idMessage']}\033[0m")
            return data["idMessage"]
        else:
            print(f"\033[91m[GREEN-API ERROR {response.status_code}]: {response.text}\033[0m")
            return None

    except Exception as e:
        print(f"\033[91m[ALERT FATAL ERROR]: {e}\033[0m")
        return None