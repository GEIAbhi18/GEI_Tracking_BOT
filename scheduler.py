import logging
from datetime import datetime
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
# pyrefly: ignore [missing-import]
from telegram.ext import ContextTypes
from config import EMPLOYEE_CHAT_ID, DIRECTOR_CHAT_ID, TIMEZONE
from db import (
    get_todays_updates, get_upcoming_deadlines, get_all_tasks,
    get_active_users_with_tasks, get_tasks_for_user, supabase,
)
from rag import calculate_project_rag, calculate_rag

logger = logging.getLogger(__name__)


async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    """
    5PM Reminder — sends personalized task reminders to ALL team members
    who have active (non-completed) tasks and have NOT submitted any
    updates today.  Each user gets their own task list.
    """
    logger.info("Running 5PM reminder for all team members...")
    try:
        users = get_active_users_with_tasks()
        if not users:
            logger.info("No active users with tasks found — skipping 5PM reminder.")
            return

        today = datetime.now().date().isoformat()
        sent_count = 0
        skipped_count = 0

        for user in users:
            tid = user.get("telegram_id")
            name = user.get("name", "Team Member")

            # Skip users without a Telegram ID (they may be WhatsApp-only)
            if not tid:
                logger.info(f"ℹ️ {name} has no telegram_id — skipping Telegram 5PM reminder.")
                continue

            # Check if this user already submitted any updates today
            try:
                upds_res = (
                    supabase.table("updates")
                    .select("id")
                    .eq("employee_id", user["id"])
                    .gte("timestamp", today)
                    .execute()
                )
                if upds_res.data:
                    logger.info(f"ℹ️ {name} already updated tasks today — skipping 5PM reminder.")
                    skipped_count += 1
                    continue
            except Exception as check_err:
                logger.warning(f"Could not check today's updates for {name}: {check_err}")

            # Get this user's active tasks
            tasks = get_tasks_for_user(user["id"])
            active_tasks = [t for t in tasks if t.get("status") != "Completed"]

            if not active_tasks:
                logger.info(f"ℹ️ {name} has no active tasks — skipping 5PM reminder.")
                continue

            # Build personalized message with their task list
            msg = f"Hi {name} 👋\n"
            msg += "You haven't updated any tasks today. Please share updates on your ongoing tasks:\n\n"
            for i, t in enumerate(active_tasks, 1):
                p_name = t["projects"]["name"] if t.get("projects") else "No Project"
                msg += f"{i}. {t['name']} - {p_name}\n"
            msg += "\nReply with updates in natural language."

            try:
                await context.bot.send_message(chat_id=tid, text=msg)
                sent_count += 1
                logger.info(f"✅ 5PM reminder sent successfully to {name} (telegram_id: {tid})")
            except Exception as send_err:
                logger.error(f"❌ Failed to send 5PM reminder to {name} (telegram_id: {tid}): {send_err}")

        logger.info(f"5PM reminder complete — sent: {sent_count}, skipped (already updated): {skipped_count}")

    except Exception as e:
        logger.error(f"Error in 5PM send_reminder: {e}", exc_info=True)


