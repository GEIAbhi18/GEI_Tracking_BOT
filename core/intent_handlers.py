import logging
import json
from db import (
    get_all_tasks, save_update, create_ticket, get_user_by_telegram_id, 
    get_projects, complete_task, add_blocker, get_tasks_for_user, get_task_blockers,
    get_open_tickets
)
from core.conversation_state import set_state, clear_state
from core.context_manager import update_context, get_context

logger = logging.getLogger(__name__)

async def handle_task_update(entities, user_id, context, send_reply_func):
    task_name = entities.get("task_name")
    progress = entities.get("progress")
    
    # Try to resolve from context if missing
    if not task_name and context.get("recent_task_name"):
        task_name = context["recent_task_name"]

    if not task_name:
        tasks = get_all_tasks()
        open_tasks = [t for t in tasks if t.get('status') != 'completed']
        tasks_msg = "\n".join([f"- {t['name']} ({t['projects']['name']})" for t in open_tasks])
        set_state(user_id, {"action": "update_task", "step": "waiting_for_task"})
        await send_reply_func(f"Which task do you want to update?\n\n{tasks_msg}")
        return
    
    if not progress:
        set_state(user_id, {"action": "update_task", "step": "waiting_for_progress", "task_query": task_name})
        await send_reply_func(f"What is the progress % for '{task_name}'?")
        return

    await perform_update(task_name, progress, user_id, send_reply_func)

async def handle_complete_task(entities, user_id, context, send_reply_func):
    task_name = entities.get("task_name")
    
    if not task_name and context.get("recent_task_name"):
        task_name = context["recent_task_name"]

    if not task_name:
        set_state(user_id, {"action": "complete_task", "step": "waiting_for_project"})
        projects = get_projects()
        p_list = "\n".join([f"- {p['name']}" for p in projects])
        await send_reply_func(f"Which project is the task in?\n\n{p_list}")
        return

    await perform_update(task_name, "100", user_id, send_reply_func)

async def handle_add_blocker(entities, user_id, context, send_reply_func):
    task_name = entities.get("task_name")
    blocker_text = entities.get("blocker_description") or entities.get("blocker_name")

    if not task_name and context.get("recent_task_name"):
        task_name = context["recent_task_name"]

    if not task_name:
        tasks = get_all_tasks()
        open_tasks = [t for t in tasks if t.get('status') != 'completed']
        tasks_msg = "\n".join([f"- {t['name']} ({t['projects']['name']})" for t in open_tasks])
        set_state(user_id, {"action": "add_blocker", "step": "waiting_for_task"})
        await send_reply_func(f"Which task is blocked?\n\n{tasks_msg}")
        return
    
    if not blocker_text:
        set_state(user_id, {"action": "add_blocker", "step": "waiting_for_description", "task_query": task_name})
        await send_reply_func(f"What is the issue holding up '{task_name}'?")
        return

    await perform_add_blocker(task_name, blocker_text, user_id, send_reply_func)

async def handle_remove_blocker(entities, user_id, context, send_reply_func):
    task_name = entities.get("task_name")
    
    if not task_name and context.get("recent_task_name"):
        task_name = context["recent_task_name"]

    if not task_name:
        tasks = get_all_tasks()
        blocked_tasks = [t for t in tasks if t.get('is_blocked')]
        if not blocked_tasks:
            await send_reply_func("No blocked tasks found.")
            return
        tasks_msg = "\n".join([f"- {t['name']}" for t in blocked_tasks])
        set_state(user_id, {"action": "remove_blocker", "step": "waiting_for_task"})
        await send_reply_func(f"Which task's blocker should I remove?\n\n{tasks_msg}")
        return

    await perform_remove_blocker(task_name, user_id, send_reply_func)

async def handle_query_tasks(entities, user_id, context, send_reply_func):
    u_info = get_user_by_telegram_id(user_id)
    if u_info and u_info['role'] != 'director':
        tasks = get_tasks_for_user(u_info['id'])
    else:
        tasks = get_all_tasks()
        
    if not tasks:
        await send_reply_func("No tasks found.")
        return
        
    msg = "📋 *Task List:*\n"
    for idx, t in enumerate(tasks):
        status_icon = "✅" if t.get('status') == 'completed' else "⏳"
        deadline_str = f" | Deadline: {t.get('deadline')}" if t.get('deadline') else ""
        msg += f"{idx + 1}. {status_icon} *{t['name']}*\n   Progress: {t.get('progress', 0)}%{deadline_str}\n"
    
    await send_reply_func(msg)

