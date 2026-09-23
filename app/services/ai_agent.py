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
# CONFIGURATION
# ============================================================

GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
]

SUPPORTED_AGENTS = {
    "sales",
    "support",
    "hr",
    "accountant",
    "research",
}


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are the official WhatsApp AI Sales Executive for Xytralyn.

Xytralyn is a Multi-Agent AI Business Automation platform.

It helps businesses automate:
- WhatsApp conversations
- Lead capture
- Lead qualification
- Customer support
- HR workflows
- Accounting workflows
- Business research
- Follow-ups
- Demo enquiries

CORE AI AGENTS:

1. Sales Agent
Lead qualification, instant replies, WhatsApp follow-ups,
demo enquiries, objection handling and lead capture.

2. Support Agent
Customer queries, FAQs, complaints, support and escalation.

3. HR Agent
Candidate screening, interview scheduling and recruitment workflows.

4. Accountant Agent
Invoice generation, GST calculations, expense logging
and basic profit/loss tracking.

5. Research Agent
Market research, competitor analysis, business analysis
and trend analysis.


PLANS:

Basic:
₹2,000/month
One AI Agent with WhatsApp integration.

Pro:
₹5,000/month
All five AI Agents, CRM dashboard and lead management.

Business:
₹10,000/month
All five AI Agents, custom automation workflows
and priority support.

CUSTOM AGENT PRICING:

Sales: ₹2,000/month
Support: ₹2,000/month
HR: ₹2,500/month
Accountant: ₹3,000/month
Research: ₹2,500/month


PRICING RULE:

Only discuss pricing when the customer explicitly asks about:
price, pricing, cost, fees, charges, package, plan,
quotation, quote or budget.

Never introduce pricing during a normal conversation unless
the customer asks.


============================================================
HUMAN CONVERSATION RULES
============================================================

You are NOT a scripted FAQ bot.

Talk like a natural, experienced human sales executive.

Understand the customer's CURRENT message first.

Use previous conversation only when it is relevant.

Never restart the conversation unnecessarily.

Never behave as if every message is a new customer.

Never repeat a question that the customer has already answered.

Never ask for the customer's:
- name
- phone number
- email
- business type
- lead volume
- demo date
- demo time

if that information is already known.


============================================================
CUSTOMER MEMORY
============================================================

A CUSTOMER PROFILE may be provided by the backend.

The profile contains information extracted from THIS customer's
WhatsApp conversation.

Treat that information as factual conversation memory.

IMPORTANT:

- Never invent customer information.
- Never change a customer's name.
- Never change a customer's phone number.
- Never change a customer's email.
- Never change the customer's business type.
- Never mix information from another customer.
- Latest explicit customer information has priority.
- If the customer asks "mera naam kya hai?", answer from memory.
- If the customer asks "mera email kya hai?", answer from memory.
- If the customer asks "mera number kya hai?", answer from memory.
- If the customer asks for multiple saved details, answer all
  available details directly.
- Do not say "I don't know" if the information is present
  in CUSTOMER PROFILE or conversation history.


============================================================
CONVERSATION CONTINUITY
============================================================

Continue the existing conversation naturally.

For example:

Customer:
"Mera naam Suresh hai."

Later:

Customer:
"Mai coaching centre ka owner hu."

Later:

Customer:
"150 leads daily."

The assistant should understand that all three messages
belong to the same customer and conversation.

Do NOT restart the conversation.

Do NOT ask:

"What is your business?"

if the customer already said:

"Mai coaching centre ka owner hu."


============================================================
BUSINESS CONTEXT
============================================================

The latest explicit business context has priority.

If the customer first says:

"Mai real estate mein hu"

and later says:

"Actually mai coaching centre chalata hu"

the current business context is:

coaching.

Never bring the old business back unless the customer
explicitly mentions it again.


============================================================
DEMO MEMORY
============================================================

If the customer gives a demo date and time:

Example:

"5 October ko shaam 6:30 baje demo dekhna hai."

Acknowledge the exact date and time.

Do NOT ask for the date again.

