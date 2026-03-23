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

def filter_tasks(tasks, filters):
    if not filters:
        return tasks
        
    filtered = list(tasks)
    from datetime import datetime, timedelta
    
    # Simple naive date for comparison matching JS
    today = datetime.now().date()
    
    status = filters.get("status")
    if status == "completed":
        filtered = [t for t in filtered if t.get("status") == "completed"]
    elif status == "pending":
        filtered = [t for t in filtered if t.get("status") != "completed"]
        
    progress_lt = filters.get("progress_lt")
    if progress_lt is not None:
        filtered = [t for t in filtered if t.get("progress", 0) < progress_lt]
        
    if filters.get("has_blockers"):
        filtered = [t for t in filtered if t.get("is_blocked")]
        
    rge = filters.get("range")
    inc_no_dl = filters.get("include_no_deadline")
    
    if rge:
        def parse_date(date_str):
            if not date_str: return None
            try:
                # expecting something like ISO format or YYYY-MM-DD
                return datetime.fromisoformat(date_str.split('T')[0]).date()
            except:
                try:
                    from dateutil.parser import parse
                    return parse(date_str).date()
                except:
                    return None
                    
        new_filtered = []
        for t in filtered:
            dl_str = t.get("deadline")
            if not dl_str:
                if inc_no_dl: new_filtered.append(t)
                continue
                
            dl_date = parse_date(dl_str)
            if not dl_date:
                continue
                
            if rge == "overdue":
                if dl_date < today and t.get("status") != "completed":
                    new_filtered.append(t)
            elif rge == "today":
                if dl_date == today:
                    new_filtered.append(t)
            elif rge == "tomorrow":
                if dl_date == today + timedelta(days=1):
                    new_filtered.append(t)
            elif rge == "this_week":
                if today <= dl_date <= today + timedelta(days=7):
                    new_filtered.append(t)
            elif rge == "custom_range":
                sd = parse_date(filters.get("start_date"))
                ed = parse_date(filters.get("end_date"))
                if sd and ed and (sd <= dl_date <= ed):
                    new_filtered.append(t)
            else:
                new_filtered.append(t)
        filtered = new_filtered
    elif inc_no_dl:
        filtered = [t for t in filtered if not t.get("deadline")]
        
    return filtered

def build_grouped_tasks_list_py(tasks):
    if not tasks: return "No tasks found."
    
    from collections import defaultdict
    from datetime import datetime
    
    grouped = defaultdict(list)
    for idx, t in enumerate(tasks):
        number = idx + 1
        p_name = t.get('projects', {}).get('name', 'No Project') if t.get('projects') else 'No Project'
        
        updates = t.get('updates', [])
        prog = t.get('progress', 0)
        if 'progress' not in t and updates:
            prog = max([u.get('progress', 0) for u in updates]) if updates else 0
            
        blocker_count = sum(1 for u in updates if str(u.get('blockers', '')).lower() not in ['none', ''])
        br = str(t.get('blocker_reason', '')).lower()
        if br not in ['none', ''] and not any(str(u.get('blockers', '')).lower() == br for u in updates):
            blocker_count += 1
            
        grouped[p_name].append({
            'number': number,
            'name': t.get('name', 'Unknown Task'),
            'deadline': t.get('deadline'),
            'progress': prog,
            'blockerCount': blocker_count
        })
        
    msg = ""
    for p_name, t_list in grouped.items():
        msg += f"**{p_name}**\n"
        for t in t_list:
            dl_str = "No deadline"
            if t['deadline']:
                try:
                    d = datetime.fromisoformat(t['deadline'].replace('Z', '+00:00'))
                    dl_str = d.strftime("%d %b")
                except:
                    # fallback date parser
                    dl_str = t['deadline'][:10]
            msg += f"{t['number']}. {t['name']} – Deadline: {dl_str} | {t['progress']}% done | {t['blockerCount']} blocker(s)\n"
        msg += "\n"
        
    return msg.strip()

