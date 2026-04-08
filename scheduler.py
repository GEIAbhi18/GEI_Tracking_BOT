import logging
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from config import EMPLOYEE_CHAT_ID, DIRECTOR_CHAT_ID, TIMEZONE
from db import get_todays_updates, get_upcoming_deadlines, get_all_tasks
from rag import calculate_project_rag, calculate_rag

logger = logging.getLogger(__name__)

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Sending 5PM reminder to employee...")
    try:
        await context.bot.send_message(
            chat_id=EMPLOYEE_CHAT_ID,
            text="Asif, aaj ke tasks ka update bhejo.\nExample:\n'Top Terrace waterproofing 40% done, material delay' + photo"
        )
    except Exception as e:
        logger.error(f"Error sending reminder: {e}")

async def send_deadline_alerts(context: ContextTypes.DEFAULT_TYPE):
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
        logger.error(f"Error sending deadline alerts: {e}")

async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
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
                # Mark as missed, so RED RAG
                rag_color, _ = calculate_rag(0, None, None, "", missed_updates=1)
                projects_data[pname]['tasks'].append({
                    'name': t['name'],
                    'rag': "RED",
                    'progress': 0,
                    'blockers': "Asif did not respond.",
                    'deadline': t['deadline'],
                    'updated': False
                })

        report_text = "📊 *6PM Project Summary*\n\n"
        buttons = []
        
        emoji_map = {"RED": "🔴", "AMBER": "🟡", "GREEN": "🟢"}
        
        for p_name, p_info in projects_data.items():
            task_rags = [t['rag'] for t in p_info['tasks']]
            proj_rag = calculate_project_rag(task_rags)
            
            report_text += f"{p_name} ➔ {emoji_map.get(proj_rag, '-')}\n"
            
            buttons.append([InlineKeyboardButton(f"[{p_name} Details]", callback_data=f"proj_{p_info['id']}")])
        
        await context.bot.send_message(
            chat_id=DIRECTOR_CHAT_ID,
            text=report_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.error(f"Error sending 6PM report: {e}")
