import logging
import json
import re
from db import (
    get_all_tasks, save_update, create_ticket, get_user_by_telegram_id, 
    get_projects, complete_task, add_blocker, get_tasks_for_user, get_task_blockers,
    get_open_tickets, get_user_by_name, remove_blocker
)
from core.conversation_state import set_state, clear_state
from core.context_manager import update_context, get_context
from core.utils import parse_human_date, resolve_project, resolve_task_from_list

logger = logging.getLogger(__name__)

async def handle_task_update(entities, user_id, context, send_reply_func, images=None):
    task_name = entities.get("task_name")
    progress = entities.get("progress")
    
    if not task_name and context.get("recent_task_name"):
        task_name = context["recent_task_name"]

    
    # Context Management: Prompt user to select project first if active_project_id is missing and task_name is a pure number
    import re
    is_numeric_task = task_name and re.match(r'^(task\s*)?\d+$', str(task_name).lower().strip())
    ctx = get_context(user_id)
    active_project_id = ctx.get("active_project_id")
    
    if is_numeric_task and not active_project_id:
        set_state(user_id, {"action": "update_task", "step": "waiting_for_project", "task_query_pending": task_name, "progress": progress, "deadline": entities.get("deadline")})
        projects = get_projects()
        p_list = "\n".join([f"{idx+1}. {p['name']}" for idx, p in enumerate(projects)])
        await send_reply_func(f"Context missing: Which project is this task in? (Type the number)\n\n{p_list}")
        return

    if not task_name:
        set_state(user_id, {"action": "update_task", "step": "waiting_for_project"})
        projects = get_projects()
        p_list = "\n".join([f"{idx+1}. {p['name']}" for idx, p in enumerate(projects)])
        await send_reply_func(f"Which project is the task in? (Type the number)\n\n{p_list}")
        return

    # Check if task_name is actually a project name
    projects = get_projects()
    project_match = resolve_project(task_name, projects)
    if project_match:
        tasks = get_all_tasks()
        p_tasks = [t for t in tasks if t['status'] != 'completed' and t.get('project_id') == project_match['id']]
        if not p_tasks:
            await send_reply_func(f"No pending tasks found for project '{project_match['name']}'.")
            return
        tasks_msg = "\n".join([f"{idx+1}. {t['name']}" for idx, t in enumerate(p_tasks)])
        set_state(user_id, {"action": "update_task", "step": "waiting_for_task", "project_query": project_match['name'], "_task_map": [t['name'] for t in p_tasks]})
        await send_reply_func(f"Which task in '{project_match['name']}' do you want to update? (Type the number)\n\n{tasks_msg}")
        return
    
    deadline_raw = entities.get("deadline")
    deadline = parse_human_date(deadline_raw) if deadline_raw else None
    
    # If deadline is provided but no progress, we still want to update the deadline
    if progress is None and not deadline:
        set_state(user_id, {"action": "update_task", "step": "waiting_for_progress", "task_query": task_name, "deadline": deadline})
        await send_reply_func(f"What is the progress % for '{task_name}'?")
        return

    # Check for 100% completion - Require proof
    try:
        if progress is not None and int(str(progress).replace('%','')) >= 100 and not images:
            # Resolve task_name if it's a number from a list
            ctx = get_context(user_id)
            last_list = ctx.get('last_task_list', [])
            active_project_id = ctx.get('active_project_id')
            tasks = get_all_tasks()
            match = resolve_task_from_list(task_name, tasks, last_list_ids=last_list, active_project_id=active_project_id)
            resolved_name = match['name'] if match else task_name
            
            set_state(user_id, {"action": "update_task", "step": "waiting_for_proof", "task_query": resolved_name, "progress": "100", "deadline": deadline})
            await send_reply_func(f"Please upload an image proof to mark '{resolved_name}' as 100% complete.")
            return
    except:
        pass

    await perform_update(task_name, progress, user_id, send_reply_func, images=images, deadline=deadline)