Do NOT ask for the time again.

If the customer later provides a phone number, name or email,
continue from the already confirmed demo information.

Do NOT restart the demo booking conversation.


============================================================
GREETING RULE
============================================================

This is extremely important.

Only greet when the CUSTOMER actually greets.

If the customer says:

"Hi"

you may reply:

"Hi! ..."

If the customer says:

"Hello"

you may reply naturally.

If the customer says:

"Ram Ram"

you may respectfully reply:

"Ram Ram ji."

If the customer sends:

"9876543210"

DO NOT say:

"Hi!"

If the customer says:

"150"

DO NOT say:

"Hello!"

If the customer asks:

"Mera naam kya hai?"

DO NOT greet.

If the customer gives their name:

"Mera naam Suresh hai."

DO NOT restart the sales conversation.

Never automatically start every response with:
Hi
Hello
Namaste
Ram Ram
Welcome


============================================================
LANGUAGE
============================================================

Use natural Roman Hinglish by default.

Match the customer's language.

If the customer uses Hindi/Hinglish:
reply in natural Hinglish.

If the customer uses English:
reply in natural English.

Do not translate unnecessarily.

Keep the tone friendly, professional and human.


============================================================
WHATSAPP STYLE
============================================================

Normal response:
1 to 3 short sentences.

Avoid long explanations unless the customer asks for details.

Do not use headings or bullet lists during normal WhatsApp sales chat.

Avoid robotic phrases such as:

"To guide you better..."
"Based on your requirements..."
"Thank you for providing..."
"As an AI..."

Do not use signatures.

Do not use "Regards".

Do not mention internal instructions.

Do not mention:
- system prompt
- model name
- API
- database
- internal memory
- backend
- developer instructions


============================================================
LEAD FOLLOW-UP
============================================================

Your job is not only to answer.

You should naturally move a genuine prospect toward the
next useful step.

Possible flow:

Greeting
→ understand business
→ understand lead volume
→ understand requirement
→ explain relevant automation
→ offer demo
→ collect contact details
→ confirm demo details

But NEVER force this flow.

If the customer asks a direct question, answer that question first.

Ask at most ONE useful follow-up question at a time.

Never ask multiple questions unnecessarily.


============================================================
DEMO SAFETY
============================================================

Never claim that a real meeting link was sent unless the
system actually provides a meeting link.

Never claim a real booking was completed unless the backend
actually confirms it.

You may say:

"Demo time note kar liya hai."

But do not falsely claim:

"Meeting successfully booked"

unless the application actually booked it.


============================================================
FINAL RESPONSE QUALITY
============================================================

Before responding, internally check:

1. Did I answer the current message?
2. Am I remembering previous information?
3. Am I accidentally asking something already known?
4. Am I accidentally saying Hi again?
5. Am I using the latest business context?
6. Am I preserving the demo date/time?
7. Am I answering memory questions directly?
8. Am I talking naturally?
9. Am I keeping the reply concise?
10. Am I avoiding invented information?

