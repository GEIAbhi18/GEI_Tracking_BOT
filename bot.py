import logging
import datetime
import os
import pytz
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from config import TELEGRAM_BOT_TOKEN
from db import get_user_by_telegram_id, supabase
from core.intent_handlers import generate_pdf_report
from core.update_engine import process_update_message
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
    u_info = get_user_by_telegram_id(user_id)
    name = u_info['name'] if u_info else "there"
    await update.message.reply_text(f"Hi {name}, What can I help you with?")

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
        await process_update_message(text=user_message, user_id=user_id, images=images, send_reply_func=reply_function)
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

application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))
tz = pytz.timezone('Asia/Kolkata')
job_time = datetime.time(hour=18, minute=0, tzinfo=tz)
application.job_queue.run_daily(send_daily_report_job, time=job_time, days=(0,1,2,3,4,5))
application.job_queue.run_daily(send_multiline_updates_report_job, time=job_time, days=(0,1,2,3,4,5))

def start_bot():
    from core.reminder_scheduler import setup_reminder_scheduler
    from scheduler import start_scheduler
    logging.info(f"BOOTING PROCESS: {os.getpid()}")
    start_scheduler(application)
    setup_reminder_scheduler(application)
    logging.info("Starting GEI Telegram Bot...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    start_bot()