async def send_deadline_alerts(context: ContextTypes.DEFAULT_TYPE):
    if not EMPLOYEE_CHAT_ID:
        logger.error("EMPLOYEE_CHAT_ID is not set in environment variables. Cannot send deadline alerts.")
        return
    logger.info("Checking for upcoming deadlines...")
    try:
        deadlines = get_upcoming_deadlines()
        if not deadlines:
            return
            
        alert_text = "⚠️ *Deadline Alert*\n\n"
        for task in deadlines:
            project_name = task.get("projects", {}).get("name", "N/A")
            alert_text += f"*{project_name}* -> {task['name']}\n"
            alert_text += f"⏳ Due: {task['deadline']}\n\n"
            
        await context.bot.send_message(
            chat_id=EMPLOYEE_CHAT_ID,
            text=alert_text,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error sending deadline alerts to {EMPLOYEE_CHAT_ID}: {e}")

async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    """
    6PM Daily Report — sends project summary to Kanav (Director).
    Resolves Kanav's telegram_id from DB instead of relying on
    DIRECTOR_CHAT_ID env var, for consistency with bot.py.
    Falls back to DIRECTOR_CHAT_ID if DB lookup fails.
    """
    logger.info("Generating 6PM daily report for Kanav (Director)...")

    # Resolve Kanav's telegram_id from DB
    target_chat_id = None
    try:
        res = supabase.table("users").select("telegram_id").eq("name", "Kanav").execute()
        if res.data and res.data[0].get("telegram_id"):
            target_chat_id = res.data[0]["telegram_id"]
            logger.info(f"Resolved Kanav's telegram_id from DB: {target_chat_id}")
    except Exception as db_err:
        logger.warning(f"DB lookup for Kanav failed: {db_err}")

    # Fallback to DIRECTOR_CHAT_ID env var
    if not target_chat_id:
        if DIRECTOR_CHAT_ID:
            target_chat_id = DIRECTOR_CHAT_ID
            logger.info(f"Using DIRECTOR_CHAT_ID fallback: {target_chat_id}")
        else:
            logger.error("Cannot send 6PM report: Kanav not found in DB and DIRECTOR_CHAT_ID env var is not set.")
            return

    try:
        updates = get_todays_updates()
        all_tasks = get_all_tasks()
        
        # Build project -> tasks logic with RAG 
        projects_data = {}
        for t in all_tasks:
            pid = t['project_id']
            pname = t.get('projects', {}).get('name', 'Uncategorized')
            if pname not in projects_data:
                projects_data[pname] = {'id': pid, 'tasks': []}
                
            task_updated = False
            task_rag_color = "RED" # Default assuming missed 
            
            for u in updates:
                if u['task_id'] == t['id']:
                    task_updated = True
                    task_rag_color = u['rag']
                    projects_data[pname]['tasks'].append({
                        'name': t['name'],
                        'rag': u['rag'],
                        'progress': u['progress'],
                        'blockers': u['blockers'],
                        'deadline': t['deadline'],
                        'updated': True
                    })
                    break
            
            if not task_updated:
                # Instead of defaulting to RED, check if it's a future task
                def parse_dt(dt_str):
                    if not dt_str: return None
                    try:
                        return datetime.fromisoformat(str(dt_str).replace('Z', '+00:00'))
                    except:
                        return None
                
                t_start = parse_dt(t.get("planned_start_date") or t.get("created_at"))
                t_dl = parse_dt(t.get("deadline"))
                
                rag_color, _ = calculate_rag(0, t_start, t_dl, "", missed_updates=1 if t_start and datetime.now(t_start.tzinfo if t_start.tzinfo else None) > t_start else 0)
                
                # If it's not started, we don't consider it a "missed response" red
                if rag_color == "NOT_STARTED":
                    blocker_msg = "Task has not begin."
                else:
                    rag_color = "RED"
                    blocker_msg = "No update received."

                projects_data[pname]['tasks'].append({
                    'name': t['name'],
                    'rag': rag_color,
                    'progress': 0,
                    'blockers': blocker_msg,
                    'deadline': t['deadline'],
                    'updated': False
                })

        report_text = "📊 *6PM Project Summary*\n\n"
        buttons = []
        
        emoji_map = {"RED": "🔴", "AMBER": "🟡", "GREEN": "🟢", "NOT_STARTED": "⚪"}
        
        for p_name, p_info in projects_data.items():
            task_rags = [t['rag'] for t in p_info['tasks']]
            proj_rag = calculate_project_rag(task_rags)
            
            report_text += f"{p_name} ➔ {emoji_map.get(proj_rag, '⚪')}\n"
            
            buttons.append([InlineKeyboardButton(f"[{p_name} Details]", callback_data=f"proj_{p_info['id']}")])
        
        await context.bot.send_message(
            chat_id=target_chat_id,
            text=report_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        logger.info(f"✅ 6PM daily report sent successfully to Kanav (telegram_id: {target_chat_id})")
    except Exception as e:
        logger.error(f"❌ Error sending 6PM report to Kanav (telegram_id: {target_chat_id}): {e}")