async def handle_query_tasks(entities, user_id, context, send_reply_func):
    u_info = get_user_by_telegram_id(user_id)
    filters = entities.get("query_filters") or {}
    
    # Same logic as JS: check if all tasks were requested
    raw_message = str(context.get("messages", [])[-1].get("content", "")).lower() if context.get("messages") else ""
    explicit_assignee = str(filters.get("assignee") or entities.get("assignee", "")).lower()
    is_all = "all tasks" in raw_message or "all task" in raw_message or explicit_assignee == "all"
    
    requester = u_info['name'] if u_info else 'Asif'
    
    # Defaults for Manager Kanav
    if requester == 'Kanav' and not explicit_assignee:
        is_all = True
        
    if requester == 'Kanav' and is_all and explicit_assignee not in ['kanav', 'asif']:
        msg = "**Tasks Assigned to Kanav**\n"
        all_tasks = get_all_tasks()
        k_tasks = [t for t in all_tasks if str(t.get('assigned_to_user', {}).get('name', '')).lower() == 'kanav']
        k_tasks = filter_tasks(k_tasks, filters)
        msg += build_grouped_tasks_list_py(k_tasks) + "\n\n" if k_tasks else "No tasks match criteria\n\n"
        
        msg += "**Tasks Assigned to Asif**\n"
        a_tasks = [t for t in all_tasks if str(t.get('assigned_to_user', {}).get('name', '')).lower() == 'asif' or not t.get('assigned_to_user')]
        a_tasks = filter_tasks(a_tasks, filters)
        msg += build_grouped_tasks_list_py(a_tasks) if a_tasks else "No tasks match criteria"
        
        await send_reply_func(msg)
        return
        
    # Not Kanav "all tasks"
    target_user_id = u_info['id'] if u_info else None
    
    # If explicitly targeting kanav or asif but we are not there, try strictly checking logic
    tasks = get_all_tasks()
    if explicit_assignee == 'kanav':
        tasks = [t for t in tasks if str(t.get('assigned_to_user', {}).get('name', '')).lower() == 'kanav']
    elif explicit_assignee == 'asif' or (requester == 'Asif' and not explicit_assignee):
        tasks = [t for t in tasks if str(t.get('assigned_to_user', {}).get('name', '')).lower() == 'asif' or not t.get('assigned_to_user')]
    elif target_user_id and u_info['role'] != 'director':
        tasks = get_tasks_for_user(target_user_id)

    filtered = filter_tasks(tasks, filters)
    if not filtered:
        await send_reply_func("No tasks found matching criteria.")
        return
        
    msg = f"Here are the tasks currently matching your query:\n\n{build_grouped_tasks_list_py(filtered)}"
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

def generate_pdf_report():
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
        
        p_tasks = [t for t in tasks if t.get('project_id') == p['id']]
        red = sum(1 for t in p_tasks if t.get('is_blocked'))
        green = sum(1 for t in p_tasks if t.get('status') == 'completed')
        amber = len(p_tasks) - red - green
        
        pdf.set_font("Arial", size=12)
        pdf.cell(0, 8, txt=f"Tasks: {len(p_tasks)} | Red: {red} | Amber: {amber} | Green: {green}", ln=1)
        
        for t in p_tasks:
            pdf.ln(5)
            pdf.set_font("Arial", 'B', 12)
            pdf.cell(0, 8, txt=f"Task: {t['name']}", ln=1)
            pdf.set_font("Arial", size=10)
            
            t_status = t.get('status', 'pending')
            progress = t.get('progress', 0)
            deadline = t.get('deadline') or 'None'
            pdf.cell(0, 6, txt=f"Status: {t_status} | Progress: {progress}% | Deadline: {deadline}", ln=1)
            
            t_rag = "amber"
            if t_status == 'completed': t_rag = "green"
            if t.get('is_blocked'): t_rag = "red"
            
            pdf.cell(12, 6, txt="RAG: ")
            if t_rag == "red":
                pdf.set_text_color(220, 0, 0)
                pdf.cell(0, 6, txt="Red", ln=1)
            elif t_rag == "green":
                pdf.set_text_color(0, 180, 0)
                pdf.cell(0, 6, txt="Green", ln=1)
            else:
                pdf.set_text_color(200, 150, 0)
                pdf.cell(0, 6, txt="Amber", ln=1)
            pdf.set_text_color(0, 0, 0) # reset black
            
            blocker = t.get('blocker_reason') if t.get('is_blocked') else "None"
            pdf.cell(0, 6, txt=f"Blocker: {blocker}", ln=1)
            
            atts = t.get('attachments')
            if atts and isinstance(atts, list) and len(atts) > 0:
                img_url = atts[0]
                proof_url = img_url
                if proof_url.startswith('data:image'):
                    import os
                    host = os.getenv("NEXT_PUBLIC_SITE_URL", "http://localhost:3000")
                    proof_url = f"{host}/api/proof?taskId={t['id']}"
                    
                pdf.set_text_color(0, 0, 255)
                pdf.cell(0, 6, txt="View Proof Image", link=proof_url, ln=1)
                pdf.set_text_color(0, 0, 0)
            
    filepath = "/tmp/daily_report.pdf"
    pdf.output(filepath)
    return filepath

async def handle_request_report(entities, user_id, context, send_reply_func):
    filepath = generate_pdf_report()
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

async def handle_greeting(entities, user_id, context, send_reply_func):
    u_info = get_user_by_telegram_id(user_id)
    name = u_info['name'] if u_info else "there"
    role = u_info['role'] if u_info else "normal"
    
    msg = f"Hi {name}, What can I help you with?\n\n🤖 Available Commands:\n"
    if role == 'director':
        msg += "• /get_report\n• /get_task\n• /create_task\n• /create_project\n• /view_tickets\n• /help"
    else:
        msg += "• /update_task\n• /raise_ticket\n• /view_tickets\n• /create_task\n• /create_project\n• /help"
    
    await send_reply_func(msg)

async def handle_clarify(entities, user_id, context, send_reply_func):
    set_state(user_id, {"action": "clarify", "step": "waiting_for_choice"})
    msg = (
        "I'm not sure I understood that correctly. Did you want to:\n"
        "1. Update task progress\n"
        "2. Add a blocker\n"
        "3. Complete a task\n"
        "4. Raise a ticket\n"
        "5. View all tickets\n"
        "6. Show All Blockers Project wise\n"
        "7. Create Project or Task\n"
        "8. Show your tasks\n\n"
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
