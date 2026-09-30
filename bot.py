import datetime
import html
import logging
import os
import re

import pytz
import telegram
from telegram import Update

# pyrefly: ignore [missing-import]
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import TELEGRAM_BOT_TOKEN
from core.error_messages import friendly_system_error
from core.intent_handlers import generate_pdf_report
from core.logic import process_user_message
from db import get_user_by_telegram_id, supabase

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Clear any existing state or context (Requirement 2)
    from core.context_manager import clear_context
    from core.conversation_state import clear_state
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

    async def reply_function(
        text: str | None = None,
        document: str | None = None,
        target_user_id: int | None = None
    ):
        target = target_user_id if target_user_id else update.effective_chat.id
        text_html = None
        if text:
            text_html = html.escape(text)
            text_html = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text_html)
            text_html = re.sub(r'\*(.+?)\*', r'<b>\1</b>', text_html)
        if document:
            with open(document, 'rb') as f:  # noqa: ASYNC230
                if text:
                    await context.bot.send_document(chat_id=target, document=f, caption=text_html, parse_mode='HTML')
                else:
                    await context.bot.send_document(chat_id=target, document=f)
        elif text:
            await context.bot.send_message(chat_id=target, text=text_html, parse_mode='HTML')

    try:
        await process_user_message(text=user_message, user_id=user_id, images=images, send_reply_func=reply_function)
    except Exception:
        logger.exception("CRITICAL ERROR")
        # Always send a friendly message — never leave the user hanging
        try:
            error_msg = friendly_system_error(user_message)
            error_html = html.escape(error_msg)
            await update.message.reply_text(error_html, parse_mode='HTML')
        except Exception as notify_err:  # noqa: BLE001
            logger.debug("Failed to send error fallback: %s", notify_err)


async def send_daily_report_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Running 6PM daily PDF report job for Kanav...")
    try:
        res = supabase.table("users").select("telegram_id").eq("name", "Kanav").execute()
        if not res.data or not res.data[0].get("telegram_id"):
            logger.error("❌ 6PM PDF report: Kanav not found in DB or has no telegram_id configured.")
            return

        target = res.data[0]["telegram_id"]
        from facilities.config import ENABLE_FACILITIES_EOD_REPORT
        teams = ["Tech", "Project"]
        if ENABLE_FACILITIES_EOD_REPORT:
            teams.append("Facilities")
        else:
            logger.info("Evening Facilities EOD report is disabled for now. Skipping Facilities PDF report.")
        for team in teams:
            try:
                path = generate_pdf_report(team_name=team)
                with open(path, 'rb') as f:  # noqa: ASYNC230
                    await context.bot.send_document(chat_id=target, document=f, caption=f"📊 Daily {team} Team Report (6:00 PM)")
                logger.info("✅ 6PM Daily PDF report (%s) sent successfully to Kanav (telegram_id: %s)", team, target)
            except Exception as team_err:  # noqa: BLE001
                logger.error("❌ Failed to send %s PDF report to Kanav (telegram_id: %s): %s", team, target, team_err)
    except Exception:
        logger.exception("❌ 6PM PDF report job error")


async def send_multiline_updates_report_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Running 6PM daily updates summary job for Kanav...")
    try:
        res = supabase.table("users").select("telegram_id").eq("name", "Kanav").execute()
        if not res.data or not res.data[0].get("telegram_id"):
            logger.error("❌ 6PM updates summary: Kanav not found in DB or has no telegram_id configured.")
            return

        target = res.data[0]["telegram_id"]
        today = datetime.datetime.now(pytz.timezone('Asia/Kolkata')).date().isoformat()
        upds = supabase.table("daily_updates").select("*, projects(name), tasks(title), users(name)").gte("timestamp", today).execute()
        if upds.data:
            from collections import defaultdict
            grouped = defaultdict(list)
            for u in upds.data:
                grouped[u.get("projects", {}).get("name", "Unknown")].append(u)
            report = "📝 *Daily Updates Summary*\n\n"
            for p, lu in grouped.items():
                report += f"*{p}*\n"
                for u in lu:
                    report += f"- {u.get('tasks', {}).get('name', 'Task')} ({u['progress']}%) by {u.get('users', {}).get('name', 'User')}\n"
                    if u.get('blocker') and u['blocker'].lower() not in ["no blocker", "none"]:
                        report += f"  🛑 Blocker: {u['blocker']}\n"
                report += "\n"
            await context.bot.send_message(chat_id=target, text=report, parse_mode='Markdown')
            logger.info("✅ 6PM daily updates summary sent successfully to Kanav (telegram_id: %s)", target)
        else:
            logger.info("ℹ️ No daily updates found for today — skipping updates summary to Kanav.")
    except Exception:
        logger.exception("❌ 6PM updates summary job error")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, telegram.error.Conflict):
        logger.warning("⚠️ Bot conflict detected! (Railway overlap) Waiting for old instance to shut down...")
    else:
        logger.error("Exception while handling an update:", exc_info=context.error)


application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))
application.add_error_handler(error_handler)

tz = pytz.timezone('Asia/Kolkata')
time_9am = datetime.time(hour=9, minute=0, tzinfo=tz)
time_5pm = datetime.time(hour=17, minute=0, tzinfo=tz)
time_6pm = datetime.time(hour=18, minute=0, tzinfo=tz)
weekdays = (0, 1, 2, 3, 4, 5)

application.job_queue.run_daily(send_daily_report_job, time=time_6pm, days=weekdays)
application.job_queue.run_daily(send_multiline_updates_report_job, time=time_6pm, days=weekdays)


def start_bot():
    from core.reminder_scheduler import (
        check_inactivity_and_notify,
        send_scheduled_reminders,
    )
    from scheduler import send_daily_report, send_deadline_alerts

    logger.info("BOOTING PROCESS: %s", os.getpid())

    # Consolidate all external APScheduler jobs to PTB's native JobQueue
    application.job_queue.run_daily(send_deadline_alerts, time=time_9am, days=weekdays)
    # 5PM: Single reminder job for ALL team members (checks "no updates today")
    application.job_queue.run_daily(send_scheduled_reminders, time=time_5pm, days=weekdays)
    application.job_queue.run_daily(send_daily_report, time=time_6pm, days=weekdays)

    # Run every hour (3600s), staggering the first run by 10s
    application.job_queue.run_repeating(check_inactivity_and_notify, interval=3600, first=10)

    # Notification Engine worker (every minute)
    from notifications.worker import process_notifications

    async def process_notifications_job(context: ContextTypes.DEFAULT_TYPE):
        process_notifications()
    application.job_queue.run_repeating(process_notifications_job, interval=60, first=5)

    logger.info("Starting GEI Telegram Bot natively...")
    # drop_pending_updates prevents processing old messages on reboot
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    start_bot()