async def handle_query_blockers(entities, user_id, context, send_reply_func):
    tasks = get_all_tasks()
    blocked_tasks = [t for t in tasks if t.get('is_blocked')]
    
    if not blocked_tasks:
        await send_reply_func("No blocked tasks found. Everything is on track! 🟢")
        return
        
    from collections import defaultdict
    blocked_by_proj = defaultdict(list)
    for t in blocked_tasks:
        pname = t.get('projects', {}).get('name', 'Unknown Project') if t.get('projects') else "Unknown"
        blocked_by_proj[pname].append(t)
        
    msg = "🛑 *Current Blockers:*\n"
    for proj, blks in blocked_by_proj.items():
        msg += f"\n- *{proj}*\n"
        for t in blks:
            msg += f"   - *{t['name']}*: blocker: {t.get('blocker_reason', 'Unknown reason')}\n"
    
    await send_reply_func(msg)

async def handle_view_tickets(entities, user_id, context, send_reply_func):
    tickets = get_open_tickets()
    if not tickets:
        await send_reply_func("No open tickets found.")
        return
        
    msg = "🎫 *Open Tickets:*\n\n"
    for idx, t in enumerate(tickets):
        p_name = t['projects']['name'] if t.get('projects') else 'Unknown'
        t_name = t['tasks']['name'] if t.get('tasks') else 'Unknown'
        u_name = t['users']['name'] if t.get('users') else 'Unknown'
        issue_text = "No messages"
        if t.get("messages"):
            issue_text = t["messages"][0]
            
        msg += f"{idx + 1}. *Project: {p_name}*\n   Task: {t_name}\n   By: {u_name}\n   Issue: {issue_text}\n\n"
        
    msg += "*To reply, type:* '1. Working on it'\n*To close type* 'close Ticket 1'"
    await send_reply_func(msg)

async def handle_reply_ticket(entities, user_id, context, send_reply_func):
    ticket_index = entities.get("ticket_index")
    reply_msg = entities.get("message")
    from db import get_open_tickets, add_ticket_message
    tickets = get_open_tickets()
    if ticket_index and 1 <= ticket_index <= len(tickets):
        target_ticket = tickets[ticket_index - 1]
        u_info = get_user_by_telegram_id(user_id)
        if u_info:
            add_ticket_message(target_ticket['id'], u_info['id'], reply_msg)
            await send_reply_func(f"✅ Reply added to Ticket {ticket_index}.")
        else:
            await send_reply_func("User error.")
    else:
        await send_reply_func(f"Ticket {ticket_index} not found.")

async def handle_close_ticket(entities, user_id, context, send_reply_func):
    ticket_index = entities.get("ticket_index")
    from db import get_open_tickets, close_ticket
    tickets = get_open_tickets()
    if ticket_index and 1 <= ticket_index <= len(tickets):
        target_ticket = tickets[ticket_index - 1]
        close_ticket(target_ticket['id'])
        await send_reply_func(f"✅ Ticket {ticket_index} closed.")
    else:
        await send_reply_func(f"Ticket {ticket_index} not found.")

async def handle_request_report(entities, user_id, context, send_reply_func):
    from fpdf import FPDF
    from db import get_all_tasks, get_projects
    projects = get_projects()
    tasks = get_all_tasks()
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(0, 10, txt="Daily Project Report", ln=1, align="C")
    
    for p in projects:
        pdf.ln(10)
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, txt=f"Project: {p['name']}", ln=1)
        
        p_tasks = [t for t in tasks if t['project_id'] == p['id']]
        red = sum(1 for t in p_tasks if t.get('is_blocked'))
        green = sum(1 for t in p_tasks if t.get('status') == 'completed')
        amber = len(p_tasks) - red - green
        
        pdf.set_font("Arial", size=12)
        pdf.cell(0, 8, txt=f"Tasks: {len(p_tasks)} | Red: {red} | Amber: {amber} | Green: {green}", ln=1)
        
        for t in p_tasks:
            pdf.ln(5)
            pdf.set_font("Arial", 'B', 12)
            status_txt = f"Task: {t['name']} - Progress: {t.get('progress', 0)}%"
            pdf.cell(0, 8, txt=status_txt, ln=1)
            pdf.set_font("Arial", size=10)
            if t.get('is_blocked'):
                pdf.cell(0, 6, txt=f"Blocker: {t.get('blocker_reason')}", ln=1)
            
    filepath = "/tmp/daily_report.pdf"
    pdf.output(filepath)
    await send_reply_func(text="Here is your detailed daily report.", document=filepath)

