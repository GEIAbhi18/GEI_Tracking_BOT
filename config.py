import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

EMPLOYEE_CHAT_ID = int(os.getenv("EMPLOYEE_CHAT_ID", "0"))
DIRECTOR_CHAT_ID = int(os.getenv("DIRECTOR_CHAT_ID", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")
