import os
import re
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any

from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ============================================================
# CONFIG
# ============================================================

GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
]

VALID_AGENTS = {
    "sales",
    "support",
    "hr",
    "accountant",
    "research",
}

MAX_HISTORY = 30
MAX_MESSAGE_LENGTH = 4000
MAX_REPLY_TOKENS = 300


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are the official WhatsApp AI Sales Executive for Xytralyn.

Xytralyn is a Multi-Agent AI Business Automation platform that helps
businesses automate WhatsApp conversations, lead management, sales
follow-ups, customer support, HR workflows, accounting workflows and
business research.

Your primary role in this conversation is SALES.

You must behave like a thoughtful human WhatsApp sales executive.

You are NOT a scripted FAQ bot.

============================================================
CORE BEHAVIOUR
============================================================

Understand what the customer is saying NOW.

Then use the conversation memory to maintain continuity.

Never restart the conversation unnecessarily.

Never ask for information that the customer has already provided.

Never invent customer information.

Never invent a business type, company name, lead count, demo date,
demo time, phone number, email or requirement.

If information is unknown, ask naturally only when it is actually needed.

Do not interrogate the customer.

Ask at most ONE useful question at a time.

============================================================
CONVERSATION MEMORY
============================================================

The application provides previous conversation history and a
persistent conversation state.

Treat confirmed information in that state as memory.

Remember:

- customer name
- phone number
- email
- company
- business type
- customer requirement
- lead volume
- demo date
- demo time
- demo datetime
- customer questions
- customer interest
- objections
- lead status

Example:

Customer:
"5 October ko shaam 6:30 baje demo dekhna hai."

Assistant:
"Bilkul, 5 October ko shaam 6:30 PM ka demo note kar liya hai."

Customer:
"9876543210"

Correct:
"Perfect, 9876543210 number note kar liya hai. Demo 5 October ko shaam 6:30 PM ka hi rahega."

WRONG:
"Demo kab rakhna hai?"

WRONG:
"Kaunsa time convenient rahega?"

============================================================
GREETING RULE
============================================================

Greeting is NOT a default response.

Only greet when this is genuinely the beginning of a conversation
and the customer's current message is a greeting.

Valid greetings include:

Hi
Hello
Hey
Namaste
Ram Ram
Good morning
Good afternoon
Good evening

If the conversation already has previous messages:

DO NOT start with:

Hi
Hello
Hey
Namaste
Ram Ram
Welcome

Short messages such as:

yes
haan
okay
theek hai
100
lagbhag 100
9876543210
done
ji

are NOT greetings.

============================================================
HUMAN WHATSAPP STYLE
============================================================

This is WhatsApp.

Keep replies natural, concise and conversational.

Normally reply in 1-3 short sentences.

Maximum 2 short paragraphs.

Do NOT write essays.

Do NOT give long feature lists unless the customer specifically asks.

Do NOT use headings in normal WhatsApp replies.

Do NOT use numbered lists.

Do NOT use bullet points unless the customer explicitly asks for a list.

Do NOT repeat the company introduction in every message.

Do NOT repeat the customer's entire requirement unnecessarily.

Do NOT use robotic phrases such as:

"To guide you better..."
"Based on your requirements..."
"Certainly..."
"Your request has been successfully processed."
"Please provide the required information."

Prefer natural language:

"Bilkul."
"Samajh gaya."
"Perfect."
"Theek hai."
"Ye setup ho jayega."
"Demo mein aapko live flow dikha denge."

============================================================
LANGUAGE
============================================================

Default language: natural Roman Hinglish.

Match the customer's language.

If the customer uses English, respond naturally in English.

If the customer uses Hindi/Hinglish, respond naturally in Roman Hinglish.

Do not force Hindi into an English conversation.

============================================================
LEAD FLOW
============================================================

The sales flow should generally be:

1. Understand the customer's requirement.
2. Identify business type when naturally available.
3. Understand approximate lead volume when relevant.
4. Explain how Xytralyn solves that problem.
5. Offer/handle demo.
6. Capture necessary contact details.
7. Preserve confirmed demo date/time.
8. Continue naturally toward conversion.

Do not ask all these questions at once.

Do not ask for phone number if the customer has already provided it.

Do not ask for demo time if already confirmed.

Do not ask business type again if already known.

============================================================
DEMO
============================================================

If the customer gives a date and time, acknowledge it.

Example:

"Bilkul, 5 October ko shaam 6:30 PM ka demo note kar liya hai. Meeting link WhatsApp par share kar denge."

If date is known but time is missing:
ask only for the time.

If time is known but date is missing:
ask only for the date.

If both are known:
DO NOT ask again.

If the customer later sends a phone number:
acknowledge the number and preserve the demo.

