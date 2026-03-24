import logging
import json
import re
from db import (
    get_all_tasks, save_update, create_ticket, get_user_by_telegram_id, 
    get_projects, complete_task, add_blocker, get_tasks_for_user, get_task_blockers,
    get_open_tickets
)
from core.conversation_state import set_state, clear_state
from core.context_manager import update_context, get_context

logger = logging.getLogger(__name__)

async def handle_task_update(entities, user_id, context, send_reply_func, images=None):
    task_name = entities.get("task_name")
    progress = entities.get("progress")
    
    if not task_name and context.get("recent_task_name"):
        task_name = context["recent_task_name"]

    if not task_name:
        set_state(user_id, {"action": "update_task", "step": "waiting_for_project"})
        projects = get_projects()
        p_list = "\n".join([f"{idx+1}. {p['name']}" for idx, p in enumerate(projects)])
        await send_reply_func(f"Which project is the task in? (Type the number)\n\n{p_list}")
        return

    # Check if task_name is actually a project name
    projects = get_projects()
    project_match = next((p for p in projects if p['name'].lower() == task_name.lower()), None)
    if project_match:
        from db import get_all_tasks
        tasks = get_all_tasks()
        p_tasks = [t for t in tasks if t['status'] != 'completed' and t.get('project_id') == project_match['id']]
        if not p_tasks:
            await send_reply_func(f"No pending tasks found for project '{project_match['name']}'.")
            return
        tasks_msg = "\n".join([f"{idx+1}. {t['name']}" for idx, t in enumerate(p_tasks)])
        set_state(user_id, {"action": "update_task", "step": "waiting_for_task", "project_query": project_match['name'], "_task_map": [t['name'] for t in p_tasks]})
        await send_reply_func(f"Which task in '{project_match['name']}' do you want to update? (Type the number)\n\n{tasks_msg}")
        return
    
    deadline = entities.get("deadline")
    
    # If deadline is provided but no progress, we still want to update the deadline
    if not progress and not deadline:
        set_state(user_id, {"action": "update_task", "step": "waiting_for_progress", "task_query": task_name, "deadline": deadline})
        await send_reply_func(f"What is the progress % for '{task_name}'?")
        return

    await perform_update(task_name, progress, user_id, send_reply_func, images=images, deadline=deadline)

async def handle_complete_task(entities, user_id, context, send_reply_func, images=None):
    task_name = entities.get("task_name")
    
    if not task_name and context.get("recent_task_name"):
        task_name = context["recent_task_name"]

    if not task_name:
        set_state(user_id, {"action": "complete_task", "step": "waiting_for_project"})
        projects = get_projects()
        p_list = "\n".join([f"{idx+1}. {p['name']}" for idx, p in enumerate(projects)])
        await send_reply_func(f"Which project is the task in? (Type the number)\n\n{p_list}")
        return

    # Check if task_name is actually a project name
    projects = get_projects()
    project_match = next((p for p in projects if p['name'].lower() == task_name.lower()), None)
    if project_match:
        from db import get_all_tasks
        tasks = get_all_tasks()
        p_tasks = [t for t in tasks if t['status'] != 'completed' and t.get('project_id') == project_match['id']]
        if not p_tasks:
            await send_reply_func(f"No pending tasks found for project '{project_match['name']}'.")
            return
        tasks_msg = "\n".join([f"{idx+1}. {t['name']}" for idx, t in enumerate(p_tasks)])
        set_state(user_id, {"action": "complete_task", "step": "waiting_for_task", "project_query": project_match['name'], "_task_map": [t['name'] for t in p_tasks]})
        await send_reply_func(f"Which task in '{project_match['name']}' should I complete? (Type the number)\n\n{tasks_msg}")
        return

    # Resolve task_name if it's a number from a list
    resolved_name = task_name
    ctx = get_context(user_id)
    last_list = ctx.get('last_task_list', [])
    import re
    m = re.search(r'(\d+)', str(task_name))
    if m and ("task" in str(task_name).lower() or str(task_name).isdigit()):
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(last_list):
            tasks = get_all_tasks()
            match = next((t for t in tasks if t['id'] == last_list[idx]), None)
            if match:
                resolved_name = match['name']

    # Require proof for completion
    if not images:
        set_state(user_id, {"action": "complete_task", "step": "waiting_for_proof", "task_query": resolved_name})
        await send_reply_func(f"Please upload an image proof to mark '{resolved_name}' as complete.")
        return

    await perform_update(resolved_name, "100", user_id, send_reply_func, images=images)