async def handle_complete_task(entities, user_id, context, send_reply_func, images=None):
    task_name = entities.get("task_name")
    
    if not task_name and context.get("recent_task_name"):
        task_name = context["recent_task_name"]

    # Context Management check
    import re
    is_numeric_task = task_name and re.match(r'^(task\s*)?\d+$', str(task_name).lower().strip())
    ctx = get_context(user_id)
    active_project_id = ctx.get("active_project_id")
    
    if is_numeric_task and not active_project_id:
        set_state(user_id, {"action": "complete_task", "step": "waiting_for_project", "task_query_pending": task_name})
        projects = get_projects()
        p_list = "\n".join([f"{idx+1}. {p['name']}" for idx, p in enumerate(projects)])
        await send_reply_func(f"Context missing: Which project is this task in? (Type the number)\n\n{p_list}")
        return

    if not task_name:
        set_state(user_id, {"action": "complete_task", "step": "waiting_for_project"})
        projects = get_projects()
        p_list = "\n".join([f"{idx+1}. {p['name']}" for idx, p in enumerate(projects)])
        await send_reply_func(f"Which project is the task in? (Type the number)\n\n{p_list}")
        return

    # Check if task_name is actually a project name
    projects = get_projects()
    project_match = resolve_project(task_name, projects)
    if project_match:
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
    ctx = get_context(user_id)
    last_list = ctx.get('last_task_list', [])
    active_project_id = ctx.get('active_project_id')
    tasks = get_all_tasks()
    match = resolve_task_from_list(task_name, tasks, last_list_ids=last_list, active_project_id=active_project_id)
    resolved_name = match['name'] if match else task_name

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

    # Context Management check
    import re
    is_numeric_task = task_name and re.match(r'^(task\s*)?\d+$', str(task_name).lower().strip())
    ctx = get_context(user_id)
    active_project_id = ctx.get("active_project_id")
    
    if is_numeric_task and not active_project_id:
        set_state(user_id, {"action": "add_blocker", "step": "waiting_for_project", "task_query_pending": task_name, "blocker_description": blocker_text})
        projects = get_projects()
        p_list = "\n".join([f"{idx+1}. {p['name']}" for idx, p in enumerate(projects)])
        await send_reply_func(f"Context missing: Which project is this task in? (Type the number)\n\n{p_list}")
        return

    if not task_name:
        set_state(user_id, {"action": "add_blocker", "step": "waiting_for_project"})
        projects = get_projects()
        p_list = "\n".join([f"{idx+1}. {p['name']}" for idx, p in enumerate(projects)])
        await send_reply_func(f"Which project is the task in? (Type the number)\n\n{p_list}")
        return

    # Check if task_name is actually a project name
    projects = get_projects()
    project_match = resolve_project(task_name, projects)
    if project_match:
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
    ctx = get_context(user_id)
    last_list = ctx.get('last_task_list', [])
    active_project_id = ctx.get('active_project_id')
    tasks = get_all_tasks()
    match = resolve_task_from_list(task_name, tasks, last_list_ids=last_list, active_project_id=active_project_id)
    resolved_name = match['name'] if match else task_name

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
    import pytz
    from config import TIMEZONE
    tz = pytz.timezone(TIMEZONE)
    today = datetime.now(tz).date()
    
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
        def parse_date_internal(date_str):
            if not date_str: return None
            # If it's already an ISO string with T, extract the date part
            if "T" in date_str:
                date_str = date_str.split("T")[0]
            elif " " in date_str and len(date_str) > 10:
                date_str = date_str.split(" ")[0]
                
            parsed = parse_human_date(date_str)
            if parsed:
                try:
                    # Try YYYY-MM-DD
                    return datetime.strptime(parsed, "%Y-%m-%d").date()
                except:
                    try:
                        # Try ISO-like if needed
                        return datetime.fromisoformat(parsed.replace('Z', '+00:00')).date()
                    except:
                        return None
            return None
                    
        new_filtered = []
        for t in filtered:
            dl_str = t.get("deadline")
            if not dl_str:
                if inc_no_dl: new_filtered.append(t)
                continue
                
            dl_date = parse_date_internal(dl_str)
            if not dl_date:
                # If we can't parse it, skip for range filters
                continue
                
            if rge == "overdue":
                # Overdue means deadline passed AND it's not completed
                # Use today (local)
                if dl_date < today and str(t.get("status")).lower() != "completed":
                    new_filtered.append(t)
            elif rge == "today":
                if dl_date == today:
                    new_filtered.append(t)
            elif rge == "tomorrow":
                if dl_date == today + timedelta(days=1):
                    new_filtered.append(t)
            elif rge == "this_week":
                # Next 7 days
                if today <= dl_date <= (today + timedelta(days=7)):
                    new_filtered.append(t)
            elif rge == "custom_range":
                sd_str = filters.get("start_date")
                ed_str = filters.get("end_date")
                sd = parse_date_internal(sd_str)
                ed = parse_date_internal(ed_str)
                if sd and ed:
                    if sd <= dl_date <= ed:
                        new_filtered.append(t)
                elif sd: # Only start date
                    if dl_date >= sd:
                        new_filtered.append(t)
                elif ed: # Only end date
                    if dl_date <= ed:
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
            number = t.get('project_task_number', idx + 1)
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
            'created_at': t.get('created_at'),
            'progress': prog,
            'blockerCount': blocker_count
            })
        except Exception as e:
            logger.error(f"Error processing task {t.get('id', 'unknown')}: {e}")
            continue
        
    msg = ""
    # Sort projects by name for stable numbering
    sorted_p_names = sorted(grouped.keys())
    for proj_idx, p_name in enumerate(sorted_p_names, 1):
        t_list = grouped[p_name]
        msg += f"**{proj_idx}. {p_name}**\n"
        # Sort tasks by their number before displaying
        t_list = sorted(t_list, key=lambda x: float(x['number']) if str(x['number']).replace('.','').isdigit() else 999)
        for t in t_list:
            from core.utils import format_date_human
            start_str = format_date_human(t.get('created_at')).replace("No deadline", "Unknown")
            dl_str = format_date_human(t.get('deadline'))
            
            try:
                # Cast to int to ensure we handle strings/floats correctly
                current_prog = t.get('progress', 0)
                if current_prog is None: current_prog = 0
                is_done = int(float(current_prog)) >= 100
            except:
                is_done = False
                
            tick = " ✅" if is_done else ""
            msg += f"{t['number']}. {t['name']} – Start: {start_str} | Deadline: {dl_str} | {t['progress']}% done{tick} | {t['blockerCount']} blocker(s)\n"
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
        
        # Store context for index matching
        update_context(user_id, last_task_list=[t['id'] for t in k_tasks] + [t['id'] for t in a_tasks], active_project_id=None)
        
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
    update_context(user_id, last_task_list=[t['id'] for t in filtered], active_project_id=None)
    await send_reply_func(msg)