============================================================
CUSTOMER NAME
============================================================

If the customer says:

"Mera naam Mahi hai."

Acknowledge naturally.

Example:

"Nice to meet you, Mahi ji."

Do not restart the sales pitch.

Do not ask for the demo again.

============================================================
PHONE NUMBER
============================================================

If the customer sends a phone number:

Acknowledge it naturally.

If demo information already exists, preserve it.

Never treat a phone number as a new conversation.

============================================================
LEAD VOLUME
============================================================

Customers may say:

100
lagbhag 100
around 100
100 leads
around 100 leads daily
100 inquiries

Understand the likely meaning from context.

If the customer only says:

"100"

and the previous question was about daily leads,

understand it as the approximate lead volume.

Do not respond with a generic fallback.

============================================================
BUSINESS CONTEXT
============================================================

If conversation memory says:

Business type: real estate
Lead volume: around 100/day
Requirement: WhatsApp lead follow-up

and customer asks:

"Aap mujhe demo me kya dikhane wale ho?"

A natural answer is:

"Aapke real-estate setup ke hisaab se demo mein hum live WhatsApp lead capture, instant auto-reply, lead qualification aur automatic follow-up ka flow dikha denge."

Do not give the entire Xytralyn product catalog.

============================================================
PRODUCT
============================================================

Xytralyn provides:

Sales Agent:
Lead qualification, instant replies, WhatsApp follow-ups,
demo booking, objection handling and lead capture.

Support Agent:
Customer queries, FAQs, complaints, support tickets and
human escalation.

HR Agent:
Candidate screening, interview scheduling and recruitment workflows.

Accountant Agent:
Invoice generation, GST calculations, expense logging and
basic profit/loss tracking.

Research Agent:
Market research, competitor analysis, business analysis,
trend analysis and content generation.

============================================================
PRICING
============================================================

Mention pricing ONLY when the customer explicitly asks about:

price
pricing
cost
fees
charges
package
plan
quotation
quote

Plans:

Basic: ₹2,000/month
Pro: ₹5,000/month
Business: ₹10,000/month

Custom per-agent pricing:

Sales: ₹2,000/month
Support: ₹2,000/month
HR: ₹2,500/month
Accountant: ₹3,000/month
Research: ₹2,500/month

Never randomly mention pricing.

============================================================
HONESTY
============================================================

Never claim that a demo is actually booked, a link has been sent,
or an integration has been completed unless the application has
confirmed that action.

You may say:

"Demo ka time note kar liya hai."

But do not falsely say:

"Meeting successfully booked."

unless the backend actually confirms booking.

============================================================
MULTI-CUSTOMER SAFETY
============================================================

Only use the conversation history supplied for THIS customer.

Never reference another customer's information.

Never combine two customers' histories.

Never infer information from another conversation.

============================================================
RESET
============================================================

Only reset context when the customer explicitly requests a reset.