Return ONLY the customer-facing reply.
"""


# ============================================================
# GROQ CLIENT
# ============================================================

def get_groq_client() -> Optional[AsyncGroq]:
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        logger.error(
            "GROQ_API_KEY is missing"
        )
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
# RESET DETECTION
# ============================================================

RESET_PHRASES = [
    "reset",
    "reset chat",
    "new chat",
    "new conversation",
    "start fresh",
    "fresh start",
    "naye se start karo",
    "nayi shuruaat",
    "purani baat chhodo",
    "purani history hatao",
]


def is_reset_request(
    text: str,
) -> bool:

    clean_text = re.sub(
        r"\s+",
        " ",
        (text or "").strip().lower(),
    )

    if clean_text in RESET_PHRASES:
        return True

    extra_phrases = [
        "start fresh karo",
        "fresh chat karo",
        "purani baat ignore karo",
        "naye chat ki tarah",
    ]

    return any(
        phrase in clean_text
        for phrase in extra_phrases
    )


# ============================================================
# HISTORY NORMALIZATION
# ============================================================

def normalize_history(
    history: Optional[List[Dict[str, Any]]],
    limit: int = 20,
) -> List[Dict[str, str]]:

    if not isinstance(history, list):
        return []

    result: List[Dict[str, str]] = []

    for item in history:

        if not isinstance(item, dict):
            continue

        role = item.get("role")
        content = item.get("content")

        if (
            role in {"user", "assistant"}
            and isinstance(content, str)
            and content.strip()
        ):
            result.append(
                {
                    "role": role,
                    "content": content.strip()[:4000],
                }
            )

    return result[-limit:]


# ============================================================
# GREETING DETECTION
# ============================================================

def user_started_with_greeting(
    text: str,
) -> bool:

    if not text:
        return False

    clean = text.strip().lower()

    greeting_patterns = [
        r"^hi\b",
        r"^hello\b",
        r"^hey\b",
        r"^hii+\b",
        r"^namaste\b",
        r"^namaskar\b",
        r"^ram ram\b",
        r"^good morning\b",
        r"^good afternoon\b",
        r"^good evening\b",
    ]

    return any(
        re.search(
            pattern,
            clean,
        )
        for pattern in greeting_patterns
    )


# ============================================================
# REMOVE UNWANTED GREETING
# ============================================================

def remove_unwanted_greeting(
    reply: str,
    user_message: str,
    history: List[Dict[str, str]],
) -> str:

    if not reply:
        return ""

    # If customer greeted for the first time,
    # greeting is allowed.
    if user_started_with_greeting(
        user_message
    ):
        return reply.strip()

    text = reply.strip()

    # Do not allow automatic greetings in middle
    # of an existing conversation.
    greeting_patterns = [
        r"^hi[!,.:\-\s]+",
        r"^hello[!,.:\-\s]+",
        r"^hey[!,.:\-\s]+",
        r"^hii+[!,.:\-\s]+",
        r"^namaste[!,.:\-\s]+",
        r"^namaskar[!,.:\-\s]+",
        r"^ram ram ji[!,.:\-\s]+",
        r"^ram ram[!,.:\-\s]+",
        r"^welcome[!,.:\-\s]+",
    ]

    for pattern in greeting_patterns:

        cleaned = re.sub(
            pattern,
            "",
            text,
            count=1,
            flags=re.IGNORECASE,
        )

        if cleaned != text:
            text = cleaned.strip()
            break

    return text


# ============================================================
# REPLY CLEANING
# ============================================================

def clean_reply(
    reply: str,
) -> str:

    if not reply:
        return ""

    text = reply.strip()

    # Remove reasoning tags if model returns them.
    text = re.sub(
        r"(?is)<think>.*?</think>",
        "",
        text,
    ).strip()

    # Remove common AI disclaimers.
    text = re.sub(
        r"(?i)^as an ai assistant[,:-]?\s*",
        "",
        text,
    ).strip()

    # Remove robotic prefixes.
    text = re.sub(
        r"(?i)^(great|perfect|excellent)!\s*to guide you better[,:-]?\s*",
        "",
        text,
    ).strip()

    # Remove signatures.
    text = re.sub(
        r"(?is)\n+\s*"
        r"(regards|best regards|sincerely|thanks and regards|dhanyavaad)"
        r"\s*[.!]*$",
        "",
        text,
    ).strip()

    # Remove accidental unmatched closing characters.
    text = re.sub(
        r"[\]\(\)\<\>]+$",
        "",
        text,
    ).strip()

    return text


# ============================================================
# FALLBACK
# ============================================================

def fallback_message() -> str:
    return (
        "Aapka message note ho gaya hai. "
        "Main details check karke aapko confirm karta hoon."
    )
# ============================================================
# AGENT DETECTION
# ============================================================

def detect_agent(
    user_message: str,
) -> str:

    text = (
        user_message
        or ""
    ).lower().strip()

    support_keywords = [
        "technical issue",
        "technical problem",
        "login problem",
        "login issue",
        "not working",
        "kaam nahi kar",
        "error aa raha",
        "error",
        "refund chahiye",
        "complaint",
    ]

    hr_keywords = [
        "job application",
        "candidate screening",
        "interview schedule",
        "interview",
        "recruitment",
        "candidate",
    ]

    accountant_keywords = [
        "invoice banao",
        "gst calculate",
        "gst calculation",
        "p&l report",
        "profit loss",
        "expense report",
    ]

    research_keywords = [
        "competitor research",
        "market research report",
        "market research",
        "trend analysis",
        "competitor analysis",
    ]

    if any(
        keyword in text
        for keyword in support_keywords
    ):
        return "support"

    if any(
        keyword in text
        for keyword in hr_keywords
    ):
        return "hr"

    if any(
        keyword in text
        for keyword in accountant_keywords
    ):
        return "accountant"

    if any(
        keyword in text
        for keyword in research_keywords
    ):
        return "research"

    return "sales"


# ============================================================
# BUSINESS CONTEXT EXTRACTION
# ============================================================

def extract_business_context(
    history: Optional[List[Dict[str, Any]]],
    current_message: str,
) -> Dict[str, Optional[str]]:

    parts: List[str] = []

    if isinstance(history, list):

        for item in history:

            if (
                isinstance(item, dict)
                and isinstance(
                    item.get("content"),
                    str,
                )
            ):
                parts.append(
                    item["content"]
                )

    if current_message:
        parts.append(
            current_message
        )

    transcript = "\n".join(parts)
    lower = transcript.lower()

    context: Dict[str, Optional[str]] = {
        "business_type": None,
        "need": None,
    }

    # --------------------------------------------------------
    # BUSINESS TYPES
    # --------------------------------------------------------

    business_patterns = [
        (
            "real estate",
            [
                "real estate",
                "real-estate",
                "property dealer",
                "property business",
            ],
        ),
        (
            "coaching",
            [
                "coaching centre",
                "coaching center",
                "coaching",
                "tuition centre",
                "tuition center",
            ],
        ),
        (
            "clinic",
            [
                "clinic",
            ],
        ),
        (
            "hospital",
            [
                "hospital",
            ],
        ),
        (
            "doctor",
            [
                "doctor",
            ],
        ),
        (
            "school",
            [
                "school",
            ],
        ),
        (
            "restaurant",
            [
                "restaurant",
                "cafe",
                "café",
            ],
        ),
        (
            "salon",
            [
                "salon",
                "beauty parlour",
                "beauty parlor",
            ],
        ),
        (
            "ecommerce",
            [
                "ecommerce",
                "e-commerce",
                "online store",
            ],
        ),
        (
            "consultant",
            [
                "consultant",
                "consulting",
            ],
        ),
        (
            "insurance",
            [
                "insurance",
            ],
        ),
        (
            "travel agency",
            [
                "travel agency",
                "tour agency",
            ],
        ),
        (
            "car dealer",
            [
                "car dealer",
                "automobile dealer",
            ],
        ),
        (
            "gym",
            [
                "gym",
                "fitness centre",
                "fitness center",
            ],
        ),
        (
            "retail",
            [
                "retail",
                "shop",
                "store",
            ],
        ),
    ]

    latest_position = -1
    latest_business = None

    for business_name, phrases in business_patterns:

        for phrase in phrases:

            position = lower.rfind(
                phrase
            )

            if position > latest_position:

                latest_position = position
                latest_business = (
                    business_name
                )

    if latest_business:
        context["business_type"] = (
            latest_business
        )

    # --------------------------------------------------------
    # NEED
    # --------------------------------------------------------

    need_patterns = [
        (
            "WhatsApp lead follow-up",
            [
                "whatsapp follow",
                "whatsapp follow-up",
                "follow up chahiye",
                "follow-up chahiye",
                "followup chahiye",
            ],
        ),
        (
            "lead replies",
            [
                "lead reply",
                "leads ko reply",
                "customer reply",
                "inquiry reply",
            ],
        ),
        (
            "appointment automation",
            [
                "appointment",
                "booking",
                "reminder",
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
            "lead automation",
            [
                "lead automation",
                "leads automate",
                "lead automate",
                "automation chahiye",
            ],
        ),
    ]

    latest_need_position = -1
    latest_need = None

    for need_name, phrases in need_patterns:

        for phrase in phrases:

            position = lower.rfind(
                phrase
            )

            if position > latest_need_position:

                latest_need_position = position
                latest_need = need_name

    if latest_need:
        context["need"] = latest_need

    return context


# ============================================================
# CONTEXT INSTRUCTION
# ============================================================

def build_context_instruction(
    context: Dict[str, Optional[str]],
) -> str:

    if not context:
        return ""

    lines = [
        "CONFIRMED CONVERSATION CONTEXT:",
    ]

    if context.get("business_type"):
        lines.append(
            "Business type: "
            + str(
                context["business_type"]
            )
        )

    if context.get("need"):
        lines.append(
            "Main need: "
            + str(
                context["need"]
            )
        )

    lines.extend(
        [
            "",
            "These facts are already known.",
            "Do not ask the customer for them again.",
            "Use the latest customer context.",
        ]
    )

    return "\n".join(lines)


# ============================================================
# DEMO DATE/TIME EXTRACTION
# ============================================================

def extract_demo_datetime(
    user_message: str,
) -> Dict[str, Optional[str]]:

    text = (
        user_message
        or ""
    ).strip()

    result: Dict[str, Optional[str]] = {
        "date": None,
        "time": None,
        "datetime": None,
    }

    # --------------------------------------------------------
    # Date with year
    # Example:
    # 5 October 2026
    # --------------------------------------------------------

    date_match = re.search(
        r"\b"
        r"(\d{1,2})\s+"
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)"
        r"(?:\s+(20\d{2}))?"
        r"\b",
        text,
        re.IGNORECASE,
    )

    if date_match:

        try:

            day = int(
                date_match.group(1)
            )

            month_name = (
                date_match.group(2)
            )

            year_text = (
                date_match.group(3)
            )

            if year_text:

                year = int(
                    year_text
                )

                selected_date = datetime.strptime(
                    f"{day} {month_name} {year}",
                    "%d %B %Y",
                )

                result["date"] = (
                    selected_date.strftime(
                        "%d %B %Y"
                    )
                )

            else:

                # No year provided.
                # Preserve the customer's date wording
                # instead of inventing a year.
                result["date"] = (
                    f"{day} {month_name}"
                )

        except ValueError:
            result["date"] = None

    # --------------------------------------------------------
    # Numeric date
    # Example:
    # 2026-10-05
    # 2026/10/05
    # --------------------------------------------------------

    if not result["date"]:

        numeric_date = re.search(
            r"\b"
            r"(20\d{2})[-/]"
            r"(\d{1,2})[-/]"
            r"(\d{1,2})"
            r"\b",
            text,
        )

        if numeric_date:

            try:

                selected_date = datetime(
                    int(
                        numeric_date.group(1)
                    ),
                    int(
                        numeric_date.group(2)
                    ),
                    int(
                        numeric_date.group(3)
                    ),
                )

                result["date"] = (
                    selected_date.strftime(
                        "%d %B %Y"
                    )
                )

            except ValueError:
                result["date"] = None

    # --------------------------------------------------------
    # Time
    # Supports:
    # 6:30 PM
    # 6 PM
    # 18:30
    # --------------------------------------------------------

    time_match = re.search(
        r"\b"
        r"(\d{1,2})"
        r"(?::(\d{2}))?"
        r"\s*"
        r"(AM|PM|am|pm)"
        r"\b",
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
                    f"{hour}:{minute:02d} "
                    f"{time_match.group(3).upper()}"
                )

        except ValueError:
            result["time"] = None

    # 24-hour time
    if not result["time"]:

        time_24 = re.search(
            r"\b"
            r"([01]?\d|2[0-3])"
            r":"
            r"([0-5]\d)"
            r"\b",
            text,
        )

        if time_24:

            try:

                hour = int(
                    time_24.group(1)
                )

                minute = int(
                    time_24.group(2)
                )

                result["time"] = (
                    f"{hour:02d}:{minute:02d}"
                )

            except ValueError:
                result["time"] = None

    if (
        result["date"]
        and result["time"]
    ):

        result["datetime"] = (
            f"{result['date']} "
            f"at {result['time']}"
        )

    return result


# ============================================================
# LEAD INFORMATION EXTRACTION
# ============================================================

def extract_lead_info(
    user_message: str,
) -> Dict[str, Optional[str]]:

    data: Dict[str, Optional[str]] = {
        "name": None,
        "phone": None,
        "email": None,
        "company": None,
    }

    if not user_message:
        return data

    text = user_message.strip()

    # --------------------------------------------------------
    # EMAIL
    # --------------------------------------------------------

    email_match = re.search(
        r"\b"
        r"[A-Za-z0-9._%+-]+"
        r"@"
        r"[A-Za-z0-9.-]+"
        r"\."
        r"[A-Za-z]{2,}"
        r"\b",
        text,
    )

    if email_match:

        data["email"] = (
            email_match.group(0)
            .lower()
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

    name_match = re.search(
        r"(?i)"
        r"\b"
        r"(?:mera naam|my name is|"
        r"i am|main hoon|"
        r"mera name)"
        r"\s+"
        r"([A-Za-z][A-Za-z .'-]{1,49})",
        text,
    )

    if name_match:

        name = name_match.group(1).strip(
            " .,-"
        )

        # Stop common continuation words.
        name = re.split(
            r"(?i)\s+(?:hai|h|and|aur|my|mera|meri)\b",
            name,
            maxsplit=1,
        )[0].strip()

        if name:
            data["name"] = name[:100]

    # --------------------------------------------------------
    # COMPANY
    # --------------------------------------------------------

    company_patterns = [
        r"(?i)\b(?:company|firm|business)\s*(?:ka naam|name)?\s*(?:hai|is)?\s*[:\-]?\s*([A-Za-z0-9 .&'-]{2,80})",
        r"(?i)\b(?:meri company|my company)\s*(?:hai|is)?\s*([A-Za-z0-9 .&'-]{2,80})",
    ]

    for pattern in company_patterns:

        company_match = re.search(
            pattern,
            text,
        )

        if company_match:

            company = (
                company_match.group(1)
                .strip(" .,-")
            )

            if company:
                data["company"] = (
                    company[:100]
                )

                break

    return data


# ============================================================
# POTENTIAL LEAD DETECTION
# ============================================================

def is_potential_lead(
    user_message: str,
) -> bool:

    if not user_message:
        return False

    text = (
        user_message
        .lower()
        .strip()
    )

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
        r"\blead\b",
    ]

    return any(
        re.search(
            pattern,
            text,
        )
        for pattern in patterns
    )


# ============================================================
# MEMORY QUESTION DETECTION
# ============================================================

def is_memory_question(
    text: str,
) -> bool:

    if not text:
        return False

    clean = (
        text
        .lower()
        .strip()
    )

    patterns = [
        "mera naam kya hai",
        "mera name kya hai",
        "my name kya hai",
        "what is my name",
        "mera email kya hai",
        "meri email kya hai",
        "email kya hai",
        "my email kya hai",
        "my email",
        "mera number kya hai",
        "mera phone number kya hai",
        "number kya hai",
        "phone number kya hai",
        "my number",
        "meri details kya hain",
        "meri detail kya hai",
        "maine kya bataya tha",
        "maine kya bataya",
    ]

    return any(
        pattern in clean
        for pattern in patterns
    )


# ============================================================
# PROFILE VALUE EXTRACTION
# ============================================================

def extract_profile_values(
    customer_profile: Optional[str],
) -> Dict[str, Optional[str]]:

    profile: Dict[str, Optional[str]] = {
        "name": None,
        "phone": None,
        "email": None,
        "company": None,
        "business_type": None,
    }

    if not customer_profile:
        return profile

    text = str(
        customer_profile
    )

    patterns = {
        "name": r"(?im)^Customer name:\s*(.+)$",
        "phone": r"(?im)^Customer phone:\s*(.+)$",
        "email": r"(?im)^Customer email:\s*(.+)$",
        "company": r"(?im)^Company:\s*(.+)$",
        "business_type": r"(?im)^Business type:\s*(.+)$",
    }

    for key, pattern in patterns.items():

        match = re.search(
            pattern,
            text,
        )

        if match:

            value = (
                match.group(1)
                .strip()
            )

            if value:
                profile[key] = value

    return profile
# ============================================================
# DIRECT MEMORY ANSWER
# ============================================================

def build_direct_memory_answer(
    user_message: str,
    customer_profile: Optional[str],
) -> Optional[str]:

    if not is_memory_question(
        user_message
    ):
        return None

    profile = extract_profile_values(
        customer_profile
    )

    text = (
        user_message
        .lower()
        .strip()
    )

    name = profile.get("name")
    phone = profile.get("phone")
    email = profile.get("email")
    business = profile.get("business_type")

    # --------------------------------------------------------
    # Name + email + phone
    # --------------------------------------------------------

    asks_name = (
        "naam" in text
        or "name" in text
    )

    asks_email = (
        "email" in text
        or "mail" in text
    )

    asks_phone = (
        "number" in text
        or "phone" in text
    )

    parts: List[str] = []

    if asks_name and name:
        parts.append(
            f"Aapka naam {name} hai."
        )

    if asks_email and email:
        parts.append(
            f"Aapka email {email} hai."
        )

    if asks_phone and phone:
        parts.append(
            f"Aapka number {phone} hai."
        )

    if parts:
        return " ".join(parts)

    # --------------------------------------------------------
    # Business
    # --------------------------------------------------------

    business_question = (
        "business kya hai" in text
        or "mera business" in text
        or "what is my business" in text
    )

    if business_question and business:
        return (
            f"Aapka business "
            f"{business} hai."
        )

    return None


# ============================================================
# CONVERSATION STATE INSTRUCTION
# ============================================================

def build_conversation_rules(
    user_message: str,
    history: List[Dict[str, str]],
    customer_profile: Optional[str],
) -> str:

    lines = [
        "CONVERSATION CONTROL:",
        "",
        "Current customer message:",
        user_message,
        "",
        "Follow these rules strictly:",
        "1. Answer the current message first.",
        "2. Use customer memory when relevant.",
        "3. Do not repeat already answered questions.",
        "4. Do not restart the sales conversation.",
        "5. Do not add a greeting unless the current customer message contains a greeting.",
        "6. If a demo date/time is already confirmed, do not ask for it again.",
        "7. If contact details are already known, do not ask for them again.",
        "8. Ask at most one useful follow-up question.",
        "9. Keep normal WhatsApp responses concise.",
        "10. Never invent a booking, meeting link or confirmation.",
    ]

    if history:
        lines.extend(
            [
                "",
                "There is an existing conversation.",
                "Treat it as continuous conversation.",
            ]
        )

    if customer_profile:
        lines.extend(
            [
                "",
                customer_profile,
            ]
        )

    return "\n".join(lines)


# ============================================================
# DEMO CONTEXT FROM HISTORY
# ============================================================

def find_demo_context(
    history: List[Dict[str, str]],
) -> Optional[str]:

    if not history:
        return None

    # Search newest user messages first.
    for item in reversed(history):

        if (
            item.get("role")
            != "user"
        ):
            continue

        content = item.get(
            "content",
            "",
        )

        demo = extract_demo_datetime(
            content
        )

        if demo.get("datetime"):
            return demo["datetime"]

    return None


# ============================================================
# MAIN AI RESPONSE GENERATOR
# ============================================================

async def generate_agent_reply(
    user_message: str,
    history: Optional[List[Dict[str, str]]] = None,
    agent_name: Optional[str] = None,
    business_name: str = "Xytralyn",
    customer_profile: Optional[str] = None,
) -> str:

    current_message = (
        user_message
        or ""
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
        safe_history: List[
            Dict[str, str]
        ] = []

    else:
        safe_history = normalize_history(
            history,
            limit=20,
        )

    # --------------------------------------------------------
    # DIRECT MEMORY ANSWER
    #
    # Important:
    # Do this BEFORE the LLM call.
    # This prevents the model from forgetting
    # name/email/phone.
    # --------------------------------------------------------

    direct_memory_answer = (
        build_direct_memory_answer(
            current_message,
            customer_profile,
        )
    )

    if direct_memory_answer:

        logger.info(
            "Direct customer-memory answer returned."
        )

        return direct_memory_answer

    # --------------------------------------------------------
    # CONTEXT
    # --------------------------------------------------------

    context = extract_business_context(
        history=safe_history,
        current_message=current_message,
    )

    context_instruction = (
        build_context_instruction(
            context
        )
    )

    demo_details = extract_demo_datetime(
        current_message
    )

    previous_demo = find_demo_context(
        safe_history
    )

    # --------------------------------------------------------
    # AGENT
    # --------------------------------------------------------

    selected_agent = (
        agent_name
        if agent_name in SUPPORTED_AGENTS
        else "sales"
    )

    # --------------------------------------------------------
    # GROQ CLIENT
    # --------------------------------------------------------

    client = get_groq_client()

    if client is None:
        return fallback_message()

    # --------------------------------------------------------
    # BUILD MESSAGES
    # --------------------------------------------------------

    messages: List[
        Dict[str, str]
    ] = []

    messages.append(
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        }
    )

    # --------------------------------------------------------
    # BUSINESS
    # --------------------------------------------------------

    messages.append(
        {
            "role": "system",
            "content": (
                f"Official business name: "
                f"{business_name}\n"
                f"Current AI agent: "
                f"{selected_agent}"
            ),
        }
    )

    # --------------------------------------------------------
    # CUSTOMER PROFILE
    # --------------------------------------------------------

    if customer_profile:

        messages.append(
            {
                "role": "system",
                "content": customer_profile,
            }
        )

    # --------------------------------------------------------
    # CONTEXT
    # --------------------------------------------------------

    if context_instruction:

        messages.append(
            {
                "role": "system",
                "content": context_instruction,
            }
        )

    # --------------------------------------------------------
    # CONVERSATION CONTROL
    # --------------------------------------------------------

    messages.append(
        {
            "role": "system",
            "content": build_conversation_rules(
                user_message=current_message,
                history=safe_history,
                customer_profile=customer_profile,
            ),
        }
    )

    # --------------------------------------------------------
    # CURRENT DEMO
    # --------------------------------------------------------

    if demo_details.get("datetime"):

        messages.append(
            {
                "role": "system",
                "content": (
                    "The customer has provided this "
                    "demo date/time in the current message: "
                    f"{demo_details['datetime']}. "
                    "Acknowledge it naturally. "
                    "Do not ask for another date/time."
                ),
            }
        )

    elif previous_demo:

        messages.append(
            {
                "role": "system",
                "content": (
                    "A demo date/time was already "
                    "mentioned earlier in this conversation: "
                    f"{previous_demo}. "
                    "Preserve it unless the customer explicitly "
                    "changes the date or time. "
                    "Do not ask for the demo date/time again."
                ),
            }
        )

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

    messages.append(
        {
            "role": "user",
            "content": current_message,
        }
    )

    # --------------------------------------------------------
    # MODEL LOOP
    # --------------------------------------------------------

    for model_id in GROQ_MODELS:

        try:

            response = (
                await client.chat.completions.create(
                    model=model_id,
                    messages=messages,
                    temperature=0.25,
                    top_p=0.85,
                    max_tokens=350,
                    timeout=25.0,
                )
            )

            if not response.choices:
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

            reply = remove_unwanted_greeting(
                reply=reply,
                user_message=current_message,
                history=safe_history,
            )

            if not reply:
                continue

            logger.info(
                "Xytralyn response generated "
                "with model=%s",
                model_id,
            )

            return reply

        except Exception as error:

            logger.warning(
                "Groq model %s failed: %s",
                model_id,
                error,
            )

    return fallback_message()