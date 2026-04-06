import logging
import time
import os
import html, re
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
from config import TELEGRAM_BOT_TOKEN
from core.update_engine import process_update_message
from db import get_user_by_telegram_id, supabase
from core.intent_handlers import generate_pdf_report
import datetime
import pytz

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.info(f"BOOTING PROCESS: {os.getpid()}")
# You can switch these comments out while testing locally
# TEST_USER_ID = 123456789 # Asif Temp ID
# TEST_USER_ID = 987654321 # Kanav Temp ID

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command to welcome the user."""
    user_id = update.effective_user.id
    u_info = get_user_by_telegram_id(user_id)
    name = u_info['name'] if u_info else "there"
    welcome_message = f"Hi {name}, What can I help you with?"
    await update.message.reply_text(welcome_message)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = (update.message.text or update.message.caption or "").lstrip('/')
    user_id = update.effective_user.id
    
    # Extract images if a photo was uploaded
    images = []
    if update.message.photo:
        # Get the highest resolution photo
        photo_file = await update.message.photo[-1].get_file()
        images.append(photo_file.file_path)
    
    # Define how the backend should send replies back to this Telegram user
    async def reply_function(text: str = None, document: str = None, target_user_id: int = None):
        target = target_user_id if target_user_id else update.effective_chat.id
        
        # Safe HTML escaping for Telegram
        if text:
            text_html = html.escape(text)
            text_html = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text_html)
            text_html = re.sub(r'\*(.+?)\*', r'<b>\1</b>', text_html)
        
        if document:
            with open(document, 'rb') as f:
                if text:
                    await context.bot.send_document(chat_id=target, document=f, caption=text_html, parse_mode='HTML')
                else:
                    await context.bot.send_document(chat_id=target, document=f)
        elif text:
            await context.bot.send_message(chat_id=target, text=text_html, parse_mode='HTML')
        
    try:
        # Call the existing shared backend
        await process_update_message(
            text=user_message,
            user_id=user_id,
            images=images,
            send_reply_func=reply_function
        )
    except Exception as e:
        import telegram
        if isinstance(e, telegram.error.TimedOut):
            logging.warning(f"Timeout occurred sending message to {user_id}, message might have still reached user.")
            return # Don't send double error message if it timed out but potentially succeeded
        logging.exception(f"CRITICAL ERROR processing message for user {user_id}: {e}")
        await update.message.reply_text("Sorry, an error occurred while processing your request. Our developers have been notified.")

async def send_daily_report_job(context: ContextTypes.DEFAULT_TYPE):
    """Sends the daily PDF report to Kanav at 6 PM."""
    
    # Get Kanav's true telegram_id dynamically
    try:
        response = supabase.table("users").select("telegram_id").eq("name", "Kanav").execute()
        if not response.data or not response.data[0].get("telegram_id"):
            logging.error("Could not find Kanav's telegram_id in DB for 6PM job.")
            return
        target_user_id = response.data[0]["telegram_id"]
    except Exception as e:
        logging.error(f"Error fetching Kanav's telegram_id: {e}")
        return

    filepath = generate_pdf_report()
    
    with open(filepath, 'rb') as f:
        await context.bot.send_document(
            chat_id=target_user_id, 
            document=f, 
            caption="📊 Automated Daily Project Report (6:00 PM)"
        )

async def send_multiline_updates_report_job(context: ContextTypes.DEFAULT_TYPE):
    """Sends the multi-line daily updates summary to Kanav at 6 PM."""
    from db import supabase # Ensure we use the shared instance
    try:
        response = supabase.table("users").select("telegram_id").eq("name", "Kanav").execute()
        if not response.data or not response.data[0].get("telegram_id"):
            return
        target_user_id = response.data[0]["telegram_id"]
    except Exception:
        return
        
    try:
        from datetime import datetime
        today_iso = datetime.now().date().isoformat()
        updates_res = supabase.table("daily_updates").select("*, projects(name), tasks(name), users(name)").gte("timestamp", today_iso).execute()
        
        updates = updates_res.data
        if not updates:
            return
            
        from collections import defaultdict
        grouped = defaultdict(list)
        for u in updates:
            p_name = u.get("projects", {}).get("name", "Unknown Project") if u.get("projects") else "Unknown Project"
            grouped[p_name].append(u)
            
        report_text = "📝 *Daily Updates Summary*\n\n"
        for p_name, p_updates in grouped.items():
            report_text += f"*{p_name}*\n"
            for u in p_updates:
                t_name = u.get("tasks", {}).get("name", "Unknown Task") if u.get("tasks") else "Unknown Task"
                user_n = u.get("users", {}).get("name", "Unknown User") if u.get("users") else "Unknown User"
                report_text += f"- {t_name} ({u['progress']}%) by {user_n}\n"
                if u.get('blocker') and str(u['blocker']).lower() not in ["no blocker", "none"]:
                    report_text += f"  🛑 Blocker: {u['blocker']}\n"
            report_text += "\n"
        
        await context.bot.send_message(chat_id=target_user_id, text=report_text, parse_mode='Markdown')
    except Exception as e:
        logging.error(f"Failed to generate multiline daily report: {e}")

application = (
    ApplicationBuilder()
    .token(TELEGRAM_BOT_TOKEN)
    .connect_timeout(30)
    .read_timeout(30)
    .write_timeout(30)
    .build()
)

application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))

async def error_handler(update, context):
    logging.error(f"Update {update} caused error: {context.error}")

application.add_error_handler(error_handler)

# Daily report from bot.py
tz = pytz.timezone('Asia/Kolkata')
job_time = datetime.time(hour=18, minute=0, tzinfo=tz)
application.job_queue.run_daily(send_daily_report_job, time=job_time, days=(0, 1, 2, 3, 4, 5))
application.job_queue.run_daily(send_multiline_updates_report_job, time=job_time, days=(0, 1, 2, 3, 4, 5))

def main():
    # Start both scheduler systems inside main to prevent duplicate instances
    from core.reminder_scheduler import setup_reminder_scheduler
    from scheduler import start_scheduler
    
    logging.info(f"BOOTING PROCESS: {os.getpid()}")
    logging.info("Starting GEI Tracking Bot Schedulers...")
    start_scheduler(application)
    setup_reminder_scheduler(application)
    
    logging.info("Starting GEI Telegram Bot in polling mode from bot.py...")
    application.run_polling(
        drop_pending_updates=True,
        close_loop=False
    )

if __name__ == '__main__':
    main()
