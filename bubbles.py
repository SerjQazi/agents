import json
import os
import re
import requests
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


load_dotenv(Path(__file__).with_name(".env"))

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL = os.getenv("OLLAMA_MODEL", "llama3")

ALLOWED_USER_ID_TEXT = os.getenv("BUBBLES_ALLOWED_USER_ID", "").strip()
ALLOWED_USER_ID = int(ALLOWED_USER_ID_TEXT) if ALLOWED_USER_ID_TEXT.isdigit() else None
BOT_TOKEN = os.getenv("BUBBLES_BOT_TOKEN")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
GOOGLE_CREDENTIALS_PATH = Path(os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json"))
GOOGLE_TOKEN_PATH = Path(os.getenv("GOOGLE_TOKEN_PATH", "token.json"))
GOOGLE_CALENDAR_TIMEZONE = os.getenv("GOOGLE_CALENDAR_TIMEZONE", "UTC")
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
REMINDER_MINUTES = [10, 30, 60, 24 * 60, 7 * 24 * 60]
PENDING_EVENTS: dict[int, dict] = {}
CHAT_MEMORY: dict[int, list[dict[str, str]]] = {}
SYSTEM_PROMPT = (
    "You are Bubbles, my personal Telegram assistant. Reply naturally and keep answers short. "
    "The bot has local tools for calendar, files, and system checks; never claim you lack access "
    "when the code can handle the task. For tool tasks, assume the code has already handled them."
)
try:
    LOCAL_TZ = ZoneInfo(GOOGLE_CALENDAR_TIMEZONE)
except ZoneInfoNotFoundError:
    LOCAL_TZ = timezone.utc
MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "fourteen": 14,
}
WEEKDAYS = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}


def is_authorized(update: Update) -> bool:
    user = update.effective_user
    return user is not None and ALLOWED_USER_ID is not None and user.id == ALLOWED_USER_ID


def remember_message(user_id: int, role: str, content: str) -> None:
    history = CHAT_MEMORY.setdefault(user_id, [])
    history.append({"role": role, "content": content})
    del history[:-10]


def format_chat_prompt(user_id: int, user_input: str) -> str:
    lines = [f"System: {SYSTEM_PROMPT}"]
    for item in CHAT_MEMORY.get(user_id, []):
        role = "User" if item["role"] == "user" else "Bubbles"
        lines.append(f"{role}: {item['content']}")
    lines.append(f"User: {user_input}")
    lines.append("Bubbles:")
    return "\n".join(lines)


def ask_ollama(user_id: int, user_input: str) -> str:
    prompt = format_chat_prompt(user_id, user_input)
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False
            },
            timeout=120
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "No response from Ollama.")
    except Exception as e:
        return f"❌ Ollama error: {e}"


def run_command(cmd: list[str]) -> str:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=True
        )
        return result.stdout.strip() or "✅ Done."
    except subprocess.CalledProcessError as e:
        return e.stdout.strip() or e.stderr.strip() or f"❌ Command failed: {e.returncode}"
    except Exception as e:
        return f"❌ Error: {e}"


def token_has_calendar_scopes(path: Path) -> bool:
    try:
        token_data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    granted_scopes = set(token_data.get("scopes", []))
    return all(scope in granted_scopes for scope in CALENDAR_SCOPES)


def get_calendar_service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as e:
        raise RuntimeError(
            "Google Calendar libraries are not installed. Run: "
            "pip install -r requirements.txt"
        ) from e

    creds = None
    if GOOGLE_TOKEN_PATH.exists() and token_has_calendar_scopes(GOOGLE_TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_PATH), CALENDAR_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            GOOGLE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError(
                "Google Calendar is not authorized yet, or the existing token "
                "does not include event write access. Put your OAuth desktop "
                f"credentials at {GOOGLE_CREDENTIALS_PATH}, delete {GOOGLE_TOKEN_PATH}, and run: "
                "python3 bubbles.py --google-auth"
            )

    return build("calendar", "v3", credentials=creds)


def setup_google_calendar_auth() -> str:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as e:
        raise RuntimeError(
            "Google Calendar libraries are not installed. Run: "
            "pip install -r requirements.txt"
        ) from e

    if not GOOGLE_CREDENTIALS_PATH.exists():
        raise RuntimeError(
            f"Missing {GOOGLE_CREDENTIALS_PATH}. Download an OAuth desktop client "
            "JSON file from Google Cloud and save it there."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(GOOGLE_CREDENTIALS_PATH), CALENDAR_SCOPES)
    creds = flow.run_local_server(port=0)
    GOOGLE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return f"Google Calendar authorized. Token saved to {GOOGLE_TOKEN_PATH}."