async def handle_add_blocker(entities, user_id, context, send_reply_func, images=None):
    task_name = entities.get("task_name")
    blocker_text = entities.get("blocker_description") or entities.get("blocker_name")

    if not task_name and context.get("recent_task_name"):
        task_name = context["recent_task_name"]

    if not task_name:
        set_state(user_id, {"action": "add_blocker", "step": "waiting_for_project"})
        projects = get_projects()
        p_list = "\n".join([f"{idx+1}. {p['name']}" for idx, p in enumerate(projects)])
        await send_reply_func(f"Which project is the task in? (Type the number)\n\n{p_list}")
        return

    # Check if task_name is actually a project name
    projects = get_projects()
    project_match = next((p for p in projects if p['name'].lower() == task_name.lower()), None)
    if project_match:
        from db import get_all_tasks
        tasks = get_all_tasks()
        p_tasks = [t for t in tasks if t['status'] != 'completed' and t.get('project_id') == project_match['id']]
        if not p_tasks:
            await send_reply_func(f"No pending tasks found for project '{project_match['name']}'.")
            return
        tasks_msg = "\n".join([f"{idx+1}. {t['name']}" for idx, t in enumerate(p_tasks)])
        set_state(user_id, {"action": "add_blocker", "step": "waiting_for_task", "project_query": project_match['name'], "_task_map": [t['name'] for t in p_tasks]})
        await send_reply_func(f"Which task in '{project_match['name']}' is blocked? (Type the number)\n\n{tasks_msg}")
        return
    
    # Resolve task_name if it's a number from a list
    resolved_name = task_name
    ctx = get_context(user_id)
    last_list = ctx.get('last_task_list', [])
    import re
    m = re.search(r'(\d+)', str(task_name))
    if m and ("task" in str(task_name).lower() or str(task_name).isdigit()):
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(last_list):
            tasks = get_all_tasks()
            match = next((t for t in tasks if t['id'] == last_list[idx]), None)
            if match:
                resolved_name = match['name']

    if not blocker_text:
        set_state(user_id, {"action": "add_blocker", "step": "waiting_for_description", "task_query": resolved_name})
        await send_reply_func(f"What is the issue holding up '{resolved_name}'?")
        return

    await perform_add_blocker(resolved_name, blocker_text, user_id, send_reply_func, images=images)

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
        try:
            number = idx + 1
            # Safer project name lookup
            p_obj = t.get('projects')
            if isinstance(p_obj, list) and p_obj:
                p_name = p_obj[0].get('name', 'No Project')
            elif isinstance(p_obj, dict):
                p_name = p_obj.get('name', 'No Project')
            else:
                p_name = 'No Project'
            
            updates = t.get('updates') or []
            prog = t.get('progress', 0)
            if prog is None: prog = 0
            
            if ('progress' not in t or t.get('progress') is None) and updates:
                valid_progs = [u.get('progress') for u in updates if u.get('progress') is not None]
                if valid_progs:
                    prog = max(valid_progs)
                
            blocker_count = 0
            for u in updates:
                b_val = str(u.get('blockers') or '').lower()
                if b_val and b_val not in ['none', 'null', 'undefined']:
                    blocker_count += 1
                    
            br = str(t.get('blocker_reason') or '').lower()
            if br and br not in ['none', 'null'] and not any(str(u.get('blockers') or '').lower() == br for u in updates):
                blocker_count += 1
                
            grouped[p_name].append({
            'number': number,
            'name': t.get('name', 'Unknown Task'),
            'deadline': t.get('deadline'),
            'progress': prog,
            'blockerCount': blocker_count
            })
        except Exception as e:
            logger.error(f"Error processing task {t.get('id', 'unknown')}: {e}")
            continue
        
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
            try:
                # Cast to int to ensure we handle strings/floats correctly
                is_done = int(float(prog)) >= 100
            except:
                is_done = False
                
            tick = " ✅" if is_done else ""
            msg += f"{t['number']}. {t['name']} – Deadline: {dl_str} | {t['progress']}% done{tick} | {t['blockerCount']} blocker(s)\n"
        msg += "\n"
        
    return msg.strip()

