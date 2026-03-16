import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, MessageHandler, filters

from core.update_engine import process_update_message
from core.llm_parser import parse_with_llm
from db import get_projects, get_tasks_for_project, get_user_by_telegram_id, create_ticket, get_open_tickets, add_ticket_message
from config import EMPLOYEE_CHAT_ID

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    if user_id == EMPLOYEE_CHAT_ID:
        await update.message.reply_text(
            "Hello Asif! 👋\nDin kaisa ja raha hai? \nUpdate format: 'Project Task 50% done, blocker'"
        )
    else:
        await update.message.reply_text("Welcome Kanav. You will receive automated 6 PM reports here.")

async def handle_employee_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    if user_id != EMPLOYEE_CHAT_ID:
        return

    text = update.message.caption or update.message.text
    if not text:
        return
        
    images = []
    if update.message.photo:
        photo_file = await update.message.photo[-1].get_file()
        images.append(photo_file.file_path)
        
    async def send_reply(msg):
        await update.message.reply_text(msg)
        
    await process_update_message(text, user_id, images, send_reply)

async def test_parse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Usage: /test_parse <message>")
        return
        
    parsed = parse_with_llm(text)
    import json
    await update.message.reply_text(json.dumps(parsed, indent=2))

async def test_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from scheduler import send_reminder
    await send_reminder(context.application)

async def test_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "Top Terrace waterproofing 40% done, material delay"
    await update.message.reply_text(f"Send this message exactly: {text}")

async def test_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from scheduler import send_daily_report
    await send_daily_report(context.application)

async def view_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickets = get_open_tickets()
    if not tickets:
        await update.message.reply_text("No open tickets.")
        return
        
    for t in tickets:
        pname = t.get('projects', {}).get('name', 'N/A')
        tname = t.get('tasks', {}).get('name', 'General') if t.get('tasks') else 'General'
        owner = t.get('users', {}).get('name', 'Unknown')
        await update.message.reply_text(f"🎫 ID: {t['id']}\nProject: {pname}\nTask: {tname}\nCreated By: {owner}")

async def raise_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    u_info = get_user_by_telegram_id(user_id)
    if not u_info:
        await update.message.reply_text("User unknown in DB.")
        return
        
    args = context.args
    if len(args) == 0:
        await update.message.reply_text("Usage: /raise_ticket <ProjectName> <Message>")
        return
        
    proj_name = args[0]
    projects = get_projects()
    pid = next((p['id'] for p in projects if p['name'].lower() == proj_name.lower()), None)
    
    if not pid:
        await update.message.reply_text("Project not found.")
        return
        
    msg = " ".join(args[1:])
    create_ticket(u_info['id'], pid, message=msg)
    await update.message.reply_text("✅ Ticket raised.")

async def reply_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /reply_ticket <Ticket_UUID> <Message>")
        return
        
    user_id = update.message.chat_id
    u_info = get_user_by_telegram_id(user_id)
    
    tid = args[0]
    msg = " ".join(args[1:])
    add_ticket_message(tid, u_info['id'], msg)
    await update.message.reply_text("✅ Reply sent.")

async def trigger_drilldown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data.startswith("proj_"):
        project_id = data.replace("proj_", "")
        from db import get_todays_updates
        updates = get_todays_updates()
        
        from db import get_tasks_for_project
        tasks = get_tasks_for_project(project_id)
        
        green_cnt = amber_cnt = red_cnt = missed_cnt = 0
        text = "📋 *Project Drilldown*\n\n"
        
        for t in tasks:
            task_updated = False
            task_u = None
            for u in updates:
                if u['task_id'] == t['id']:
                    task_updated = True
                    task_u = u
                    break
                    
            if task_updated:
                rag = task_u['rag']
                text += f"🔹 *Task:* {t['name']}\n"
                text += f"   ⏳ *Deadline:* {t['deadline']}\n"
                text += f"   ✅ *Progress:* {task_u['progress']}%\n"
                text += f"   🛑 *Blocker:* {task_u['blockers']}\n"
                text += f"   🚦 *RAG:* {rag}\n"
                
                if rag == 'GREEN': green_cnt += 1
                elif rag == 'AMBER': amber_cnt += 1
                else: red_cnt += 1
            else:
                text += f"🔹 *Task:* {t['name']}\n"
                text += f"   🛑 *Status:* Asif did not respond.\n"
                text += f"   🚦 *RAG:* RED\n"
                missed_cnt += 1
                red_cnt += 1
            text += "\n"
            
        text += f"📈 *Summary:*\n"
        text += f"🟢 Green: {green_cnt} | 🟡 Amber: {amber_cnt} | 🔴 Red: {red_cnt}\n"
        text += f"🚨 Missed Updates: {missed_cnt}"
        
        await query.message.reply_text(text, parse_mode="Markdown")