async def handle_create_ticket(entities, user_id, context, send_reply_func):
    projects = get_projects()
    if not projects:
        await send_reply_func("No projects exist. Create a project first.")
        return
    msg = "Which project is this for?\n\n"
    for p in projects:
        msg += f"- {p['name']}\n"
    set_state(user_id, {"action": "create_ticket", "step": "waiting_for_project"})
    await send_reply_func(msg)

async def handle_create_project(entities, user_id, context, send_reply_func):
    set_state(user_id, {"action": "create_project", "step": "waiting_for_name"})
    await send_reply_func("What is the name of the new project?")

async def handle_create_task(entities, user_id, context, send_reply_func):
    projects = get_projects()
    if not projects:
        await send_reply_func("No projects exist. Create a project first.")
        return
    msg = "Which project should this task be added to?\n\n"
    for p in projects:
        msg += f"- {p['name']}\n"
    set_state(user_id, {"action": "create_task", "step": "waiting_for_project"})
    await send_reply_func(msg)

async def handle_help(entities, user_id, context, send_reply_func):
    msg = (
        "👋 *GEI Bot Help*\n\n"
        "You can talk to me in natural language:\n"
        "- \"update slope test 50%\"\n"
        "- \"complete task panel installation\"\n"
        "- \"add blocker to slope corrections: rain delay\"\n"
        "- \"show my tasks\"\n"
        "- \"what are the current blockers?\"\n\n"
        "Or use commands:\n"
        "/list_tasks, /view_projects, /raise_ticket"
    )
    await send_reply_func(msg)

async def handle_clarify(entities, user_id, context, send_reply_func):
    set_state(user_id, {"action": "clarify", "step": "waiting_for_choice"})
    msg = (
        "I'm not sure I understood that correctly. Did you want to:\n"
        "1. Update task progress\n"
        "2. Add a blocker\n"
        "3. Complete a task\n"
        "4. Show your tasks\n\n"
        "Please specify your request."
    )
    await send_reply_func(msg)

# --- Helper Performers ---

async def perform_update(task_query, progress_str, user_id, send_reply_func):
    tasks = get_all_tasks()
    match = next((t for t in tasks if task_query.lower() in t['name'].lower()), None)
    
    if not match:
        await send_reply_func(f"Could not find task matching '{task_query}'.")
        return

    try:
        progress = int(str(progress_str).replace('%', ''))
    except:
        progress = 0
        
    u_info = get_user_by_telegram_id(user_id)
    emp_uuid = u_info['id'] if u_info else None
    
    save_update(match['id'], progress, "None", [], emp_uuid)
    
    # Update Context
    update_context(user_id, task_id=match['id'], task_name=match['name'], last_command="update_task")
    
    await send_reply_func(f"Update saved ✅\nTask: {match['name']}\nProgress: {progress}%")

async def perform_add_blocker(task_query, description, user_id, send_reply_func):
    tasks = get_all_tasks()
    match = next((t for t in tasks if task_query.lower() in t['name'].lower()), None)
    
    if not match:
        await send_reply_func(f"Could not find task matching '{task_query}'.")
        return

    add_blocker(match['id'], description)
    
    # Also log an update in history
    u_info = get_user_by_telegram_id(user_id)
    save_update(match['id'], match.get('progress', 0), description, [], u_info['id'] if u_info else None)
    
    # Update Context
    update_context(user_id, task_id=match['id'], task_name=match['name'], last_command="add_blocker")
    
    await send_reply_func(f"Blocker added successfully 🛑\nTask: {match['name']}\nIssue: {description}")

async def perform_remove_blocker(task_query, user_id, send_reply_func):
    from db import remove_blocker
    tasks = get_all_tasks()
    match = next((t for t in tasks if task_query.lower() in t['name'].lower()), None)
    
    if not match:
        await send_reply_func(f"Could not find task matching '{task_query}'.")
        return

    remove_blocker(match['id'])
    
    # Update Context
    update_context(user_id, task_id=match['id'], task_name=match['name'], last_command="remove_blocker")
    
    await send_reply_func(f"Blocker removed from '{match['name']}' 🟢")