async def handle_query_tasks(entities, user_id, context, send_reply_func):
    u_info = get_user_by_telegram_id(user_id)
    filters = entities.get("query_filters") or {}
    
    # Same logic as JS: check if all tasks were requested
    raw_message = str(context.get("messages", [])[-1]).lower() if context.get("messages") else ""
    explicit_assignee = str(filters.get("assignee") or entities.get("assignee", "")).lower()
    is_all = any(x in raw_message for x in ["all tasks", "all task", "view all", "list all", "show all"]) or explicit_assignee == "all"
    
    requester = u_info['name'] if u_info else 'Asif'
    
    # Defaults for Manager Kanav
    if requester == 'Kanav' and not explicit_assignee:
        is_all = True
        
    if requester == 'Kanav' and is_all and explicit_assignee not in ['kanav', 'asif']:
        msg = "**Tasks Assigned to Kanav**\n"
        all_tasks = get_all_tasks()
        k_tasks = [t for t in all_tasks if t.get('assigned_to_user') and str(t['assigned_to_user'].get('name', '')).lower() == 'kanav']
        k_tasks = filter_tasks(k_tasks, filters)
        msg += build_grouped_tasks_list_py(k_tasks) + "\n\n" if k_tasks else "No tasks match criteria\n\n"
        
        msg += "**Tasks Assigned to Asif**\n"
        a_tasks = [t for t in all_tasks if (t.get('assigned_to_user') and str(t['assigned_to_user'].get('name', '')).lower() == 'asif') or not t.get('assigned_to_user')]
        a_tasks = filter_tasks(a_tasks, filters)
        msg += build_grouped_tasks_list_py(a_tasks) if a_tasks else "No tasks match criteria"
        
        await send_reply_func(msg)
        return
        
    # Not Kanav "all tasks"
    target_user_id = u_info['id'] if u_info else None
    
    # If explicitly targeting kanav or asif but we are not there, try strictly checking logic
    tasks = get_all_tasks()
    if explicit_assignee == 'kanav':
        tasks = [t for t in tasks if t.get('assigned_to_user') and str(t['assigned_to_user'].get('name', '')).lower() == 'kanav']
    elif explicit_assignee == 'asif':
        tasks = [t for t in tasks if (t.get('assigned_to_user') and str(t['assigned_to_user'].get('name', '')).lower() == 'asif') or not t.get('assigned_to_user')]
    elif (requester == 'Asif' and not explicit_assignee and not is_all):
        # Only restrict to self if they specifically said 'my tasks' or didn't use 'view all'
        # Actually standard 'show tasks' for Asif we will now show everything if they want a common view
        # But for strictly personal lists we use this:
        if "my tasks" in raw_message:
            tasks = [t for t in tasks if t.get('assigned_to_user') and str(t['assigned_to_user'].get('name', '')).lower() == 'asif']
        else:
            # Default to showing everything since the user asked if 'anyone' sees all
            pass 
    elif target_user_id and u_info and u_info['role'] != 'director' and not is_all:
        tasks = get_tasks_for_user(target_user_id)

    filtered = filter_tasks(tasks, filters)
    if not filtered:
        await send_reply_func("No tasks found matching criteria.")
        return
        
    msg = f"Here are the tasks currently matching your query:\n\n{build_grouped_tasks_list_py(filtered)}"
    update_context(user_id, last_task_list=[t['id'] for t in filtered])
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
        try:
            p_obj = t.get('projects')
            if isinstance(p_obj, list) and p_obj:
                pname = p_obj[0].get('name', 'Unknown')
            elif isinstance(p_obj, dict):
                pname = p_obj.get('name', 'Unknown')
            else:
                pname = "Unknown"
        except:
            pname = "Unknown"
        blocked_by_proj[pname].append(t)
        
    msg = "🛑 *Current Blockers:*\n"
    for proj, blks in blocked_by_proj.items():
        msg += f"\n- *{proj}*\n"
        for idx, t in enumerate(blks, 1):
            msg += f"   {idx}. *{t['name']}*: blocker: {t.get('blocker_reason', 'Unknown reason')}\n"
    
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
        issue_text = "\n     ".join(t["messages"]) if t.get("messages") else "No messages"
            
        msg += f"{idx + 1}. *Project: {p_name}*\n   Task: {t_name}\n   By: {u_name}\n   Issue: {issue_text}\n\n"
        
    msg += "*To reply, type:* 'Ticket 1. Working on it'\n*To close type* 'close Ticket 1'"
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
            await send_reply_func(f"Employee/User with Telegram ID {user_id} not found in database. Please contact admin to register your device.")
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