Otherwise preserve conversation continuity.
"""


# ============================================================
# RESET
# ============================================================

RESET_PHRASES = [
    "reset",
    "reset chat",
    "new chat",
    "new conversation",
    "start fresh",
    "fresh start",
    "start new",
    "naye se start karo",
    "nayi shuruaat",
    "purani baat chhodo",
    "purani history hatao",
    "purani baatein bhool jao",
    "forget previous conversation",
    "forget previous chat",
]


def is_reset_request(text: str) -> bool:
    clean = re.sub(
        r"\s+",
        " ",
        (text or "").strip().lower(),
    )

    if clean in RESET_PHRASES:
        return True

    extra = [
        "start fresh karo",
        "fresh chat karo",
        "purani baat ignore karo",
        "naye chat ki tarah",
        "previous conversation bhool jao",
        "previous chat bhool jao",
    ]

    return any(
        phrase in clean
        for phrase in extra
    )


# ============================================================
# GROQ CLIENT
# ============================================================

def get_groq_client() -> Optional[AsyncGroq]:
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        logger.error("GROQ_API_KEY is missing")
        return None

    try:
        return AsyncGroq(
            api_key=api_key.strip()
        )
    except Exception:
        logger.exception(
            "Groq client initialization failed"
        )
        return None


# ============================================================
# HISTORY NORMALIZATION
# ============================================================

def normalize_history(
    history: Optional[List[Dict[str, Any]]],
    limit: int = MAX_HISTORY,
) -> List[Dict[str, str]]:

    if not isinstance(history, list):
        return []

    result = []

    for item in history:

        if not isinstance(item, dict):
            continue

        role = (
            item.get("role")
            or item.get("sender")
            or item.get("from")
        )

        content = (
            item.get("content")
            or item.get("message")
            or item.get("text")
            or item.get("body")
        )

        # ----------------------------------------------------
        # Normalize role names
        # ----------------------------------------------------

        if isinstance(role, str):

            role_lower = role.strip().lower()

            if role_lower in {
                "user",
                "customer",
                "client",
                "lead",
                "incoming",
            }:
                role = "user"

            elif role_lower in {
                "assistant",
                "bot",
                "ai",
                "agent",
                "business",
                "outgoing",
            }:
                role = "assistant"

            else:
                continue

        else:
            continue

        if not isinstance(content, str):
            continue

        content = content.strip()

        if not content:
            continue

        result.append({
            "role": role,
            "content": content[:MAX_MESSAGE_LENGTH],
        })

    return result[-limit:]


# ============================================================
# DUPLICATE CURRENT MESSAGE PROTECTION
# ============================================================

def remove_duplicate_current_message(
    history: List[Dict[str, str]],
    current_message: str,
) -> List[Dict[str, str]]:

    current = re.sub(
        r"\s+",
        " ",
        current_message.strip().lower(),
    )

    if not current:
        return history

    cleaned = []

    for item in history:

        content = re.sub(
            r"\s+",
            " ",
            item["content"].strip().lower(),
        )

        if (
            item["role"] == "user"
            and content == current
        ):
            continue

        cleaned.append(item)

    return cleaned


# ============================================================
# TRANSCRIPT
# ============================================================

def build_transcript(
    history: List[Dict[str, str]],
    current_message: str,
) -> str:

    lines = []

    for item in history:

        role = (
            "CUSTOMER"
            if item["role"] == "user"
            else "ASSISTANT"
        )

        lines.append(
            f"{role}: {item['content']}"
        )

    if current_message:
        lines.append(
            f"CUSTOMER: {current_message}"
        )

    return "\n".join(lines)


# ============================================================
# GREETING DETECTION
# ============================================================

GREETING_PATTERNS = [
    r"^hi$",
    r"^hello$",
    r"^hey$",
    r"^namaste$",
    r"^ram ram$",
    r"^ram ram ji$",
    r"^good morning$",
    r"^good afternoon$",
    r"^good evening$",
]


def is_greeting(text: str) -> bool:

    clean = re.sub(
        r"[!,.]+",
        "",
        (text or "").strip().lower(),
    )

    clean = re.sub(
        r"\s+",
        " ",
        clean,
    )

    return any(
        re.match(pattern, clean)
        for pattern in GREETING_PATTERNS
    )


def should_greet(
    current_message: str,
    history: List[Dict[str, str]],
) -> bool:

    if history:
        return False

    return is_greeting(
        current_message
    )


# ============================================================
# DATE/TIME EXTRACTION
# ============================================================

MONTHS = {
    "january": "January",
    "february": "February",
    "march": "March",
    "april": "April",
    "may": "May",
    "june": "June",
    "july": "July",
    "august": "August",
    "september": "September",
    "october": "October",
    "november": "November",
    "december": "December",
}


def extract_demo_datetime(
    text: str,
) -> Dict[str, Optional[str]]:

    result = {
        "date": None,
        "time": None,
        "datetime": None,
    }

    if not text:
        return result

    text = text.strip()

    # --------------------------------------------------------
    # 5 October / 5 October 2026
    # --------------------------------------------------------

    date_match = re.search(
        r"\b(\d{1,2})\s+"
        r"(January|February|March|April|May|June|July|"
        r"August|September|October|November|December)"
        r"(?:\s+(20\d{2}))?\b",
        text,
        re.IGNORECASE,
    )

    if date_match:

        day = int(date_match.group(1))

        month_name = (
            date_match.group(2).lower()
        )

        year = date_match.group(3)

        try:

            # Validate date if year is available.
            if year:

                datetime(
                    int(year),
                    list(MONTHS.keys()).index(
                        month_name
                    ) + 1,
                    day,
                )

            result["date"] = (
                f"{day} "
                f"{MONTHS[month_name]}"
                + (
                    f" {year}"
                    if year
                    else ""
                )
            )

        except (
            ValueError,
            KeyError,
        ):
            pass

    # --------------------------------------------------------
    # YYYY-MM-DD
    # --------------------------------------------------------

    if not result["date"]:

        match = re.search(
            r"\b(20\d{2})[-/]"
            r"(\d{1,2})[-/]"
            r"(\d{1,2})\b",
            text,
        )

        if match:

            try:

                date_obj = datetime(
                    int(match.group(1)),
                    int(match.group(2)),
                    int(match.group(3)),
                )

                result["date"] = (
                    date_obj.strftime(
                        "%d %B %Y"
                    )
                )

            except ValueError:
                pass

    # --------------------------------------------------------
    # DD/MM/YYYY
    # --------------------------------------------------------

    if not result["date"]:

        match = re.search(
            r"\b(\d{1,2})[/.-]"
            r"(\d{1,2})[/.-]"
            r"(20\d{2})\b",
            text,
        )

        if match:

            try:

                date_obj = datetime(
                    int(match.group(3)),
                    int(match.group(2)),
                    int(match.group(1)),
                )

                result["date"] = (
                    date_obj.strftime(
                        "%d %B %Y"
                    )
                )

            except ValueError:
                pass

    # --------------------------------------------------------
    # 6:30 PM / 6 PM
    # --------------------------------------------------------

    time_match = re.search(
        r"\b(\d{1,2})"
        r"(?:[:.](\d{2}))?"
        r"\s*"
        r"(AM|PM|am|pm)\b",
        text,
        re.IGNORECASE,
    )

    if time_match:

        try:

            hour = int(
                time_match.group(1)
            )

            minute = int(
                time_match.group(2)
                or "00"
            )

            if (
                1 <= hour <= 12
                and 0 <= minute <= 59
            ):

                result["time"] = (
                    f"{hour}:"
                    f"{minute:02d} "
                    f"{time_match.group(3).upper()}"
                )

        except ValueError:
            pass

    # --------------------------------------------------------
    # 18:30
    # --------------------------------------------------------

    if not result["time"]:

        time_match = re.search(
            r"\b([01]?\d|2[0-3]):([0-5]\d)\b",
            text,
        )

        if time_match:

            result["time"] = (
                f"{int(time_match.group(1)):02d}:"
                f"{int(time_match.group(2)):02d}"
            )

    if (
        result["date"]
        and result["time"]
    ):

        result["datetime"] = (
            f"{result['date']} at "
            f"{result['time']}"
        )

    return result
# ============================================================
# LEAD INFORMATION
# ============================================================

def extract_lead_info(
    text: str,
) -> Dict[str, Optional[str]]:

    data = {
        "name": None,
        "phone": None,
        "email": None,
        "company": None,
    }

    if not text:
        return data

    text = text.strip()

    # --------------------------------------------------------
    # EMAIL
    # --------------------------------------------------------

    email_match = re.search(
        r"\b[A-Za-z0-9._%+-]+"
        r"@[A-Za-z0-9.-]+\."
        r"[A-Za-z]{2,}\b",
        text,
    )

    if email_match:
        data["email"] = (
            email_match.group(0).lower()
        )

    # --------------------------------------------------------
    # PHONE
    # --------------------------------------------------------

    phone_matches = re.findall(
        r"(?<!\d)"
        r"(?:\+?91[\s-]?)?"
        r"[6-9]\d{4}[\s-]?\d{5}"
        r"(?!\d)",
        text,
    )

    if phone_matches:

        phone = re.sub(
            r"[^\d]",
            "",
            phone_matches[0],
        )

        if (
            len(phone) == 12
            and phone.startswith("91")
        ):
            phone = phone[2:]

        if len(phone) == 10:
            data["phone"] = phone

    # --------------------------------------------------------
    # NAME
    # --------------------------------------------------------

    name_patterns = [
        r"(?i)\bmera\s+naam\s+"
        r"([A-Za-z][A-Za-z .'-]{1,60}?)"
        r"\s+(?:hai|h|ji|yah|yeh)\b",

        r"(?i)\bmy\s+name\s+is\s+"
        r"([A-Za-z][A-Za-z .'-]{1,60})",

        r"(?i)\bi\s+am\s+"
        r"([A-Za-z][A-Za-z .'-]{1,60})",

        r"(?i)\bmain\s+"
        r"([A-Za-z][A-Za-z .'-]{1,60}?)"
        r"\s+(?:hoon|hun|hu|hai)\b",
    ]

    for pattern in name_patterns:

        match = re.search(
            pattern,
            text,
        )

        if match:

            name = re.sub(
                r"\s+",
                " ",
                match.group(1).strip(
                    " .,-"
                ),
            )

            if name:
                data["name"] = name[:100]
                break

    return data


# ============================================================
# LEAD VOLUME
# ============================================================

def extract_lead_volume(
    text: str,
) -> Optional[str]:

    if not text:
        return None

    clean = text.lower().strip()

    # --------------------------------------------------------
    # Around 100 leads
    # --------------------------------------------------------

    match = re.search(
        r"\b(?:around|about|approx|approximately|"
        r"lagbhag|करीब)?\s*"
        r"(\d+(?:\.\d+)?)\s*"
        r"(?:leads?|inquiries?|enquiries?)"
        r"(?:\s*(?:per|a)\s*day)?\b",
        clean,
    )

    if match:
        return (
            f"around {match.group(1)} "
            f"leads"
        )

    # --------------------------------------------------------
    # 100 leads/day
    # --------------------------------------------------------

    match = re.search(
        r"\b(\d+(?:\.\d+)?)\s*"
        r"(?:leads?|inquiries?|enquiries?)"
        r"\s*(?:/|per|a)\s*day\b",
        clean,
    )

    if match:
        return (
            f"around {match.group(1)} "
            f"leads/day"
        )

    # --------------------------------------------------------
    # Approximate number alone.
    #
    # This is only used when previous conversation
    # contains a question about lead volume.
    # --------------------------------------------------------

    if re.fullmatch(
        r"(?:around\s+|about\s+|"
        r"approx\s+|approximately\s+|"
        r"lagbhag\s+)?\d+",
        clean,
    ):

        return clean

    return None


# ============================================================
# BUSINESS CONTEXT
# ============================================================

def extract_business_context(
    transcript: str,
) -> Dict[str, Optional[str]]:

    lower = transcript.lower()

    result = {
        "business_type": None,
        "need": None,
    }

    businesses = [
        "real estate",
        "real-estate",
        "property dealer",
        "property",
        "clinic",
        "hospital",
        "doctor",
        "coaching",
        "school",
        "restaurant",
        "salon",
        "ecommerce",
        "e-commerce",
        "consultant",
        "insurance",
        "travel agency",
        "car dealer",
        "automobile",
        "gym",
        "retail",
    ]

    for business in businesses:

        if business in lower:

            result["business_type"] = business
            break

    need_patterns = [
        (
            "WhatsApp lead follow-up",
            [
                "whatsapp follow",
                "follow-up",
                "follow up",
                "followup",
            ],
        ),
        (
            "lead management",
            [
                "lead management",
                "lead manage",
                "leads handle",
                "leads ko",
            ],
        ),
        (
            "demo",
            [
                "demo",
                "meeting",
            ],
        ),
        (
            "customer support",
            [
                "customer support",
                "support chahiye",
                "customer queries",
            ],
        ),
        (
            "automation",
            [
                "automation",
                "automate",
                "auto-reply",
                "autoreply",
            ],
        ),
    ]

    for need_name, phrases in need_patterns:

        if any(
            phrase in lower
            for phrase in phrases
        ):

            result["need"] = need_name
            break

    return result


# ============================================================
# CONVERSATION STATE
# ============================================================

def extract_conversation_state(
    history: List[Dict[str, str]],
    current_message: str,
    existing_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:

    transcript = build_transcript(
        history,
        current_message,
    )

    state = {
        "name": None,
        "phone": None,
        "email": None,
        "company": None,
        "business_type": None,
        "need": None,
        "lead_volume": None,
        "demo_date": None,
        "demo_time": None,
        "demo_datetime": None,
        "lead_status": "new",
    }

    # --------------------------------------------------------
    # Existing state from CRM/database
    # --------------------------------------------------------

    if isinstance(
        existing_state,
        dict,
    ):

        for key in state:

            value = existing_state.get(
                key
            )

            if value not in (
                None,
                "",
                "unknown",
            ):
                state[key] = value

        # Support nested state formats
        lead = existing_state.get(
            "lead"
        )

        if isinstance(lead, dict):

            for key in [
                "name",
                "phone",
                "email",
                "company",
            ]:

                if lead.get(key):
                    state[key] = lead[key]

        demo = existing_state.get(
            "demo"
        )

        if isinstance(demo, dict):

            if demo.get("date"):
                state["demo_date"] = (
                    demo["date"]
                )

            if demo.get("time"):
                state["demo_time"] = (
                    demo["time"]
                )

            if demo.get("datetime"):
                state["demo_datetime"] = (
                    demo["datetime"]
                )

    # --------------------------------------------------------
    # Scan every customer message
    # --------------------------------------------------------

    user_messages = [
        item["content"]
        for item in history
        if item["role"] == "user"
    ]

    user_messages.append(
        current_message
    )

    for message in user_messages:

        lead = extract_lead_info(
            message
        )

        for key, value in lead.items():

            if value:
                state[key] = value

        volume = extract_lead_volume(
            message
        )

        if volume:
            state["lead_volume"] = volume

        demo = extract_demo_datetime(
            message
        )

        if demo["date"]:
            state["demo_date"] = (
                demo["date"]
            )

        if demo["time"]:
            state["demo_time"] = (
                demo["time"]
            )

    # --------------------------------------------------------
    # Rebuild demo datetime
    # --------------------------------------------------------

    if (
        state["demo_date"]
        and state["demo_time"]
    ):

        state["demo_datetime"] = (
            f"{state['demo_date']} at "
            f"{state['demo_time']}"
        )

    # --------------------------------------------------------
    # Business context
    # --------------------------------------------------------

    business = extract_business_context(
        transcript
    )

    if business["business_type"]:
        state["business_type"] = (
            business["business_type"]
        )

    if business["need"]:
        state["need"] = business["need"]

    # --------------------------------------------------------
    # Lead status
    # --------------------------------------------------------

    lower = transcript.lower()

    if state["demo_datetime"]:

        state["lead_status"] = (
            "demo_requested"
        )

    elif (
        state["phone"]
        or state["email"]
        or state["name"]
    ):

        state["lead_status"] = (
            "contact_captured"
        )

    elif any(
        keyword in lower
        for keyword in [
            "interested",
            "automation chahiye",
            "automation",
            "demo",
            "price",
            "pricing",
            "buy",
            "purchase",
        ]
    ):

        state["lead_status"] = (
            "interested"
        )

    return state


# ============================================================
# STATE PROMPT
# ============================================================

def build_state_prompt(
    state: Dict[str, Any],
) -> str:

    lines = [
        "PERSISTENT CUSTOMER MEMORY",
        "",
        "Use these facts as confirmed context.",
        "Never ask again for a fact that is already present.",
        "Never invent missing facts.",
        "",
    ]

    fields = [
        ("Customer name", "name"),
        ("Phone", "phone"),
        ("Email", "email"),
        ("Company", "company"),
        ("Business type", "business_type"),
        ("Main requirement", "need"),
        ("Approximate lead volume", "lead_volume"),
        ("Demo date", "demo_date"),
        ("Demo time", "demo_time"),
        ("Confirmed demo", "demo_datetime"),
        ("Lead status", "lead_status"),
    ]

    found = False

    for label, key in fields:

        value = state.get(key)

        if value not in (
            None,
            "",
        ):

            lines.append(
                f"{label}: {value}"
            )

            found = True

    if not found:

        lines.append(
            "No confirmed customer facts yet."
        )

    lines.extend([
        "",
        "IMPORTANT:",
        "If a phone number is already known, do not ask for it again.",
        "If a demo date/time is already known, do not ask again.",
        "If business type is already known, do not ask again.",
        "If lead volume is already known, use it naturally.",
        "Continue from the previous conversation.",
    ])

    return "\n".join(lines)


# ============================================================
# AGENT DETECTION
# ============================================================

def detect_agent(
    user_message: str,
) -> str:

    text = (
        user_message or ""
    ).lower().strip()

    if any(
        keyword in text
        for keyword in [
            "technical issue",
            "login problem",
            "not working",
            "error aa raha",
            "refund chahiye",
        ]
    ):
        return "support"

    if any(
        keyword in text
        for keyword in [
            "job application",
            "candidate screening",
            "interview schedule",
        ]
    ):
        return "hr"

    if any(
        keyword in text
        for keyword in [
            "invoice banao",
            "gst calculate",
            "p&l report",
        ]
    ):
        return "accountant"

    if any(
        keyword in text
        for keyword in [
            "competitor research",
            "market research report",
            "trend analysis",
        ]
    ):
        return "research"

    return "sales"


# ============================================================
# LEAD DETECTION
# ============================================================

def is_potential_lead(
    user_message: str,
) -> bool:

    if not user_message:
        return False

    text = user_message.lower()

    patterns = [
        r"\bprice\b",
        r"\bpricing\b",
        r"\bcost\b",
        r"\bfees?\b",
        r"\bcharges?\b",
        r"\bdemo\b",
        r"\bquotation\b",
        r"\bquote\b",
        r"\bbuy\b",
        r"\bpurchase\b",
        r"\bservice\b",
        r"\bautomation\b",
        r"\bwhatsapp bot\b",
        r"\bai agent\b",
        r"\bneed\b",
        r"\brequirement\b",
        r"\bpackage\b",
        r"\bplan\b",
        r"\bfollow.?up\b",
    ]

    return any(
        re.search(
            pattern,
            text,
        )
        for pattern in patterns
    )


# ============================================================
# REPLY CLEANING
# ============================================================

def clean_reply(
    reply: str,
) -> str:

    if not reply:
        return ""

    text = reply.strip()

    # Remove hidden thinking
    text = re.sub(
        r"(?is)<think>.*?</think>",
        "",
        text,
    ).strip()

    # Remove accidental signatures
    text = re.sub(
        r"(?is)\n+\s*"
        r"(regards|best regards|sincerely|"
        r"thanks and regards|dhanyavaad)"
        r"\s*[.!]*$",
        "",
        text,
    ).strip()

    # Remove AI meta introduction
    text = re.sub(
        r"(?i)^as an ai assistant[,:-]?\s*",
        "",
        text,
    ).strip()

    # Remove markdown heading markers
    text = re.sub(
        r"(?m)^#{1,6}\s*",
        "",
        text,
    ).strip()

    # Remove excessive whitespace
    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


# ============================================================
# UNWANTED GREETING REMOVAL
# ============================================================

def remove_unwanted_greeting(
    reply: str,
) -> str:

    if not reply:
        return reply

    text = reply.strip()

    patterns = [
        r"(?i)^hi[!,.:\-\s]+",
        r"(?i)^hello[!,.:\-\s]+",
        r"(?i)^hey[!,.:\-\s]+",
        r"(?i)^namaste[!,.:\-\s]+",
        r"(?i)^ram\s+ram(?:\s+ji)?[!,.:\-\s]+",
        r"(?i)^welcome[!,.:\-\s]+",
    ]

    for pattern in patterns:

        text = re.sub(
            pattern,
            "",
            text,
            count=1,
        ).strip()

    return text


# ============================================================
# BULLET CLEANUP
# ============================================================

def simplify_whatsapp_reply(
    reply: str,
) -> str:

    if not reply:
        return reply

    text = reply.strip()

    # Convert simple markdown bullets into natural sentences.
    lines = text.splitlines()

    cleaned_lines = []

    for line in lines:

        stripped = line.strip()

        stripped = re.sub(
            r"^[•*\-]\s+",
            "",
            stripped,
        )

        stripped = re.sub(
            r"^\d+[.)]\s+",
            "",
            stripped,
        )

        if stripped:
            cleaned_lines.append(
                stripped
            )

    text = " ".join(
        cleaned_lines
    )

    # Avoid huge whitespace
    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    return text


# ============================================================
# SAFE FALLBACK
# ============================================================

def fallback_message(
    state: Optional[Dict[str, Any]] = None,
) -> str:

    state = state or {}

    if state.get("demo_datetime"):

        return (
            "Bilkul, details note hain. "
            "Aapka demo "
            f"{state['demo_datetime']} "
            "ke liye rahega."
        )

    if state.get("phone"):

        return (
            f"Perfect, {state['phone']} "
            "number note kar liya hai."
        )

    if state.get("lead_volume"):

        return (
            "Samajh gaya, aapke lead volume "
            f"({state['lead_volume']}) ke hisaab se "
            "WhatsApp automation ka setup "
            "kiya ja sakta hai."
        )

    return (
        "Samajh gaya. "
        "Aapki requirement note kar li hai."
    )


# ============================================================
# MAIN AI FUNCTION
# ============================================================

async def generate_agent_reply(
    user_message: str,
    history: Optional[List[Dict[str, Any]]] = None,
    agent_name: Optional[str] = None,
    business_name: str = "Xytralyn",
    conversation_state: Optional[Dict[str, Any]] = None,
) -> str:

    current_message = (
        user_message or ""
    ).strip()

    if not current_message:
        return (
            "Kripya apna message likhiye."
        )

    # --------------------------------------------------------
    # RESET
    # --------------------------------------------------------

    if is_reset_request(
        current_message
    ):

        safe_history = []

        conversation_state = None

    else:

        safe_history = normalize_history(
            history,
            limit=MAX_HISTORY,
        )

        safe_history = (
            remove_duplicate_current_message(
                safe_history,
                current_message,
            )
        )

    # --------------------------------------------------------
    # CLIENT
    # --------------------------------------------------------

    client = get_groq_client()

    # --------------------------------------------------------
    # STATE
    # --------------------------------------------------------

    state = extract_conversation_state(
        history=safe_history,
        current_message=current_message,
        existing_state=conversation_state,
    )

    # --------------------------------------------------------
    # AGENT
    # --------------------------------------------------------

    if agent_name in VALID_AGENTS:

        selected_agent = agent_name

    else:

        selected_agent = detect_agent(
            current_message
        )

    # --------------------------------------------------------
    # GREETING
    # --------------------------------------------------------

    allow_greeting = should_greet(
        current_message,
        safe_history,
    )

    # --------------------------------------------------------
    # NO API KEY / CLIENT
    # --------------------------------------------------------

    if client is None:

        logger.error(
            "AI client unavailable. "
            "Returning contextual fallback."
        )

        return fallback_message(
            state
        )

    # --------------------------------------------------------
    # MESSAGES
    # --------------------------------------------------------

    messages: List[
        Dict[str, str]
    ] = []

    messages.append({
        "role": "system",
        "content": SYSTEM_PROMPT,
    })

    messages.append({
        "role": "system",
        "content": (
            f"Company: {business_name}\n"
            f"Current agent: {selected_agent}\n"
            f"Existing conversation: "
            f"{'YES' if safe_history else 'NO'}\n"
            f"Greeting allowed: "
            f"{'YES' if allow_greeting else 'NO'}\n\n"
            "If greeting is not allowed, NEVER start "
            "the reply with a greeting."
        ),
    })

    messages.append({
        "role": "system",
        "content": build_state_prompt(
            state
        ),
    })

    # --------------------------------------------------------
    # SPECIAL CURRENT MESSAGE INSTRUCTIONS
    # --------------------------------------------------------

    current_lead = extract_lead_info(
        current_message
    )

    current_demo = extract_demo_datetime(
        current_message
    )

    current_volume = extract_lead_volume(
        current_message
    )

    if current_lead["phone"]:

        messages.append({
            "role": "system",
            "content": (
                "The customer has just supplied a "
                "phone number. Acknowledge the number "
                "naturally. Preserve all previous "
                "conversation facts."
            ),
        })

    if current_lead["name"]:

        messages.append({
            "role": "system",
            "content": (
                "The customer has just supplied their "
                "name. Acknowledge the name naturally. "
                "Do not restart the sales conversation."
            ),
        })

    if current_demo["datetime"]:

        messages.append({
            "role": "system",
            "content": (
                "The customer has supplied a demo date "
                "and time. Acknowledge that exact "
                "date/time. Do not ask for it again."
            ),
        })

    if current_volume:

        messages.append({
            "role": "system",
            "content": (
                f"The current message may contain the "
                f"customer's lead volume: "
                f"{current_volume}. "
                "Use previous context to interpret "
                "a number-only message correctly."
            ),
        })

    # --------------------------------------------------------
    # HISTORY
    # --------------------------------------------------------

    if safe_history:

        messages.extend(
            safe_history
        )

    # --------------------------------------------------------
    # CURRENT MESSAGE
    # --------------------------------------------------------

    messages.append({
        "role": "user",
        "content": current_message,
    })

    # --------------------------------------------------------
    # MODEL LOOP
    # --------------------------------------------------------

    last_error = None

    for model_id in GROQ_MODELS:

        try:

            logger.info(
                "Trying Groq model=%s",
                model_id,
            )

            response = (
                await client
                .chat
                .completions
                .create(
                    model=model_id,
                    messages=messages,
                    temperature=0.20,
                    top_p=0.90,
                    max_tokens=MAX_REPLY_TOKENS,
                    timeout=25.0,
                )
            )

            if not response.choices:

                logger.warning(
                    "Model %s returned no choices",
                    model_id,
                )

                continue

            raw_reply = (
                response
                .choices[0]
                .message
                .content
                or ""
            )

            reply = clean_reply(
                raw_reply
            )

            if not reply:

                continue

            # ------------------------------------------------
            # HARD GREETING PROTECTION
            # ------------------------------------------------

            if not allow_greeting:

                reply = (
                    remove_unwanted_greeting(
                        reply
                    )
                )

            # ------------------------------------------------
            # WHATSAPP CLEANUP
            # ------------------------------------------------

            reply = (
                simplify_whatsapp_reply(
                    reply
                )
            )

            if not reply:

                return fallback_message(
                    state
                )

            logger.info(
                "AI reply generated successfully | "
                "model=%s | history=%s | "
                "status=%s | demo=%s",
                model_id,
                len(safe_history),
                state["lead_status"],
                bool(
                    state["demo_datetime"]
                ),
            )

            return reply

        except Exception as error:

            last_error = error

            logger.exception(
                "Groq model failed: %s",
                model_id,
            )

            continue

    # --------------------------------------------------------
    # ALL MODELS FAILED
    # --------------------------------------------------------

    logger.error(
        "All Groq models failed. Last error: %s",
        last_error,
    )

    return fallback_message(
        state
    )


# ============================================================
# STATE ACCESS FOR CRM / ROUTES
# ============================================================

def get_conversation_state(
    user_message: str,
    history: Optional[
        List[Dict[str, Any]]
    ] = None,
    existing_state: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:

    safe_history = normalize_history(
        history,
        limit=MAX_HISTORY,
    )

    safe_history = (
        remove_duplicate_current_message(
            safe_history,
            user_message,
        )
    )

    return extract_conversation_state(
        history=safe_history,
        current_message=user_message,
        existing_state=existing_state,
    )


# ============================================================
# SIMPLE HEALTH CHECK
# ============================================================

def ai_agent_health() -> Dict[str, Any]:

    return {
        "groq_configured": bool(
            os.getenv("GROQ_API_KEY")
        ),
        "models_configured": len(
            GROQ_MODELS
        ),
        "valid_agents": sorted(
            VALID_AGENTS
        ),
    }