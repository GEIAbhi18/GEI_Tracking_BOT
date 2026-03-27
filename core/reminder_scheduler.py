import logging
import asyncio
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from db import get_active_users_with_tasks, get_tasks_for_user, supabase
from core.context_manager import update_context as set_context

logger = logging.getLogger(__name__)

async def send_reminder_to_user(application, user, reason="scheduled"):
    """Sends a reminder message to a specific user and updates their state."""
    tid = user.get('telegram_id')
    if not tid:
        return

    # Check cooldown: max 2 reminders per day (excluding manual)
    # Manual triggers are handled by the intent handler, not here.
    # We can check last_reminder_at to see if we already sent 2 today.
    # For simplicity, we just check if last_reminder_at was within last few hours for inactivity.
    
    tasks = get_tasks_for_user(user['id'])
    active_tasks = [t for t in tasks if t['status'] != 'completed']
    
    if not active_tasks:
        return

    # Format message
    msg = f"Hi {user['name']} 👋\n"
    if reason == "inactivity":
        msg += "You haven’t updated any tasks for a while.\n"
    else:
        msg += "Please share updates on your ongoing tasks:\n"
        
    for i, t in enumerate(active_tasks, 1):
        p_name = t['projects']['name'] if t.get('projects') else "No Project"
        msg += f"{i}. {t['name']} - {p_name}\n"
    
    msg += "\nReply with updates in natural language."

    try:
        await application.bot.send_message(chat_id=tid, text=msg)
        
        # Update last_reminder_at
        supabase.table("users").update({"last_reminder_at": datetime.now().isoformat()}).eq("id", user['id']).execute()
        
        # Context Integration (Step 7)
        # We use a helper to update context for the specific user tid
        from core.context_manager import update_context
        update_context(tid, last_prompt="awaiting_updates")
        
        logger.info(f"Reminder sent to {user['name']} ({tid}) due to {reason}")
    except Exception as e:
        logger.error(f"Failed to send reminder to {user['name']}: {e}")

async def check_inactivity_and_notify(application):
    """Checks for inactive users (> 4 hours) and notifies them."""
    logger.info("Running inactivity check...")
    users = get_active_users_with_tasks()
    now = datetime.now()
    threshold = timedelta(hours=4)
    
    for user in users:
        last_act_str = user.get('last_activity_at')
        if not last_act_str:
            continue
            
        try:
            last_act = datetime.fromisoformat(last_act_str.replace('Z', '+00:00'))
            # If naive, make it aware (assuming local time)
            if last_act.tzinfo is None:
                from config import TIMEZONE
                import pytz
                tz = pytz.timezone(TIMEZONE)
                last_act = tz.localize(last_act)
                now_aware = datetime.now(tz)
            else:
                now_aware = datetime.now(last_act.tzinfo)
                
            if now_aware - last_act > threshold:
                # Check if we already sent a reminder recently to avoid spam (e.g. last 4 hours)
                last_rem_str = user.get('last_reminder_at')
                already_sent_recently = False
                if last_rem_str:
                    last_rem = datetime.fromisoformat(last_rem_str.replace('Z', '+00:00'))
                    if last_rem.tzinfo is None:
                        last_rem = tz.localize(last_rem)
                    if now_aware - last_rem < timedelta(hours=4):
                        already_sent_recently = True
                
                if not already_sent_recently:
                    await send_reminder_to_user(application, user, reason="inactivity")
        except Exception as e:
            logger.error(f"Error checking inactivity for {user['name']}: {e}")

async def send_scheduled_reminders(application):
    """Sends reminders to all active users at fixed times."""
    logger.info("Running scheduled reminders (11AM/4PM)...")
    users = get_active_users_with_tasks()
    for user in users:
        await send_reminder_to_user(application, user, reason="scheduled")

def setup_reminder_scheduler(application):
    """Initializes the APScheduler for reminders."""
    from config import TIMEZONE
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    
    # 1. Scheduled Reminders (11:00 AM and 4:00 PM)
    scheduler.add_job(send_scheduled_reminders, CronTrigger(hour=11, minute=0), args=[application])
    scheduler.add_job(send_scheduled_reminders, CronTrigger(hour=16, minute=0), args=[application])
    
    # 2. Inactivity Check (Every hour)
    scheduler.add_job(check_inactivity_and_notify, 'interval', minutes=60, args=[application])
    
    scheduler.start()
    logger.info("Hybrid Reminder Scheduler started.")