async def handle_ask_asif(entities, user_id, context, send_reply_func):
    from db import supabase, get_all_tasks
    
    try:
        # Check if caller is authorized (Kanav)
        u_info = get_user_by_telegram_id(user_id)
        if not u_info or u_info.get('role') != 'director':
            # Optionally check by name if testing from a different ID but wanting to test Asif feature
            if u_info and u_info['name'] != "Abhijeet": # allow Dev to test if they want
                pass
        
        # Find Asif's data
        asif_data = supabase.table("users").select("telegram_id, id").eq("name", "Asif").execute().data
        if not asif_data or not asif_data[0].get('telegram_id'):
            await send_reply_func("Could not find Asif in database or Asif has no telegram_id.")
            return
            
        asif_tid = asif_data[0]['telegram_id']
        asif_uuid = asif_data[0]['id']
        
        tasks = get_all_tasks()
        asif_tasks = [t for t in tasks if (t.get('assigned_to') == asif_uuid or t.get('assigned_to_user', {}).get('name') == "Asif") and t['status'] != 'completed']
        
        if not asif_tasks:
            await send_reply_func("Asif has no pending tasks currently.")
            return

        task_list_str = build_grouped_tasks_list_py(asif_tasks)
        
        # Cross-user message
        notification = f"🔔 *Kanav is asking for your current update.*\n\n{task_list_str}\n\n/update_task"
        await send_reply_func(notification, target_user_id=asif_tid)
        
        # Confirm to Kanav
        await send_reply_func("Sent a reminder to Asif for updates. ✅")
    except Exception as e:
        logger.error(f"Error in handle_ask_asif: {e}")
        await send_reply_func(f"Error processing your request: {e}")

async def handle_request_report(entities, user_id, context, send_reply_func):
    filepath = generate_pdf_report()
    await send_reply_func(text="Here is your detailed daily report.", document=filepath)

async def handle_create_ticket(entities, user_id, context, send_reply_func):
    projects = get_projects()
    if not projects:
        await send_reply_func("No projects exist. Create a project first.")
        return
    msg = "Which project is this for? (You can type the number)\n\n"
    for i, p in enumerate(projects, 1):
        msg += f"{i}. {p['name']}\n"
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
    msg = "Which project should this task be added to? (You can type the number)\n\n"
    for i, p in enumerate(projects, 1):
        msg += f"{i}. {p['name']}\n"
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

async def handle_view_projects(entities, user_id, context, send_reply_func):
    projects = get_projects()
    if not projects:
        await send_reply_func("No projects exist yet.")
        return
    msg = "**All Projects**\n\n"
    for i, p in enumerate(projects, 1):
        msg += f"{i}. {p['name']}\n"
    await send_reply_func(msg)

async def handle_greeting(entities, user_id, context, send_reply_func):
    u_info = get_user_by_telegram_id(user_id)
    name = u_info['name'] if u_info else "there"
    role = u_info['role'] if u_info else "normal"
    
    msg = f"Hi {name}, What can I help you with?\n\n🤖 Available Commands:\n"
    if role == 'director':
        msg += "• /get_report\n• /get_task\n• /create_task\n• /create_project\n• /view_tickets\n• /ask_asif\n• /help"
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

async def perform_update(task_query, progress_str, user_id, send_reply_func, images=None, deadline=None):
    from core.context_manager import get_context
    ctx = get_context(user_id)
    last_list = ctx.get('last_task_list', [])
    
    tasks = get_all_tasks()
    match = None
    
    # Try index matching if it looks like a number
    import re
    m = re.search(r'(\d+)', str(task_query))
    if m and ("task" in str(task_query).lower() or str(task_query).isdigit()):
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(last_list):
            match = next((t for t in tasks if t['id'] == last_list[idx]), None)

    if not match:
        # Resolve by name (stripping 'task ' prefix)
        sq = str(task_query).lower()
        if sq.startswith("task "): sq = sq[5:].strip()
        match = next((t for t in tasks if sq in t['name'].lower()), None)
    
    if not match:
        await send_reply_func(f"Could not find task matching '{task_query}'.")
        return

    try:
        # Handle cases where progress is not provided (e.g. deadline-only update)
        if progress_str is not None:
            progress = int(str(progress_str).replace('%', ''))
        else:
            progress = match.get('progress', 0)
            if progress is None: progress = 0
    except:
        progress = match.get('progress', 0) or 0
        
    u_info = get_user_by_telegram_id(user_id)
    emp_uuid = u_info['id'] if u_info else None
    
    save_update(match['id'], progress, "None", images or [], emp_uuid, new_deadline=deadline)
    
    # Update Context
    update_context(user_id, task_id=match['id'], task_name=match['name'], last_command="update_task")
    
    dl_msg = f"\nDeadline: {deadline}" if deadline else ""
    proof_msg = f"Proof: [Image]" if images else ""
    await send_reply_func(f"Update saved ✅\nTask: {match['name']}\nProgress: {progress}%{dl_msg}\n{proof_msg}")