async def handle_get_task_detail(entities, user_id, context, send_reply_func):
    task_reference = entities.get("task_reference") or entities.get("task_name")
    
    if not task_reference:
        await send_reply_func("Which task do you want to see details for? (e.g., 'task 1')")
        return
        
    import re
    is_numeric_task = task_reference and re.match(r'^(task\s*)?\d+$', str(task_reference).lower().strip())
    ctx = get_context(user_id)
    active_project_id = ctx.get("active_project_id")
    
    if is_numeric_task and not active_project_id:
        # Ask for project context to show info
        set_state(user_id, {"action": "get_task_detail", "step": "waiting_for_project", "task_query_pending": task_reference})
        from db import get_projects
        projects = get_projects()
        p_list = "\n".join([f"{idx+1}. {p['name']}" for idx, p in enumerate(projects)])
        await send_reply_func(f"Context missing: Which project is this task in? (Type the number)\n\n{p_list}")
        return
        
    # Resolve task using context

    last_list = context.get('last_task_list', [])
    all_tasks = get_all_tasks()
    match = resolve_task_from_list(task_reference, all_tasks, last_list_ids=last_list, active_project_id=active_project_id)
    
    if not match:
        if active_project_id:
            await send_reply_func(f"Could not find '{task_reference}' in the active project.")
        elif not last_list:
            await send_reply_func("I don't have a recent task list for you. Please first request the task list (e.g., 'show tasks').")
        else:
            await send_reply_func(f"Could not find task matching '{task_reference}'. Please select a valid number from the list.")
        return

    # Fetch full details
    from db import supabase
    t_id = match['id']
    
    # Latest Update (Progress, Blocker, Note)
    update_res = supabase.table("updates").select("*").eq("task_id", t_id).order("timestamp", desc=True).limit(1).execute()
    latest_update = update_res.data[0] if update_res.data else {}
    
    # Project Detail
    p_name = match.get('projects', {}).get('name', 'Unknown Project')
    
    # Deadline
    dl = match.get('deadline') or 'No deadline'
    if dl and 'T' in str(dl):
        from datetime import datetime
        try:
            d = datetime.fromisoformat(dl.replace('Z', '+00:00'))
            dl = d.strftime("%d %b %Y")
        except:
            dl = str(dl)[:10]

    # Format Message (Step 5)
    msg = f"📋 **Task Details:**\n\n"
    msg += f"**Project:** {p_name}\n"
    msg += f"**Task:** {match['name']}\n"
    msg += f"**Deadline:** {dl}\n\n"
    
    prog = latest_update.get('progress', match.get('progress', 0))
    msg += f"**Progress:** {prog}%\n\n"
    
    blocker = latest_update.get('blockers') or match.get('blocker_reason') or "None"
    msg += f"**Blocker:**\n{blocker}\n\n"
    
    note = latest_update.get('note') or "None"
    msg += f"**Note:**\n{note}"
    
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
            from core.utils import format_date_human
            deadline = format_date_human(t.get('deadline'))
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
            
            # Fetch the latest confirmed note if any
            latest_note = "None"
            blocker = t.get('blocker_reason') or "None"
            
            from db import supabase
            update_res = supabase.table("updates").select("note, blockers").eq("task_id", t['id']).neq("note", None).order("timestamp", desc=True).limit(1).execute()
            if update_res.data:
                latest_note = update_res.data[0].get('note') or "None"
                blocker = update_res.data[0].get('blockers') or blocker
            
            pdf.cell(0, 6, txt=f"Blocker: {blocker}", ln=1)
            pdf.cell(0, 6, txt=f"Note: {latest_note}", ln=1)
            
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

