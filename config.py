import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

EMPLOYEE_CHAT_ID = int(os.getenv("EMPLOYEE_CHAT_ID", "0"))
DIRECTOR_CHAT_ID = int(os.getenv("DIRECTOR_CHAT_ID", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
GROQCLOUD_API_KEY = os.getenv("GROQCLOUD_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini") # Default to gemini