async def perform_add_blocker(task_query, description, user_id, send_reply_func, images=None):
    from core.context_manager import get_context
    ctx = get_context(user_id)
    last_list = ctx.get('last_task_list', [])
    
    tasks = get_all_tasks()
    match = None
    
    import re
    m = re.search(r'(\d+)', str(task_query))
    if m and ("task" in str(task_query).lower() or str(task_query).isdigit()):
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(last_list):
            match = next((t for t in tasks if t['id'] == last_list[idx]), None)

    if not match:
        sq = str(task_query).lower()
        if sq.startswith("task "): sq = sq[5:].strip()
        match = next((t for t in tasks if sq in t['name'].lower()), None)
    
    if not match:
        await send_reply_func(f"Could not find task matching '{task_query}'.")
        return

    add_blocker(match['id'], description)
    
    # Also log an update in history
    u_info = get_user_by_telegram_id(user_id)
    save_update(match['id'], match.get('progress', 0), description, images or [], u_info['id'] if u_info else None)
    
    # Update Context
    update_context(user_id, task_id=match['id'], task_name=match['name'], last_command="add_blocker")
    
    await send_reply_func(f"Blocker added successfully 🛑\nTask: {match['name']}\nIssue: {description}")

async def perform_remove_blocker(task_query, user_id, send_reply_func):
    from db import remove_blocker, get_all_tasks
    
    ctx = get_context(user_id)
    last_list = ctx.get('last_task_list', [])
    
    tasks = get_all_tasks()
    match = None
    
    # Numeric index matching
    import re
    m = re.search(r'(\d+)', str(task_query))
    if m and ("task" in str(task_query).lower() or str(task_query).isdigit()):
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(last_list):
            match = next((t for t in tasks if t['id'] == last_list[idx]), None)
            
    if not match:
        sq = str(task_query).lower()
        if sq.startswith("task "): sq = sq[5:].strip()
        match = next((t for t in tasks if sq in t['name'].lower()), None)
        
    if not match:
        await send_reply_func(f"Could not find task matching '{task_query}'.")
        return

    # Check for multiple active blockers in update history
    updates = match.get('updates') or []
    active_blockers = []
    for u in updates:
        b_val = str(u.get('blockers') or '').lower()
        if b_val and b_val not in ['none', 'null', 'undefined']:
            active_blockers.append(u.get('blockers'))
            
    # Also check the core task blocker
    br = str(match.get('blocker_reason') or '').lower()
    if br and br not in ['none', 'null'] and br not in [str(b).lower() for b in active_blockers]:
        active_blockers.append(match['blocker_reason'])

    if len(active_blockers) > 1:
        # Prompt for choice
        bl_text = "\n".join([f"{i}. {b}" for i, b in enumerate(active_blockers, 1)])
        set_state(user_id, {
            "action": "remove_blocker", 
            "step": "waiting_for_resolve_choice", 
            "task_id": match['id'], 
            "task_name": match['name'],
            "blockers": active_blockers
        })
        await send_reply_func(f"Task '{match['name']}' has multiple blockers:\n\n{bl_text}\n\nAre ALL blockers resolved? (Type 'All' or the number of the resolved blocker)")
        return

    remove_blocker(match['id'])
    
    # Update Context
    update_context(user_id, task_id=match['id'], task_name=match['name'], last_command="remove_blocker")
    from core.conversation_state import clear_state
    clear_state(user_id)
    await send_reply_func(f"Blocker removed from '{match['name']}' 🟢")