async def handle_trigger_reminder_user(entities, user_id, context, send_reply_func):
    target_name = entities.get("target_user") or "Asif"
    
    try:
        # 1. Resolve user
        user = get_user_by_name(target_name)
        if not user or not user.get('telegram_id'):
            await send_reply_func(f"User '{target_name}' not found or has no telegram_id.")
            return
            
        target_tid = user['telegram_id']
        target_uuid = user['id']
        
        # 2. Fetch tasks
        tasks = get_tasks_for_user(target_uuid)
        active_tasks = [t for t in tasks if t['status'] != 'completed']
        
        if not active_tasks:
            await send_reply_func(f"'{target_name}' has no ongoing tasks.")
            return

        # 3. Format message
        msg = f"Hi {user['name']} 👋\nPlease share updates on your ongoing tasks:\n\n"
        for i, t in enumerate(active_tasks, 1):
            p_name = t['projects']['name'] if t.get('projects') else "Unknown Project"
            msg += f"{i}. {t['name']} - {p_name}\n"
        msg += "\nReply with updates in natural language."

        # 4. Send message to target (Asif) via Telegram
        await send_reply_func(msg, target_user_id=target_tid)
        
        # 5. Context Integration
        update_context(target_tid, last_prompt="awaiting_updates")
        
        # 6. Send confirmation to requester
        await send_reply_func(f"✅ Reminder sent to {user['name']}")
    except Exception as e:
        logger.error(f"Error in handle_trigger_reminder_user: {e}")
        await send_reply_func(f"Error: {str(e)}")

async def handle_ask_asif(entities, user_id, context, send_reply_func):
    # Backward compatibility for direct calls or old routing
    entities["target_user"] = "Asif"
    await handle_trigger_reminder_user(entities, user_id, context, send_reply_func)

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
        
    project_query = entities.get("project_name") or entities.get("task_name") # LLM might put project name here
    match = resolve_project(project_query, projects) if project_query else None
    
    if not match and context.get("active_project_id"):
        match = next((p for p in projects if p['id'] == context["active_project_id"]), None)

    if match:
        set_state(user_id, {"action": "create_task", "step": "waiting_for_task_name", "project_query": match['name']})
        await send_reply_func("enter task name")
    else:
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
    ctx = get_context(user_id)
    last_list = ctx.get('last_task_list', [])
    active_project_id = ctx.get('active_project_id')
    tasks = get_all_tasks()
    match = resolve_task_from_list(task_query, tasks, last_list_ids=last_list, active_project_id=active_project_id)
    
    if not match:
        await send_reply_func(f"Could not find task matching '{task_query}'.")
        return

    try:
        # Handle cases where progress is not provided (e.g. deadline-only update)
        if progress_str is not None:
            import re
            m = re.search(r'(\d+)', str(progress_str))
            if m:
                progress = int(m.group(1))
            else:
                progress = match.get('progress', 0)
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
    
    # NEW: Set state for potential follow-up note (Step 1)
    set_state(user_id, {
        "action": "task_update", 
        "task_id": match['id'], 
        "task_name": match['name']
    })
    
    dl_msg = f"\nDeadline: {deadline}" if deadline else ""
    proof_msg = f"Proof: [Image]" if images else ""
    await send_reply_func(f"Update saved ✅\nTask: {match['name']}\nProgress: {progress}%{dl_msg}\n{proof_msg}")

async def perform_add_blocker(task_query, description, user_id, send_reply_func, images=None):
    ctx = get_context(user_id)
    last_list = ctx.get('last_task_list', [])
    active_project_id = ctx.get('active_project_id')
    tasks = get_all_tasks()
    match = resolve_task_from_list(task_query, tasks, last_list_ids=last_list, active_project_id=active_project_id)
    
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

    
    ctx = get_context(user_id)
    last_list = ctx.get('last_task_list', [])
    tasks = get_all_tasks()
    match = resolve_task_from_list(task_query, tasks, last_list_ids=last_list)
        
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
