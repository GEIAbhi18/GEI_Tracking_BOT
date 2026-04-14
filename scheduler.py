import logging
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from config import EMPLOYEE_CHAT_ID, DIRECTOR_CHAT_ID, TIMEZONE
from db import get_todays_updates, get_upcoming_deadlines, get_all_tasks
from rag import calculate_project_rag, calculate_rag

logger = logging.getLogger(__name__)

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    if not EMPLOYEE_CHAT_ID:
        logger.error("EMPLOYEE_CHAT_ID is not set in environment variables. Cannot send 5PM reminder.")
        return
    logger.info(f"Sending 5PM reminder to employee (ID: {EMPLOYEE_CHAT_ID})...")
    try:
        await context.bot.send_message(
            chat_id=EMPLOYEE_CHAT_ID,
            text="Asif, aaj ke tasks ka update bhejo.\nExample:\n'Top Terrace waterproofing 40% done, material delay' + photo"
        )
    except Exception as e:
        logger.error(f"Error sending reminder to {EMPLOYEE_CHAT_ID}: {e}")

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
    if not DIRECTOR_CHAT_ID:
        logger.error("DIRECTOR_CHAT_ID is not set in environment variables. Cannot send 6PM report.")
        return
    logger.info("Generating daily report for director...")
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
                from datetime import datetime
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
                    blocker_msg = "Asif did not respond."

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
            chat_id=DIRECTOR_CHAT_ID,
            text=report_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.error(f"Error sending 6PM report to {DIRECTOR_CHAT_ID}: {e}")