def list_calendar_events(days: int = 7, max_results: int = 10) -> list[dict]:
    service = get_calendar_service()
    now = datetime.now(timezone.utc)
    time_max = now + timedelta(days=max(1, min(days, 60)))
    result = (
        service.events()
        .list(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=now.isoformat(),
            timeMax=time_max.isoformat(),
            maxResults=max(1, min(max_results, 25)),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return result.get("items", [])


def event_start_text(event: dict) -> str:
    start = event.get("start", {})
    return start.get("dateTime") or start.get("date") or "unknown time"


def format_calendar_events(events: list[dict], empty_message: str = "No upcoming events found.") -> str:
    if not events:
        return empty_message

    lines = []
    for event in events:
        title = event.get("summary", "(no title)")
        location = event.get("location", "")
        suffix = f" — {location}" if location else ""
        lines.append(f"- {event_start_text(event)}: {title}{suffix}")
    return "\n".join(lines)


def parse_calendar_date(value: str) -> tuple[dict, dict]:
    raw = value.strip()
    normalized = raw.replace("Z", "+00:00")

    if len(raw) == 10:
        start_date = datetime.strptime(raw, "%Y-%m-%d").date()
        end_date = start_date + timedelta(days=1)
        return {"date": start_date.isoformat()}, {"date": end_date.isoformat()}

    for candidate in (normalized, normalized.replace(" ", "T", 1)):
        try:
            start = datetime.fromisoformat(candidate)
            break
        except ValueError:
            start = None
    if start is None:
        raise ValueError("Use YYYY-MM-DD, YYYY-MM-DD HH:MM, or YYYY-MM-DDTHH:MM.")

    end = start + timedelta(hours=1)
    start_value = {"dateTime": start.isoformat(), "timeZone": GOOGLE_CALENDAR_TIMEZONE}
    end_value = {"dateTime": end.isoformat(), "timeZone": GOOGLE_CALENDAR_TIMEZONE}
    return start_value, end_value


def next_month_day(month: int, day: int) -> str:
    today = datetime.now(LOCAL_TZ).date()
    year = today.year
    candidate = datetime(year, month, day).date()
    if candidate < today:
        candidate = datetime(year + 1, month, day).date()
    return candidate.isoformat()


def next_weekday(weekday: int) -> str:
    today = datetime.now(LOCAL_TZ).date()
    days_ahead = (weekday - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (today + timedelta(days=days_ahead)).isoformat()


def title_case_event(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip())
    cleaned = re.sub(r"^(an?|the)\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned[:1].upper() + cleaned[1:] if cleaned else cleaned


def parse_human_date(value: str) -> str | None:
    text = value.strip().lower().replace(",", " ")
    text = re.sub(r"\s+", " ", text)
    today = datetime.now(LOCAL_TZ).date()

    if re.search(r"\btoday\b", text):
        return today.isoformat()
    if re.search(r"\btomorrow\b", text):
        return (today + timedelta(days=1)).isoformat()

    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if iso_match:
        return iso_match.group(1)

    for weekday_match in re.finditer(r"\b(?:next\s+)?([a-z]+)\b", text):
        if weekday_match.group(1) in WEEKDAYS:
            return next_weekday(WEEKDAYS[weekday_match.group(1)])

    day_month = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]+)\b", text)
    if day_month and day_month.group(2) in MONTHS:
        return next_month_day(MONTHS[day_month.group(2)], int(day_month.group(1)))

    month_day = re.search(r"\b([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\b", text)
    if month_day and month_day.group(1) in MONTHS:
        return next_month_day(MONTHS[month_day.group(1)], int(month_day.group(2)))

    return None


def parse_human_time(value: str) -> str | None:
    text = value.strip().lower()
    am_pm = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text)
    if am_pm:
        hour = int(am_pm.group(1))
        minute = int(am_pm.group(2) or "0")
        marker = am_pm.group(3)
        if hour == 12:
            hour = 0
        if marker == "pm":
            hour += 12
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    twenty_four = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    if twenty_four:
        return f"{int(twenty_four.group(1)):02d}:{int(twenty_four.group(2)):02d}"

    return None


def parse_duration_minutes(value: str) -> int | None:
    text = value.strip().lower()
    hour_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b", text)
    if hour_match:
        return max(1, int(float(hour_match.group(1)) * 60))

    minute_match = re.search(r"\b(\d{1,3})\s*(?:minutes?|mins?|m)\b", text)
    if minute_match:
        return max(1, int(minute_match.group(1)))

    if "half hour" in text:
        return 30
    if "hour" in text:
        return 60
    return None


def parse_days_from_text(value: str, default: int = 7) -> int:
    lowered = value.lower()
    digit_match = re.search(r"\b(\d{1,2})\s+days?\b", lowered)
    if digit_match:
        return max(1, min(int(digit_match.group(1)), 60))

    for word, number in NUMBER_WORDS.items():
        if re.search(rf"\b{word}\s+days?\b", lowered):
            return max(1, min(number, 60))

    if re.search(r"\bweek\b", lowered):
        return 7

    return default


def asks_for_calendar_range(value: str) -> bool:
    lowered = value.lower()
    has_day_count = bool(re.search(r"\b\d{1,2}\s+days?\b", lowered))
    has_day_word = any(re.search(rf"\b{word}\s+days?\b", lowered) for word in NUMBER_WORDS)
    has_week = bool(re.search(r"\bweek\b", lowered))
    has_calendar_word = any(
        word in lowered
        for word in ("appointment", "appointments", "meeting", "meetings", "calendar", "schedule")
    )
    return (has_day_count or has_day_word or has_week) and has_calendar_word


def is_schedule_intent(value: str) -> bool:
    lowered = value.lower()
    phrases = (
        "schedule",
        "create appointment",
        "new appointment",
        "add appointment",
        "add to calendar",
        "put on my calendar",
        "book",
        "set up",
        "create a call",
        "add a call",
        "calendar event",
    )
    return any(phrase in lowered for phrase in phrases)


def extract_event_request(value: str) -> dict | None:
    if not is_schedule_intent(value):
        return None

    match = re.search(
        r"\b(?:create|schedule|add|book|put)\s+(?P<title>.+?)\s+(?:for|on)\s+(?P<date>.+)$",
        value,
        flags=re.IGNORECASE,
    )

    if match:
        title = title_case_event(match.group("title"))
        date_phrase = match.group("date").strip()
    else:
        title = ""
        date_phrase = value

    return {
        "title": title,
        "date": parse_human_date(date_phrase),
        "time": parse_human_time(date_phrase),
        "duration_minutes": parse_duration_minutes(value),
        "location": "",
    }


def parse_reminder_choice(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"yes", "y", "true", "1"}:
        return True
    if normalized in {"no", "n", "false", "0", "none"}:
        return False
    raise ValueError("Reminder choice must be yes or no.")


def build_event_reminders(wants_reminders: bool, count_text: str) -> dict:
    if not wants_reminders:
        return {"useDefault": False, "overrides": []}

    try:
        count = int(count_text.strip())
    except ValueError as e:
        raise ValueError("Reminder count must be a number.") from e

    count = max(1, min(count, len(REMINDER_MINUTES)))
    return {
        "useDefault": False,
        "overrides": [
            {"method": "popup", "minutes": minutes}
            for minutes in REMINDER_MINUTES[:count]
        ],
    }


def create_calendar_event(
    title: str,
    date_text: str,
    wants_reminders: bool,
    reminder_count_text: str,
    description: str = "",
    duration_minutes: int = 60,
    location: str = "",
) -> dict:
    service = get_calendar_service()
    start, end = parse_calendar_date(date_text)
    if "dateTime" in start:
        start_dt = datetime.fromisoformat(start["dateTime"])
        end_dt = start_dt + timedelta(minutes=max(1, duration_minutes))
        end["dateTime"] = end_dt.isoformat()

    event = {
        "summary": title.strip(),
        "start": start,
        "end": end,
        "reminders": build_event_reminders(wants_reminders, reminder_count_text),
    }
    if description.strip():
        event["description"] = description.strip()
    if location.strip():
        event["location"] = location.strip()

    return (
        service.events()
        .insert(calendarId=GOOGLE_CALENDAR_ID, body=event)
        .execute()
    )


def calendar_summary(days: int = 7) -> str:
    events = list_calendar_events(days=days)
    return f"📅 Upcoming calendar events ({days} days)\n\n{format_calendar_events(events)}"


def next_appointment_summary() -> str:
    events = list_calendar_events(days=60, max_results=1)
    return "📅 Next appointment\n\n" + format_calendar_events(events, "No upcoming appointments found.")


def next_available_day_summary(days: int = 14) -> str:
    events = list_calendar_events(days=days, max_results=25)
    busy_dates = {event_start_text(event)[:10] for event in events if event_start_text(event) != "unknown time"}
    today = datetime.now(timezone.utc).date()

    for offset in range(days):
        candidate = today + timedelta(days=offset)
        if candidate.isoformat() not in busy_dates:
            return f"📅 Next available day\n\n{candidate.isoformat()} has no events on {GOOGLE_CALENDAR_ID}."

    return f"📅 Next available day\n\nNo fully open day found in the next {days} days."


def parse_positive_int(args: list[str], default: int, maximum: int) -> int:
    if not args:
        return default
    try:
        return max(1, min(int(args[0]), maximum))
    except ValueError:
        return default


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ Not authorized.")
        return

    await update.message.reply_text(
        "🤖 Bubbles is online.\n\n"
        "Commands:\n"
        "/id\n"
        "/status\n"
        "/calendar [days]\n"
        "/next\n"
        "/free [days]\n"
        "/add_event <title> | <date> | <reminders yes/no> | <reminder count> | [description]\n"
        "/calendar_setup\n"
        "/ls [path]\n"
        "/read <path>\n"
        "/write <path> | <content>\n\n"
        "You can also ask things like \"What's my next upcoming appointment?\" "
        "or \"Create a call with Sam for the 25th of April.\""
    )


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ Not authorized.")
        return

    user = update.effective_user
    if user is None:
        return

    username = f"@{user.username}" if user.username else "(no username)"
    await update.message.reply_text(
        f"Your Telegram user ID is: {user.id}\nUsername: {username}"
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ Not authorized.")
        return

    cpu = run_command(["bash", "-lc", "uptime"])
    ram = run_command(["bash", "-lc", "free -h"])
    disk = run_command(["bash", "-lc", "df -h /"])

    reply = f"🖥️ System Status\n\nUptime:\n{cpu}\n\nRAM:\n{ram}\n\nDisk:\n{disk}"
    await update.message.reply_text(reply[:4000])


async def calendar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ Not authorized.")
        return

    days = parse_positive_int(context.args, default=7, maximum=60)
    try:
        await update.message.reply_text(calendar_summary(days)[:4000])
    except Exception as e:
        await update.message.reply_text(f"❌ Calendar error: {e}")


async def next_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ Not authorized.")
        return

    try:
        await update.message.reply_text(next_appointment_summary()[:4000])
    except Exception as e:
        await update.message.reply_text(f"❌ Calendar error: {e}")


async def free_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ Not authorized.")
        return

    days = parse_positive_int(context.args, default=14, maximum=60)
    try:
        await update.message.reply_text(next_available_day_summary(days)[:4000])
    except Exception as e:
        await update.message.reply_text(f"❌ Calendar error: {e}")


async def add_event_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ Not authorized.")
        return

    raw = update.message.text.partition(" ")[2].strip()
    parts = [part.strip() for part in raw.split("|")]
    if len(parts) < 4 or not parts[0] or not parts[1]:
        await update.message.reply_text(
            "Usage: /add_event <title> | <date> | <reminders yes/no> | "
            "<reminder count> | [description]\n\n"
            "Date examples: 2026-04-25 or 2026-04-25 14:30"
        )
        return

    title, date_text, reminder_choice, reminder_count = parts[:4]
    description = parts[4] if len(parts) > 4 else ""

    try:
        wants_reminders = parse_reminder_choice(reminder_choice)
        event = create_calendar_event(
            title,
            date_text,
            wants_reminders,
            reminder_count,
            description,
        )
        await update.message.reply_text(
            "✅ Calendar event added\n\n"
            f"{event_start_text(event)}: {event.get('summary', title)}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Calendar error: {e}")


async def calendar_setup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ Not authorized.")
        return

    await update.message.reply_text(
        "Google Calendar setup:\n\n"
        "1. Enable the Google Calendar API in Google Cloud.\n"
        "2. Create an OAuth client ID for a Desktop app.\n"
        f"3. Save the downloaded JSON as {GOOGLE_CREDENTIALS_PATH}.\n"
        "4. On this machine, run: python3 bubbles.py --google-auth\n\n"
        "After that, use /calendar, /next, /free, or /add_event."
    )


async def ls_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ Not authorized.")
        return

    path = " ".join(context.args).strip() if context.args else "."
    try:
        items = os.listdir(path)
        if not items:
            await update.message.reply_text("Folder is empty.")
            return
        await update.message.reply_text("\n".join(items)[:4000])
    except Exception as e:
        await update.message.reply_text(f"❌ Error reading folder: {e}")


async def read_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ Not authorized.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /read <path>")
        return

    path = " ".join(context.args).strip()
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        await update.message.reply_text(content[:4000] if content else "(empty file)")
    except Exception as e:
        await update.message.reply_text(f"❌ Error reading file: {e}")


async def write_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ Not authorized.")
        return

    raw = update.message.text[len("/write "):].strip()
    if "|" not in raw:
        await update.message.reply_text("Usage: /write <path> | <content>")
        return

    path, content = raw.split("|", 1)
    path = path.strip()
    content = content.lstrip()

    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        await update.message.reply_text(f"✅ Wrote to {path}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error writing file: {e}")


async def send_text(update: Update, text: str, remember: bool = True) -> None:
    await update.message.reply_text(text[:4000])
    user = update.effective_user
    if remember and user is not None:
        remember_message(user.id, "assistant", text[:4000])


async def continue_event_draft(update: Update, user_input: str) -> bool:
    user = update.effective_user
    if user is None or user.id not in PENDING_EVENTS:
        return False

    lowered = user_input.strip().lower()
    if lowered in {"cancel", "stop", "never mind", "nevermind"}:
        PENDING_EVENTS.pop(user.id, None)
        await send_text(update, "Canceled the calendar event.")
        return True

    draft = PENDING_EVENTS[user.id]
    step = draft.get("step")

    try:
        if step == "title":
            title = title_case_event(user_input)
            if not title:
                await send_text(update, "What should I call the appointment?")
                return True
            draft["title"] = title
            draft["step"] = "date"
            await send_text(update, "What date should that be?")
            return True

        if step == "date":
            parsed_date = parse_human_date(user_input)
            if not parsed_date:
                await send_text(update, "What date should that be? For example: tomorrow, next Friday, or April 25.")
                return True
            draft["date"] = parsed_date
            draft["step"] = "time"
            await send_text(update, "What time should it start?")
            return True

        if step == "time":
            parsed_time = parse_human_time(user_input)
            if not parsed_time:
                await send_text(update, "What time should it start? For example: 2pm or 14:30.")
                return True
            draft["time"] = parsed_time
            draft["step"] = "duration"
            await send_text(update, "How long should it be? You can say 30 minutes or 1 hour.")
            return True

        if step == "duration":
            duration = parse_duration_minutes(user_input)
            if duration is None:
                await send_text(update, "How long should it be? For example: 30 minutes or 1 hour.")
                return True
            draft["duration_minutes"] = duration
            draft["step"] = "location"
            await send_text(update, "Any location for it?")
            return True

        if step == "location":
            draft["location"] = "" if lowered in {"no", "none", "skip", "nope"} else user_input.strip()
            draft["step"] = "reminders"
            await send_text(update, "Do you want any reminders?")
            return True

        if step == "reminders":
            try:
                wants_reminders = parse_reminder_choice(user_input)
            except ValueError:
                await send_text(update, "Do you want any reminders? Please answer yes or no.")
                return True
            draft["wants_reminders"] = wants_reminders
            if wants_reminders:
                draft["step"] = "reminder_count"
                await send_text(update, "How many reminders do you want?")
            else:
                draft["reminder_count"] = "0"
                draft["step"] = "description"
                await send_text(update, "Any description you want to add?")
            return True

        if step == "reminder_count":
            try:
                int(user_input.strip())
            except ValueError:
                await send_text(update, "How many reminders do you want? Send a number from 1 to 5.")
                return True
            draft["reminder_count"] = user_input.strip()
            draft["step"] = "description"
            await send_text(update, "Any description you want to add?")
            return True

        if step == "description":
            description = "" if lowered in {"no", "none", "skip", "nope"} else user_input.strip()
            date_text = f"{draft['date']} {draft['time']}"
            event = create_calendar_event(
                draft["title"],
                date_text,
                bool(draft.get("wants_reminders")),
                str(draft.get("reminder_count", "0")),
                description,
                int(draft.get("duration_minutes", 60)),
                str(draft.get("location", "")),
            )
            PENDING_EVENTS.pop(user.id, None)
            await send_text(
                update,
                "✅ Calendar event added\n\n"
                f"{event_start_text(event)}: {event.get('summary', draft['title'])}"
            )
            return True
    except Exception as e:
        PENDING_EVENTS.pop(user.id, None)
        await send_text(update, f"❌ Calendar error: {e}")
        return True

    return False


async def start_event_draft(update: Update, request: dict) -> None:
    user = update.effective_user
    if user is None:
        return

    draft = {
        "title": request["title"],
        "date": request.get("date"),
        "time": request.get("time"),
        "duration_minutes": request.get("duration_minutes"),
        "location": request.get("location", ""),
    }
    if not draft["title"]:
        draft["step"] = "title"
        PENDING_EVENTS[user.id] = draft
        await send_text(update, "Sure. What should I call the appointment?")
        return

    if not draft["date"]:
        draft["step"] = "date"
        PENDING_EVENTS[user.id] = draft
        await send_text(update, "What date should that be?")
        return

    if not draft["time"]:
        draft["step"] = "time"
        PENDING_EVENTS[user.id] = draft
        await send_text(update, "What time should it start?")
        return

    if not draft["duration_minutes"]:
        draft["step"] = "duration"
        PENDING_EVENTS[user.id] = draft
        await send_text(update, "How long should it be?")
        return

    if not draft["location"]:
        draft["step"] = "location"
        PENDING_EVENTS[user.id] = draft
        await send_text(update, "Any location for it?")
        return

    draft["step"] = "reminders"
    PENDING_EVENTS[user.id] = draft
    await send_text(update, "Do you want any reminders?")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ Not authorized.")
        return

    if not update.message or not update.message.text:
        return

    user = update.effective_user
    if user is None:
        return

    user_input = update.message.text.strip()
    lowered = user_input.lower()

    if user.id in PENDING_EVENTS:
        remember_message(user.id, "user", user_input)

    if await continue_event_draft(update, user_input):
        return

    try:
        event_request = extract_event_request(user_input)
        if event_request:
            remember_message(user.id, "user", user_input)
            await start_event_draft(update, event_request)
            return

        if asks_for_calendar_range(user_input):
            remember_message(user.id, "user", user_input)
            await send_text(update, calendar_summary(parse_days_from_text(user_input)))
            return

        if "next appointment" in lowered or "next meeting" in lowered or "upcoming appointment" in lowered:
            remember_message(user.id, "user", user_input)
            await send_text(update, next_appointment_summary())
            return
        if "next available" in lowered or "available day" in lowered or "opening" in lowered:
            remember_message(user.id, "user", user_input)
            await send_text(update, next_available_day_summary())
            return
        if "calendar" in lowered and ("check" in lowered or "what" in lowered or "show" in lowered):
            remember_message(user.id, "user", user_input)
            await send_text(update, calendar_summary(parse_days_from_text(user_input)))
            return
    except Exception as e:
        remember_message(user.id, "user", user_input)
        await send_text(update, f"❌ Calendar error: {e}")
        return

    reply = ask_ollama(user.id, user_input)
    remember_message(user.id, "user", user_input)
    await send_text(update, reply)


def main():
    if "--google-auth" in sys.argv:
        try:
            print(setup_google_calendar_auth())
        except RuntimeError as e:
            print(f"❌ {e}")
            raise SystemExit(1) from e
        return

    if not BOT_TOKEN:
        raise RuntimeError("Missing BUBBLES_BOT_TOKEN. Add it to .env or export it in the environment.")
    if ALLOWED_USER_ID is None:
        raise RuntimeError("Missing BUBBLES_ALLOWED_USER_ID. Add your Telegram numeric user ID to .env.")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("calendar", calendar_command))
    app.add_handler(CommandHandler("next", next_command))
    app.add_handler(CommandHandler("free", free_command))
    app.add_handler(CommandHandler("add_event", add_event_command))
    app.add_handler(CommandHandler("calendar_setup", calendar_setup_command))
    app.add_handler(CommandHandler("ls", ls_command))
    app.add_handler(CommandHandler("read", read_command))
    app.add_handler(CommandHandler("write", write_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bubbles (@bubbles_sys_bot) is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
