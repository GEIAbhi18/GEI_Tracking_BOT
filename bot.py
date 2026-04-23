import logging
import datetime
import os
import pytz
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from config import TELEGRAM_BOT_TOKEN
from db import get_user_by_telegram_id, supabase
from core.intent_handlers import generate_pdf_report
from core.logic import process_user_message
import html, re

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Clear any existing state or context (Requirement 2)
    from core.conversation_state import clear_state
    from core.context_manager import clear_context
    clear_state(user_id)
    clear_context(user_id)
    
    u_info = get_user_by_telegram_id(user_id)
    name = u_info['name'] if u_info else "there"
    await update.message.reply_text(f"Hi {name}, context cleared! What can I help you with today?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = (update.message.text or update.message.caption or "").lstrip('/')
    user_id = update.effective_user.id
    images = []
    if update.message.photo:
        photo_file = await update.message.photo[-1].get_file()
        images.append(photo_file.file_path)
    
    async def reply_function(text: str = None, document: str = None, target_user_id: int = None):
        target = target_user_id if target_user_id else update.effective_chat.id
        if text:
            text_html = html.escape(text)
            text_html = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text_html)
            text_html = re.sub(r'\*(.+?)\*', r'<b>\1</b>', text_html)
        if document:
            with open(document, 'rb') as f:
                if text: await context.bot.send_document(chat_id=target, document=f, caption=text_html, parse_mode='HTML')
                else: await context.bot.send_document(chat_id=target, document=f)
        elif text: await context.bot.send_message(chat_id=target, text=text_html, parse_mode='HTML')
        
    try:
        await process_user_message(text=user_message, user_id=user_id, images=images, send_reply_func=reply_function)
    except Exception as e:
        logging.exception(f"CRITICAL ERROR: {e}")

async def send_daily_report_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        res = supabase.table("users").select("telegram_id").eq("name", "Kanav").execute()
        if res.data:
            target = res.data[0]["telegram_id"]
            path = generate_pdf_report()
            with open(path, 'rb') as f:
                await context.bot.send_document(chat_id=target, document=f, caption="📊 Automated Daily Project Report (6:00 PM)")
    except Exception as e: logging.error(f"Report error: {e}")

async def send_multiline_updates_report_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        res = supabase.table("users").select("telegram_id").eq("name", "Kanav").execute()
        if res.data:
            target = res.data[0]["telegram_id"]
            today = datetime.datetime.now().date().isoformat()
            upds = supabase.table("daily_updates").select("*, projects(name), tasks(name), users(name)").gte("timestamp", today).execute()
            if upds.data:
                from collections import defaultdict
                grouped = defaultdict(list)
                for u in upds.data: grouped[u.get("projects", {}).get("name", "Unknown")].append(u)
                report = "📝 *Daily Updates Summary*\n\n"
                for p, lu in grouped.items():
                    report += f"*{p}*\n"
                    for u in lu:
                        report += f"- {u.get('tasks', {}).get('name', 'Task')} ({u['progress']}%) by {u.get('users', {}).get('name', 'User')}\n"
                        if u.get('blocker') and u['blocker'].lower() not in ["no blocker", "none"]: report += f"  🛑 Blocker: {u['blocker']}\n"
                    report += "\n"
                await context.bot.send_message(chat_id=target, text=report, parse_mode='Markdown')
    except Exception as e: logging.error(f"Multiline report error: {e}")

import telegram

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, telegram.error.Conflict):
        logging.warning("⚠️ Bot conflict detected! (Railway overlap) Waiting for old instance to shut down...")
    else:
        logging.error("Exception while handling an update:", exc_info=context.error)

application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))
application.add_error_handler(error_handler)

tz = pytz.timezone('Asia/Kolkata')
time_9am = datetime.time(hour=9, minute=0, tzinfo=tz)
time_5pm = datetime.time(hour=17, minute=0, tzinfo=tz)
time_6pm = datetime.time(hour=18, minute=0, tzinfo=tz)
weekdays = (0,1,2,3,4,5)

application.job_queue.run_daily(send_daily_report_job, time=time_6pm, days=weekdays)
application.job_queue.run_daily(send_multiline_updates_report_job, time=time_6pm, days=weekdays)

def start_bot():
    from scheduler import send_deadline_alerts, send_reminder, send_daily_report
    from core.reminder_scheduler import send_scheduled_reminders, check_inactivity_and_notify
    
    logging.info(f"BOOTING PROCESS: {os.getpid()}")
    
    # Consolidate all external APScheduler jobs to PTB's native JobQueue
    application.job_queue.run_daily(send_deadline_alerts, time=time_9am, days=weekdays)
    application.job_queue.run_daily(send_reminder, time=time_5pm, days=weekdays)
    application.job_queue.run_daily(send_scheduled_reminders, time=time_5pm, days=weekdays)
    application.job_queue.run_daily(send_daily_report, time=time_6pm, days=weekdays)
    
    # Run every hour (3600s), staggering the first run by 10s
    application.job_queue.run_repeating(check_inactivity_and_notify, interval=3600, first=10)
    
    logging.info("Starting GEI Telegram Bot natively...")
    # drop_pending_updates prevents processing old messages on reboot
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    start_bot()
