import os
import requests
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
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

ALLOWED_USER_ID = int(os.getenv("BUBBLES_ALLOWED_USER_ID", "7875049596"))
BOT_TOKEN = os.getenv("BUBBLES_BOT_TOKEN")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
GOOGLE_CREDENTIALS_PATH = Path(os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json"))
GOOGLE_TOKEN_PATH = Path(os.getenv("GOOGLE_TOKEN_PATH", "token.json"))
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def is_authorized(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id == ALLOWED_USER_ID


def ask_ollama(prompt: str) -> str:
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
    if GOOGLE_TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_PATH), CALENDAR_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            GOOGLE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError(
                "Google Calendar is not authorized yet. Put your OAuth desktop "
                f"credentials at {GOOGLE_CREDENTIALS_PATH} and run: "
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
        "/calendar_setup\n"
        "/ls [path]\n"
        "/read <path>\n"
        "/write <path> | <content>\n\n"
        "Send a normal message to chat with Ollama."
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
        "After that, use /calendar, /next, or /free."
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


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ Not authorized.")
        return

    if not update.message or not update.message.text:
        return

    user_input = update.message.text.strip()
    lowered = user_input.lower()
    try:
        if "next appointment" in lowered or "next meeting" in lowered:
            await update.message.reply_text(next_appointment_summary()[:4000])
            return
        if "next available" in lowered or "available day" in lowered:
            await update.message.reply_text(next_available_day_summary()[:4000])
            return
        if "calendar" in lowered and ("check" in lowered or "what" in lowered or "show" in lowered):
            await update.message.reply_text(calendar_summary()[:4000])
            return
    except Exception as e:
        await update.message.reply_text(f"❌ Calendar error: {e}")
        return

    reply = ask_ollama(user_input)
    await update.message.reply_text(reply[:4000])


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

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("calendar", calendar_command))
    app.add_handler(CommandHandler("next", next_command))
    app.add_handler(CommandHandler("free", free_command))
    app.add_handler(CommandHandler("calendar_setup", calendar_setup_command))
    app.add_handler(CommandHandler("ls", ls_command))
    app.add_handler(CommandHandler("read", read_command))
    app.add_handler(CommandHandler("write", write_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bubbles (@bubbles_sys_bot) is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
