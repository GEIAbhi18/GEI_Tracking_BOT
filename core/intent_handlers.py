import logging
import json
import re
from db import (
    get_all_tasks, save_update, create_ticket, get_user_by_telegram_id, 
    get_projects, complete_task, add_blocker, get_tasks_for_user, get_task_blockers,
    get_open_tickets, get_user_by_name, remove_blocker, update_task_image
)
from core.conversation_state import set_state, clear_state
from core.context_manager import update_context, get_context
from core.utils import parse_human_date, resolve_project, resolve_task_from_list
from core.error_messages import (
    get_error_message, friendly_task_not_found, friendly_project_not_found,
    friendly_clarify, friendly_system_error, friendly_missing_info,
    friendly_permission_denied,
)

logger = logging.getLogger(__name__)


def _resolve_user(user_id):
    """Resolve a user by telegram_id, whatsapp_number, or DB ID (UUID)."""
    if not user_id:
        return None
    # 1. Try Telegram ID (works for Telegram users)
    u_info = get_user_by_telegram_id(user_id)
    if u_info:
        return u_info
    
    # 2. Fallback: try WhatsApp number (works for WhatsApp users)
    try:
        from whatsapp.task_assignment import get_user_by_whatsapp
        u_info = get_user_by_whatsapp(str(user_id))
        if u_info:
            return u_info
    except Exception:
        pass
        
    # 3. Fallback: try DB ID / UUID
    try:
        from db import get_user_by_id
        u_info = get_user_by_id(str(user_id))
        if u_info:
            return u_info
    except Exception:
        pass
    
    return None


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
    
    project_name_extracted = entities.get("project_name_extracted")
    
    if is_numeric_task and not active_project_id:
        if project_name_extracted:
            projects = get_projects()
            match = resolve_project(project_name_extracted, projects)
            if match:
                active_project_id = match['id']
                update_context(user_id, active_project_id=active_project_id)
        
        if not active_project_id:
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
        p_tasks = [t for t in tasks if t.get('project_id') == project_match['id']]
        if not p_tasks:
            await send_reply_func(f"No tasks found for project '{project_match['name']}'.")
            return
        # Sort tasks to match show tasks order
        p_tasks.sort(key=lambda x: x.get('project_task_number', 999))
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

    # Check for 100% completion - Ask for proof choice
    try:
        if progress is not None and int(str(progress).replace('%','')) >= 100 and not images:
            # Resolve task_name if it's a number from a list
            ctx = get_context(user_id)
            last_list = ctx.get('last_task_list', [])
            active_project_id = ctx.get('active_project_id')
            tasks = get_all_tasks()
            match = resolve_task_from_list(task_name, tasks, last_list_ids=last_list, active_project_id=active_project_id)
            resolved_name = match['name'] if match else task_name
            
            set_state(user_id, {"action": "update_task", "step": "waiting_for_proof_choice", "task_query": resolved_name, "progress": "100", "deadline": deadline})
            await send_reply_func(f"Task '{resolved_name}' is 100% complete! ✅\nDo you want to upload a proof image? (Reply **Yes** or **No**)")
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
    
    project_name_extracted = entities.get("project_name_extracted")

    if is_numeric_task and not active_project_id:
        if project_name_extracted:
            projects = get_projects()
            match = resolve_project(project_name_extracted, projects)
            if match:
                active_project_id = match['id']
                update_context(user_id, active_project_id=active_project_id)

        if not active_project_id:
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
        p_tasks = [t for t in tasks if t.get('project_id') == project_match['id']]
        if not p_tasks:
            await send_reply_func(f"No tasks found for project '{project_match['name']}'.")
            return
        # Sort tasks to match show tasks order
        p_tasks.sort(key=lambda x: x.get('project_task_number', 999))
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

    # Ask for proof choice
    if not images:
        set_state(user_id, {"action": "complete_task", "step": "waiting_for_proof_choice", "task_query": resolved_name})
        await send_reply_func(f"Task '{resolved_name}' is marked as complete! ✅\nDo you want to upload a proof image? (Reply **Yes** or **No**)")
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
    
    project_name_extracted = entities.get("project_name_extracted")

    if is_numeric_task and not active_project_id:
        if project_name_extracted:
            projects = get_projects()
            match = resolve_project(project_name_extracted, projects)
            if match:
                active_project_id = match['id']
                update_context(user_id, active_project_id=active_project_id)

        if not active_project_id:
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
        p_tasks = [t for t in tasks if t['status'] != 'Completed' and t.get('project_id') == project_match['id']]
        if not p_tasks:
            await send_reply_func(f"No pending tasks found for project '{project_match['name']}'.")
            return
        # Sort tasks to match show tasks order
        p_tasks.sort(key=lambda x: x.get('project_task_number', 999))
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
    
    if not task_name:
        set_state(user_id, {"action": "remove_blocker", "step": "waiting_for_project"})
        projects = get_projects()
        p_list = "\n".join([f"{idx+1}. {p['name']}" for idx, p in enumerate(projects)])
        await send_reply_func(f"Which project is the task in? (Type the number)\n\n{p_list}")
        return

    # Check if task_name is actually a project name
    projects = get_projects()
    project_match = resolve_project(task_name, projects)
    if project_match:
        tasks = get_all_tasks()
        blocked_tasks = [t for t in tasks if t.get('is_blocked') and t.get('project_id') == project_match['id']]
        if not blocked_tasks:
            await send_reply_func(f"No blocked tasks found for project '{project_match['name']}'.")
            return
        # Sort tasks to match show tasks order
        blocked_tasks.sort(key=lambda x: x.get('project_task_number', 999))
        tasks_msg = "\n".join([f"{idx+1}. {t['name']}" for idx, t in enumerate(blocked_tasks)])
        set_state(user_id, {"action": "remove_blocker", "step": "waiting_for_task", "project_query": project_match['name'], "_task_map": [t['name'] for t in blocked_tasks]})
        await send_reply_func(f"Which task in '{project_match['name']}' do you want to remove the blocker from? (Type the number)\n\n{tasks_msg}")
        return

    # Resolve task_name if it's a number from a list
    ctx = get_context(user_id)
    last_list = ctx.get('last_task_list', [])
    active_project_id = ctx.get('active_project_id')
    tasks = get_all_tasks()
    match = resolve_task_from_list(task_name, tasks, last_list_ids=last_list, active_project_id=active_project_id)
    resolved_name = match['name'] if match else task_name

    await perform_remove_blocker(resolved_name, user_id, send_reply_func)

async def handle_add_image(entities, user_id, context, send_reply_func, images=None):
    task_name = entities.get("task_name")
    
    if not task_name:
        set_state(user_id, {"action": "add_image", "step": "waiting_for_project"})
        projects = get_projects()
        p_list = "\n".join([f"{idx+1}. {p['name']}" for idx, p in enumerate(projects)])
        await send_reply_func(f"Which project is the task in? (Type the number)\n\n{p_list}")
        return

    # Check if task_name is actually a project name
    projects = get_projects()
    project_match = resolve_project(task_name, projects)
    if project_match:
        tasks = get_all_tasks()
        p_tasks = [t for t in tasks if t.get('project_id') == project_match['id']]
        if not p_tasks:
            await send_reply_func(f"No tasks found for project '{project_match['name']}'.")
            return
        # Sort tasks to match show tasks order
        p_tasks.sort(key=lambda x: x.get('project_task_number', 999))
        tasks_msg = "\n".join([f"{idx+1}. {t['name']}" for idx, t in enumerate(p_tasks)])
        set_state(user_id, {"action": "add_image", "step": "waiting_for_task", "project_query": project_match['name'], "_task_map": [t['name'] for t in p_tasks]})
        await send_reply_func(f"Which task in '{project_match['name']}' do you want to add an image to? (Type the number)\n\n{tasks_msg}")
        return

    # Resolve task_name if it's a number from a list
    ctx = get_context(user_id)
    last_list = ctx.get('last_task_list', [])
    active_project_id = ctx.get('active_project_id')
    tasks = get_all_tasks()
    match = resolve_task_from_list(task_name, tasks, last_list_ids=last_list, active_project_id=active_project_id)
    resolved_name = match['name'] if match else task_name

    if not images:
        set_state(user_id, {"action": "add_image", "step": "waiting_for_proof", "task_query": resolved_name})
        await send_reply_func(f"Please upload the image for '{resolved_name}'. (This will replace any older images)")
        return

    await perform_add_image(resolved_name, user_id, send_reply_func, images=images)


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
        filtered = [t for t in filtered if t.get("status") == "Completed"]
    elif status == "pending":
        filtered = [t for t in filtered if t.get("status") != "Completed"]
        
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

def build_building_grouped_tasks(building_structured_data, personal_tasks=None):
    """
    Formats tasks grouped by Building → Project → Tasks with continuous serial numbering.
    Returns (formatted_text, stored_task_ids)
    """
    from core.utils import format_date_human
    lines = []
    stored_task_ids = []
    serial = 1
    
    for b in (building_structured_data or []):
        b_name = b.get("building_name", "Unknown Building")
        projects = b.get("projects", [])
        
        has_tasks = any(p.get("tasks") for p in projects)
        if not has_tasks:
            continue
            
        lines.append(f"━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"🏢 *{b_name}*")
        lines.append(f"━━━━━━━━━━━━━━━━━━━━")
        lines.append("")
        
        for p in projects:
            p_name = p.get("project_name", "Unknown Project")
            p_tasks = p.get("tasks", [])
            if not p_tasks:
                continue
                
            lines.append(f"*{p_name}*")
            lines.append("")
            
            for t in p_tasks:
                t_id = t.get("id")
                stored_task_ids.append(t_id)
                
                t_title = t.get("title") or t.get("name") or "Unknown Task"
                start_val = t.get("planned_start_date") or t.get("created_at")
                start_str = format_date_human(start_val)
                dl_str = format_date_human(t.get("deadline"))
                
                prog = t.get("progress", 0) or 0
                is_done = False
                try:
                    is_done = int(float(prog)) >= 100 or str(t.get("status", "")).lower() == "completed"
                except Exception:
                    pass
                    
                done_marker = " ✅" if is_done else ""
                
                updates = t.get("updates") or []
                blocker_count = 0
                for u in updates:
                    b_val = str(u.get("blockers") or "").lower()
                    if b_val and b_val not in ["none", "null", "undefined"]:
                        blocker_count += 1
                br = str(t.get("blocker_reason") or "").lower()
                if br and br not in ["none", "null"] and not any(str(u.get("blockers") or "").lower() == br for u in updates):
                    blocker_count += 1
                if t.get("is_blocked"):
                    blocker_count = max(1, blocker_count)
                    
                blocker_marker = " 🛑" if (not is_done and blocker_count > 0) else ""
                
                line = f"{serial}. {t_title} – Start: {start_str} | Deadline: {dl_str} | {prog}% done{done_marker} | {blocker_count} blocker(s){blocker_marker}"
                lines.append(line)
                serial += 1
                
            lines.append("")
            
    if personal_tasks:
        lines.append("👤 *My Personal Tasks*")
        lines.append("")
        for t in personal_tasks:
            t_id = t.get("id")
            stored_task_ids.append(t_id)
            
            t_title = t.get("title") or t.get("name") or "Unknown Task"
            start_val = t.get("planned_start_date") or t.get("created_at")
            start_str = format_date_human(start_val)
            dl_str = format_date_human(t.get("deadline"))
            
            prog = t.get("progress", 0) or 0
            is_done = False
            try:
                is_done = int(float(prog)) >= 100 or str(t.get("status", "")).lower() == "completed"
            except Exception:
                pass
                
            done_marker = " ✅" if is_done else ""
            blocker_count = 1 if t.get("is_blocked") else 0
            blocker_marker = " 🛑" if (not is_done and blocker_count > 0) else ""
            
            line = f"{serial}. {t_title} – Start: {start_str} | Deadline: {dl_str} | {prog}% done{done_marker} | {blocker_count} blocker(s){blocker_marker}"
            lines.append(line)
            serial += 1
            
        lines.append("")
        
    return "\n".join(lines).strip(), stored_task_ids

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
                p_name = 'Personal Tasks' if t.get('task_type') == 'PERSONAL' else 'No Project'
            
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
            'planned_start_date': t.get('planned_start_date'),
            'progress': prog,
            'blockerCount': blocker_count
            })
        except Exception as e:
            logger.error(f"Error processing task {t.get('id', 'unknown')}: {e}")
            continue
        
    msg = ""
    all_projects = get_projects() or []
    project_order_map = {p['name']: i for i, p in enumerate(all_projects) if isinstance(p, dict) and 'name' in p}
    
    sorted_p_names = sorted(grouped.keys(), key=lambda x: project_order_map.get(x, 999))
    
    for proj_idx, p_name in enumerate(sorted_p_names, 1):
        t_list = grouped[p_name]
        msg += f"**{proj_idx}. {p_name}**\n"
        t_list = sorted(t_list, key=lambda x: (float(x['number']) if str(x['number']).replace('.','').isdigit() else 999))
        for t in t_list:
            from core.utils import format_date_human
            start_val = t.get('planned_start_date') or t.get('created_at')
            start_str = format_date_human(start_val)
            dl_str = format_date_human(t.get('deadline'))
            
            try:
                current_prog = t.get('progress', 0)
                if current_prog is None: current_prog = 0
                is_done = int(float(current_prog)) >= 100
            except Exception:
                is_done = False
                
            done_marker = " ✅" if is_done else ""
            blocker_marker = " 🛑" if (not is_done and int(t.get('blockerCount', 0)) > 0) else ""
            msg += f"{int(t['number'])}. {t['name']} – Start: {start_str} | Deadline: {dl_str} | {t['progress']}% done{done_marker} | {t['blockerCount']} blocker(s){blocker_marker}\n"
        msg += "\n"
        
    return msg.strip()

def build_personal_tasks_list_py(tasks):
    if not tasks:
        return "No personal tasks currently assigned."
    
    from core.utils import format_date_human
    msg = ""
    for idx, t in enumerate(tasks, 1):
        try:
            updates = t.get('updates') or []
            prog = t.get('progress', 0)
            if prog is None:
                prog = 0
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

            start_val = t.get('planned_start_date') or t.get('created_at')
            start_str = format_date_human(start_val)
            dl_str = format_date_human(t.get('deadline'))

            is_done = False
            try:
                if prog is not None:
                    is_done = int(float(prog)) >= 100
            except Exception:
                pass

            done_marker = " ✅" if is_done else ""
            blocker_marker = " 🛑" if (not is_done and blocker_count > 0) else ""
            
            task_title = t.get('title') or t.get('name') or 'Unknown Task'
            msg += f"{idx}. {task_title} – Start: {start_str} | Deadline: {dl_str} | {prog}% done{done_marker} | {blocker_count} blocker(s){blocker_marker}\n"
        except Exception as e:
            logger.error(f"Error processing personal task {t.get('id', 'unknown')}: {e}")
            continue

    return msg.strip()

def _resolve_user(user_id):
    """Resolve a user by telegram_id, whatsapp_number, or DB ID (UUID)."""
    if not user_id:
        return None
    # 1. Try WhatsApp authentication middleware (handles impersonation & WA number)
    try:
        from auth.middleware import authenticate_whatsapp_request
        u_info = authenticate_whatsapp_request(str(user_id))
        if u_info:
            return u_info
    except Exception:
        pass

    # 2. Try Telegram ID (works for Telegram users)
    u_info = get_user_by_telegram_id(user_id)
    if u_info:
        return u_info
    
    # 3. Fallback: try WhatsApp number directly
    try:
        from whatsapp.task_assignment import get_user_by_whatsapp
        u_info = get_user_by_whatsapp(str(user_id))
        if u_info:
            return u_info
    except Exception:
        pass
        
    # 4. Fallback: try DB ID / UUID
    try:
        from db import get_user_by_id
        u_info = get_user_by_id(str(user_id))
        if u_info:
            return u_info
    except Exception:
        pass
    
    return None

async def handle_query_tasks(entities, user_id, context, send_reply_func):
    u_info = _resolve_user(user_id)
    target_user_id = u_info['id'] if u_info else None
    
    if not target_user_id:
        await send_reply_func("Your account is not registered. Please contact Kanav.")
        return

    from db import get_tasks_by_buildings, get_all_tasks
    
    raw_message = (entities.get("raw_text") or "").lower()
    if not raw_message and context and context.get("messages"):
        raw_message = str(context.get("messages", [])[-1]).lower()
    
    filters = entities.get("query_filters") or {}
    
    is_only_team = ("show team tasks" in raw_message or raw_message == "team tasks") and "personal" not in raw_message
    is_only_personal = ("show my personal tasks" in raw_message or "personal tasks" in raw_message) and "team" not in raw_message

    building_data = get_tasks_by_buildings(target_user_id, include_completed=True) if not is_only_personal else []
    
    # Filter building tasks if filters applied
    if filters and building_data:
        for b in building_data:
            for p in b.get("projects", []):
                p["tasks"] = filter_tasks(p.get("tasks", []), filters)

    # Personal tasks
    personal_tasks = []
    if not is_only_team:
        all_tasks = get_all_tasks(user_id=target_user_id, include_personal=True)
        raw_personal = [
            t for t in all_tasks 
            if t.get('task_type') == 'PERSONAL' and (
                str(t.get('created_by')) == str(target_user_id) or
                str(t.get('assigned_to')) == str(target_user_id) or
                str(t.get('assigned_by')) == str(target_user_id)
            )
        ]
        personal_tasks = filter_tasks(raw_personal, filters)

    if not building_data and not personal_tasks:
        if is_only_personal:
            msg = "👤 *My Personal Tasks*\n\nNo personal tasks currently assigned."
        elif is_only_team:
            msg = "📋 *Team Tasks*\n\nNo team tasks currently assigned for your assigned buildings."
        else:
            from db import get_user_buildings
            u_b = get_user_buildings(target_user_id)
            if not u_b and u_info.get("role") not in ["Director", "Developer"]:
                msg = "No building/task access assigned to your profile."
            else:
                msg = "No active tasks found."
        await send_reply_func(msg)
        return

    formatted_text, stored_task_ids = build_building_grouped_tasks(
        building_data if not is_only_personal else [],
        personal_tasks=personal_tasks if not is_only_team else []
    )
    
    update_context(user_id, last_task_list=stored_task_ids, active_project_id=None)
    await send_reply_func(formatted_text)

async def handle_get_task_detail(entities, user_id, context, send_reply_func):
    task_reference = entities.get("task_reference") or entities.get("task_name")
    
    if not task_reference:
        await send_reply_func("Which task do you want to see details for? (e.g., 'task 1')")
        return
        
    import re
    is_numeric_task = task_reference and re.match(r'^(task\s*)?\d+$', str(task_reference).lower().strip())
    ctx = get_context(user_id)
    active_project_id = ctx.get("active_project_id")
    
    project_name_extracted = entities.get("project_name_extracted")

    if is_numeric_task and not active_project_id:
        if project_name_extracted:
            projects = get_projects()
            match = resolve_project(project_name_extracted, projects)
            if match:
                active_project_id = match['id']
                update_context(user_id, active_project_id=active_project_id)

        if not active_project_id:
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
            await send_reply_func(friendly_task_not_found(str(task_reference)))
        elif not last_list:
            await send_reply_func("I don't have a recent task list yet.\nTry: 'show tasks' first to load your list")
        else:
            await send_reply_func(friendly_task_not_found(str(task_reference)))
        return

    # Access control check for building
    u_info = _resolve_user(user_id)
    target_uid = u_info['id'] if u_info else None
    if target_uid:
        from db import check_building_access
        if not check_building_access(target_uid, match['id']):
            await send_reply_func("🚫 Unauthorized: You do not have access to view details for tasks in this building.")
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
        u_info = _resolve_user(user_id)
        if u_info:
            add_ticket_message(target_ticket['id'], u_info['id'], reply_msg)
            await send_reply_func(f"✅ Reply added to Ticket {ticket_index}.")
        else:
            await send_reply_func("Your device isn't registered yet.\nPlease contact Kanav to get set up.")
    else:
        await send_reply_func(f"Couldn't find Ticket {ticket_index}.\nTry: 'view tickets' to see all open tickets")

async def handle_close_ticket(entities, user_id, context, send_reply_func):
    ticket_index = entities.get("ticket_index")
    from db import get_open_tickets, close_ticket
    tickets = get_open_tickets()
    if ticket_index and 1 <= ticket_index <= len(tickets):
        target_ticket = tickets[ticket_index - 1]
        close_ticket(target_ticket['id'])
        await send_reply_func(f"✅ Ticket {ticket_index} closed.")
    else:
        await send_reply_func(f"Couldn't find Ticket {ticket_index}.\nTry: 'view tickets' to see all open tickets")

def generate_pdf_report(team_name=None):
    from fpdf import FPDF
    import os
    from datetime import datetime
    import pytz
    from core.utils import format_date_human
    from db import supabase, get_user_by_id, get_projects, get_all_tasks
    from config import TIMEZONE
    from collections import defaultdict

    def clean(text):
        if not text: return ""
        replacements = {
            "\u2014": "-", "\u2013": "-", "\u2022": "*", 
            "\u00b7": "|", "\u201c": "\"", "\u201d": "\"",
            "\u2018": "'", "\u2019": "'"
        }
        text = str(text)
        for k, v in replacements.items():
            text = text.replace(k, v)
        return text.encode('latin-1', 'replace').decode('latin-1')

    # --- Configuration & Colors ---
    COLORS = {
        "HEADER_BG": (31, 95, 160),      # Professional Blue
        "TEXT_DARK": (40, 40, 40),
        "TEXT_GREY": (100, 100, 100),
        "LINE_GREY": (200, 200, 200),
        "ZREBRA_BG": (245, 248, 252),    # Light Blue-Grey
        "RED": (200, 50, 50),
        "AMBER": (220, 150, 0),
        "GREEN": (40, 150, 40),
        "NOT_STARTED": (120, 120, 120)
    }

    class GEIReport(FPDF):
        def header(self):
            pass

        def footer(self):
            self.set_draw_color(*COLORS["LINE_GREY"])
            self.line(10, self.h - 15, self.w - 10, self.h - 15)
            
            self.set_y(-12)
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(*COLORS["TEXT_GREY"])
            self.cell(0, 10, clean("GEI Tracking Bot | Auto-generated | Confidential | Do not distribute"), align="C")

    # Initialize PDF
    pdf = GEIReport()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    
    # --- Top Header Section ---
    local_tz = pytz.timezone(TIMEZONE or "UTC")
    now_local = datetime.now(local_tz)
    date_str = now_local.strftime("%d %B %Y")
    time_str = now_local.strftime("%I:%M %p %Z")

    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(*COLORS["TEXT_DARK"])
    pdf.cell(100, 15, "Daily Project Report", ln=0)
    
    # Date/Time on Right
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*COLORS["TEXT_GREY"])
    pdf.set_x(-70)
    pdf.cell(60, 5, date_str, ln=1, align="R")
    pdf.set_x(-70)
    pdf.cell(60, 5, f"Generated at {time_str}", ln=1, align="R")
    
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*COLORS["TEXT_GREY"])
    pdf.cell(0, 5, clean("GEI Construction | Telegram Project Tracker | Auto-generated"), ln=1)
    
    # Separator Line
    pdf.set_draw_color(*COLORS["HEADER_BG"])
    pdf.set_line_width(0.5)
    pdf.line(10, pdf.get_y() + 2, 200, pdf.get_y() + 2)
    pdf.ln(10)

    projects = get_projects()
    tasks = get_all_tasks(include_personal=True)
    
    # Filter by team_name if provided
    if team_name:
        team_res = supabase.table("teams").select("id").eq("name", team_name).execute()
        if team_res.data:
            team_id = team_res.data[0]["id"]
            tasks = [t for t in tasks if t.get("team_id") == team_id]

    def check_space(h):
        if pdf.get_y() + h > pdf.page_break_trigger:
            pdf.add_page()

    def get_sort_date(task):
        dt_str = task.get('deadline') or task.get('planned_start_date') or task.get('created_at')
        if not dt_str: return datetime(9999, 12, 31)
        try:
            if isinstance(dt_str, str):
                return datetime.fromisoformat(dt_str.replace('Z', '+00:00')).replace(tzinfo=None)
            return dt_str
        except:
            return datetime(9999, 12, 31)

    def render_task_table(group_tasks):
        pdf.set_fill_color(*COLORS["HEADER_BG"])
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 9)
        
        cols = [
            ("Task", 38), ("Start", 22), ("Deadline", 22), ("Progress", 25), 
            ("RAG", 18), ("Blocker", 28), ("Note", 25), ("Proof", 12)
        ]
        
        for label, width in cols:
            pdf.cell(width, 8, label, fill=True, border=0, align="L" if label == "Task" else "C")
        pdf.ln(8)

        for idx, t in enumerate(group_tasks):
            fill = (idx % 2 != 0)
            if fill: pdf.set_fill_color(*COLORS["ZREBRA_BG"])
            else: pdf.set_fill_color(255, 255, 255)
            
            progress = int(t.get("progress", 0) or 0)
            start_date = format_date_human(t.get("planned_start_date") or t.get("created_at"))
            deadline = format_date_human(t.get("deadline"))
            
            latest_note = "None"
            blocker = t.get("blocker_reason") or "None"
            atts = t.get("attachments") or []
            
            update_res = supabase.table("updates").select("note, blockers, images").eq("task_id", t["id"]).order("timestamp", desc=True).limit(5).execute()
            if update_res.data:
                blocker = next((u["blockers"] for u in update_res.data if u["blockers"] and u["blockers"].lower() not in ["none", "null", ""]), blocker)
                latest_note = next((u["note"] for u in update_res.data if u["note"]), "None")
                for u in update_res.data:
                    if u["images"]: atts.extend(u["images"])

            t_start = None
            try: t_start = datetime.fromisoformat(str(t.get("planned_start_date") or t.get("created_at")).replace('Z', '+00:00'))
            except: pass
            t_dl = None
            try: t_dl = datetime.fromisoformat(str(t.get("deadline")).replace('Z', '+00:00'))
            except: pass
            from rag import calculate_rag
            rag_val, _ = calculate_rag(progress, t_start, t_dl, blocker)
            
            check_space(12)
            y_row = pdf.get_y()
            pdf.set_text_color(*COLORS["TEXT_DARK"])
            pdf.set_font("Helvetica", "B", 8)
            
            pdf.set_draw_color(*COLORS["LINE_GREY"])
            pdf.cell(38, 12, clean(t["name"][:25]), fill=True, border="B")
            
            pdf.set_font("Helvetica", "", 8)
            pdf.cell(22, 12, start_date, fill=True, border="B", align="C")
            pdf.cell(22, 12, deadline, fill=True, border="B", align="C")
            
            x_prev = pdf.get_x()
            pdf.cell(25, 12, "", fill=True, border="B")
            
            bar_w = 18
            bar_h = 2.5
            pdf.set_draw_color(*COLORS["LINE_GREY"])
            pdf.set_fill_color(230, 230, 230)
            pdf.rect(x_prev + 3.5, y_row + 6, bar_w, bar_h, style="FD")
            
            p_color = COLORS["GREEN"] if progress >= 100 else (100, 150, 255)
            pdf.set_fill_color(*p_color)
            pdf.rect(x_prev + 3.5, y_row + 6, (progress / 100) * bar_w, bar_h, style="F")
            
            pdf.set_y(y_row + 2)
            pdf.set_x(x_prev)
            pdf.set_font("Helvetica", "", 6)
            pdf.set_text_color(*COLORS["TEXT_GREY"])
            pdf.cell(25, 4, f"{progress}%", align="C")
            pdf.set_y(y_row)
            pdf.set_x(x_prev + 25)
            
            x_rag = pdf.get_x()
            pdf.set_fill_color(*(COLORS["ZREBRA_BG"] if fill else (255,255,255)))
            pdf.cell(18, 12, "", fill=True, border="B")
            
            r_color = COLORS.get(rag_val, COLORS["TEXT_DARK"])
            pdf.set_fill_color(*r_color)
            pdf.ellipse(x_rag + 2, y_row + 4.5, 2, 2, style="F")
            
            pdf.set_xy(x_rag + 5, y_row)
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(*r_color)
            pdf.cell(13, 12, rag_val.capitalize().replace("_", " "), align="L")
            
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(*COLORS["TEXT_DARK"])
            pdf.cell(28, 12, clean(blocker[:18] + ".." if len(blocker) > 18 else blocker), fill=True, border="B", align="L")
            pdf.cell(25, 12, clean(latest_note[:15] + ".." if len(latest_note) > 15 else latest_note), fill=True, border="B", align="L")
            
            if atts:
                pdf.set_text_color(30, 100, 200)
                pdf.set_font("Helvetica", "U", 8)
                pdf.cell(12, 12, "View", fill=True, border="B", align="C", link=atts[0])
            else:
                pdf.set_text_color(*COLORS["TEXT_GREY"])
                pdf.set_font("Helvetica", "", 8)
                pdf.cell(12, 12, "-", fill=True, border="B", align="C")
            
            pdf.ln(12)
        pdf.ln(10)

    # ─────────────────────────────────────────────────────────────────────────
    # Fetch all teams from DB for grouping
    # ─────────────────────────────────────────────────────────────────────────
    from teams.repository import get_all_teams
    all_teams = get_all_teams() or []

    # Build team id → name and name → id maps
    team_id_to_name = {t["id"]: t["name"] for t in all_teams}

    # Known primary team names to show in the Team Tasks section (in order)
    KNOWN_TEAM_NAMES = ["Facilities Team", "Project Team", "Tech Team"]

    # Helper to fetch a task's team id (from team_id field directly)
    def task_team_id(task):
        return task.get("team_id")

    # Compute which team (by name) a task belongs to
    def task_team_name(task):
        tid = task_team_id(task)
        if not tid:
            return None
        return team_id_to_name.get(tid)

    # ─────────────────────────────────────────────────────────────────────────
    # Helper: render a team/subgroup section header (blue strip)
    # ─────────────────────────────────────────────────────────────────────────
    def render_main_section_header(title, color=None):
        """Full-width dark blue section header (e.g. 'Team Tasks')."""
        bg = color or COLORS["HEADER_BG"]
        check_space(18)
        pdf.set_fill_color(*bg)
        pdf.rect(10, pdf.get_y(), 190, 12, style="F")
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(190, 12, "  " + clean(title), ln=1)
        pdf.ln(3)

    def render_team_subheader(team_name_str, team_tasks):
        """Medium subheader row for a team inside a main section."""
        check_space(40)
        task_stats = {"RED": 0, "AMBER": 0, "GREEN": 0, "NOT_STARTED": 0}
        for t in team_tasks:
            from rag import calculate_rag
            progress = t.get("progress", 0)
            t_start = None
            try: t_start = datetime.fromisoformat(str(t.get("planned_start_date") or t.get("created_at")).replace('Z', '+00:00'))
            except: pass
            t_dl = None
            try: t_dl = datetime.fromisoformat(str(t.get("deadline")).replace('Z', '+00:00'))
            except: pass
            t_rag, _ = calculate_rag(progress, t_start, t_dl, t.get("blocker_reason"))
            task_stats[t_rag] = task_stats.get(t_rag, 0) + 1

        pdf.set_fill_color(220, 232, 246)
        pdf.rect(10, pdf.get_y(), 190, 10, style="F")
        pdf.set_draw_color(*COLORS["HEADER_BG"])
        pdf.set_line_width(0.5)
        pdf.line(10, pdf.get_y(), 10, pdf.get_y() + 10)  # left accent bar

        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(*COLORS["HEADER_BG"])
        pdf.cell(90, 10, "   " + clean(team_name_str), ln=0)

        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*COLORS["RED"])
        pdf.cell(8, 10, str(task_stats["RED"]), align="R")
        pdf.set_text_color(*COLORS["TEXT_DARK"])
        pdf.cell(12, 10, " Red ", align="L")
        pdf.set_text_color(*COLORS["AMBER"])
        pdf.cell(8, 10, str(task_stats["AMBER"]), align="R")
        pdf.set_text_color(*COLORS["TEXT_DARK"])
        pdf.cell(14, 10, " Amber ", align="L")
        pdf.set_text_color(*COLORS["GREEN"])
        pdf.cell(8, 10, str(task_stats["GREEN"]), align="R")
        pdf.set_text_color(*COLORS["TEXT_DARK"])
        pdf.cell(12, 10, " Green", align="L")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*COLORS["TEXT_GREY"])
        pdf.cell(0, 10, f"({len(team_tasks)} tasks)", ln=1, align="R")
        pdf.set_draw_color(*COLORS["LINE_GREY"])
        pdf.set_line_width(0.2)

    def render_no_tasks_row():
        """Render a grey 'No Tasks' placeholder row."""
        check_space(10)
        pdf.set_fill_color(248, 248, 248)
        pdf.rect(10, pdf.get_y(), 190, 8, style="F")
        pdf.set_draw_color(*COLORS["LINE_GREY"])
        pdf.rect(10, pdf.get_y(), 190, 8, style="D")
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(*COLORS["TEXT_GREY"])
        pdf.cell(190, 8, "   No Tasks", ln=1, align="L")
        pdf.ln(4)

    def render_project_subheader(p, p_tasks):
        """Small project-level subheader inside a team section."""
        check_space(30)
        task_stats = {"RED": 0, "AMBER": 0, "GREEN": 0, "NOT_STARTED": 0}
        for t in p_tasks:
            from rag import calculate_rag
            progress = t.get("progress", 0)
            t_start = None
            try: t_start = datetime.fromisoformat(str(t.get("planned_start_date") or t.get("created_at")).replace('Z', '+00:00'))
            except: pass
            t_dl = None
            try: t_dl = datetime.fromisoformat(str(t.get("deadline")).replace('Z', '+00:00'))
            except: pass
            t_rag, _ = calculate_rag(progress, t_start, t_dl, t.get("blocker_reason"))
            task_stats[t_rag] = task_stats.get(t_rag, 0) + 1

        pdf.set_fill_color(240, 240, 240)
        pdf.rect(10, pdf.get_y(), 190, 9, style="F")
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*COLORS["TEXT_DARK"])
        pdf.cell(85, 9, "   \u25B6 " + clean(p["name"][:35]), ln=0)

        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*COLORS["RED"])
        pdf.cell(8, 9, str(task_stats["RED"]), align="R")
        pdf.set_text_color(*COLORS["TEXT_DARK"])
        pdf.cell(12, 9, " Red ", align="L")
        pdf.set_text_color(*COLORS["AMBER"])
        pdf.cell(8, 9, str(task_stats["AMBER"]), align="R")
        pdf.set_text_color(*COLORS["TEXT_DARK"])
        pdf.cell(14, 9, " Amber ", align="L")
        pdf.set_text_color(*COLORS["GREEN"])
        pdf.cell(8, 9, str(task_stats["GREEN"]), align="R")
        pdf.set_text_color(*COLORS["TEXT_DARK"])
        pdf.cell(12, 9, " Green", align="L")
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*COLORS["TEXT_GREY"])
        pdf.cell(0, 9, f"({len(p_tasks)} tasks)", ln=1, align="R")

    # ─────────────────────────────────────────────────────────────────────────
    # Non-personal tasks
    # ─────────────────────────────────────────────────────────────────────────
    non_personal = [t for t in tasks if t.get("task_type") != "PERSONAL"]

    # Tasks that belong to a known team
    def tasks_for_known_team(team_name_str):
        matched_team = next((t for t in all_teams if t["name"] == team_name_str), None)
        if not matched_team:
            return []
        tid = matched_team["id"]
        return [t for t in non_personal if t.get("team_id") == tid]

    # Tasks that belong to unknown/other teams or no team
    known_team_ids = {t["id"] for t in all_teams if t["name"] in KNOWN_TEAM_NAMES}
    # Also exclude tasks from the "Personal" project to avoid confusing duplicate labels
    personal_project_ids = {p["id"] for p in projects if p["name"].lower() == "personal"}
    old_tasks = [t for t in non_personal if (not t.get("team_id") or t.get("team_id") not in known_team_ids) and t.get("project_id") not in personal_project_ids]

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 1: Team Tasks
    # ─────────────────────────────────────────────────────────────────────────
    render_main_section_header("Team Tasks")

    for team_name_str in KNOWN_TEAM_NAMES:
        team_tasks = tasks_for_known_team(team_name_str)

        if team_tasks:
            render_team_subheader(team_name_str, team_tasks)
        else:
            # Show subheader with "No Tasks" even when empty
            check_space(25)
            pdf.set_fill_color(220, 232, 246)
            pdf.rect(10, pdf.get_y(), 190, 10, style="F")
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(*COLORS["HEADER_BG"])
            pdf.cell(190, 10, "   " + clean(team_name_str), ln=1)
            render_no_tasks_row()
            continue

        # Group team tasks by project
        team_project_ids = list({t.get("project_id") for t in team_tasks if t.get("project_id")})
        # Also include tasks with no project (standalone team tasks)
        standalone = [t for t in team_tasks if not t.get("project_id")]

        rendered_any = False
        for p in projects:
            if p["id"] not in team_project_ids:
                continue
            p_tasks = [t for t in team_tasks if t.get("project_id") == p["id"]]
            if not p_tasks:
                continue
            p_tasks.sort(key=get_sort_date)
            render_project_subheader(p, p_tasks)
            render_task_table(p_tasks)
            rendered_any = True

        if standalone:
            standalone.sort(key=get_sort_date)
            check_space(15)
            pdf.set_fill_color(248, 248, 248)
            pdf.rect(10, pdf.get_y(), 190, 8, style="F")
            pdf.set_font("Helvetica", "BI", 10)
            pdf.set_text_color(*COLORS["TEXT_GREY"])
            pdf.cell(190, 8, "   General Tasks (no project)", ln=1, align="L")
            render_task_table(standalone)
            rendered_any = True

        if not rendered_any:
            render_no_tasks_row()

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 2: Personal Tasks
    # ─────────────────────────────────────────────────────────────────────────
    personal_tasks = [t for t in tasks if t.get("task_type") == "PERSONAL"]
    if personal_tasks:
        check_space(40)
        render_main_section_header("Personal Tasks", color=(31, 95, 160))

        user_name_cache = {}
        def get_owner_name(t):
            u_id = t.get("assigned_to") or t.get("created_by") or t.get("assigned_by")
            if not u_id:
                return "Personal"
            u_str = str(u_id)
            if u_str in user_name_cache:
                return user_name_cache[u_str]
            name = None
            if isinstance(t.get("assigned_to_user"), dict) and t["assigned_to_user"].get("name"):
                name = t["assigned_to_user"]["name"]
            elif isinstance(t.get("creator_user"), dict) and t["creator_user"].get("name"):
                name = t["creator_user"]["name"]
            else:
                u_info = get_user_by_id(u_str)
                if u_info and u_info.get("name"):
                    name = u_info["name"]
            final_name = name or "Personal"
            user_name_cache[u_str] = final_name
            return final_name

        user_personal_tasks = defaultdict(list)
        for t in personal_tasks:
            owner = get_owner_name(t)
            user_personal_tasks[owner].append(t)

        for owner_name, u_tasks in sorted(user_personal_tasks.items()):
            u_tasks.sort(key=get_sort_date)

            task_stats = {"RED": 0, "AMBER": 0, "GREEN": 0, "NOT_STARTED": 0}
            for t in u_tasks:
                from rag import calculate_rag
                progress = t.get("progress", 0)
                t_start = None
                try: t_start = datetime.fromisoformat(str(t.get("planned_start_date") or t.get("created_at")).replace('Z', '+00:00'))
                except: pass
                t_dl = None
                try: t_dl = datetime.fromisoformat(str(t.get("deadline")).replace('Z', '+00:00'))
                except: pass
                t_rag, _ = calculate_rag(progress, t_start, t_dl, t.get("blocker_reason"))
                task_stats[t_rag] = task_stats.get(t_rag, 0) + 1

            check_space(45)
            pdf.set_fill_color(240, 244, 248)
            pdf.rect(10, pdf.get_y(), 190, 9, style="F")
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_text_color(*COLORS["TEXT_DARK"])
            pdf.cell(90, 9, "  " + clean(owner_name), ln=0)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(*COLORS["RED"])
            pdf.cell(8, 9, str(task_stats["RED"]), align="R")
            pdf.set_text_color(*COLORS["TEXT_DARK"])
            pdf.cell(12, 9, " Red ", align="L")
            pdf.set_text_color(*COLORS["AMBER"])
            pdf.cell(8, 9, str(task_stats["AMBER"]), align="R")
            pdf.set_text_color(*COLORS["TEXT_DARK"])
            pdf.cell(14, 9, " Amber ", align="L")
            pdf.set_text_color(*COLORS["GREEN"])
            pdf.cell(8, 9, str(task_stats["GREEN"]), align="R")
            pdf.set_text_color(*COLORS["TEXT_DARK"])
            pdf.cell(12, 9, " Green", align="L")
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*COLORS["TEXT_GREY"])
            pdf.cell(0, 9, clean(f" ({len(u_tasks)} tasks)"), ln=1, align="R")
            render_task_table(u_tasks)

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 3: Old Tasks & Projects
    # ─────────────────────────────────────────────────────────────────────────
    if old_tasks:
        render_main_section_header("Old Tasks & Projects", color=(90, 90, 90))

        # Group by project
        old_project_ids = list({t.get("project_id") for t in old_tasks if t.get("project_id")})
        old_standalone = [t for t in old_tasks if not t.get("project_id")]

        for p in projects:
            if p["id"] not in old_project_ids:
                continue
            p_tasks = [t for t in old_tasks if t.get("project_id") == p["id"]]
            if not p_tasks:
                continue
            p_tasks.sort(key=get_sort_date)

            # Project subheader (grey)
            check_space(30)
            task_stats = {"RED": 0, "AMBER": 0, "GREEN": 0, "NOT_STARTED": 0}
            for t in p_tasks:
                from rag import calculate_rag
                progress = t.get("progress", 0)
                t_start = None
                try: t_start = datetime.fromisoformat(str(t.get("planned_start_date") or t.get("created_at")).replace('Z', '+00:00'))
                except: pass
                t_dl = None
                try: t_dl = datetime.fromisoformat(str(t.get("deadline")).replace('Z', '+00:00'))
                except: pass
                t_rag, _ = calculate_rag(progress, t_start, t_dl, t.get("blocker_reason"))
                task_stats[t_rag] = task_stats.get(t_rag, 0) + 1

            pdf.set_fill_color(230, 230, 230)
            pdf.rect(10, pdf.get_y(), 190, 9, style="F")
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(70, 70, 70)
            pdf.cell(85, 9, "   " + clean(p["name"][:35]), ln=0)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(*COLORS["RED"])
            pdf.cell(8, 9, str(task_stats["RED"]), align="R")
            pdf.set_text_color(70, 70, 70)
            pdf.cell(12, 9, " Red ", align="L")
            pdf.set_text_color(*COLORS["AMBER"])
            pdf.cell(8, 9, str(task_stats["AMBER"]), align="R")
            pdf.set_text_color(70, 70, 70)
            pdf.cell(14, 9, " Amber ", align="L")
            pdf.set_text_color(*COLORS["GREEN"])
            pdf.cell(8, 9, str(task_stats["GREEN"]), align="R")
            pdf.set_text_color(70, 70, 70)
            pdf.cell(12, 9, " Green", align="L")
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(*COLORS["TEXT_GREY"])
            pdf.cell(0, 9, f"({len(p_tasks)} tasks)", ln=1, align="R")

            render_task_table(p_tasks)

        if old_standalone:
            old_standalone.sort(key=get_sort_date)
            check_space(15)
            pdf.set_fill_color(230, 230, 230)
            pdf.rect(10, pdf.get_y(), 190, 8, style="F")
            pdf.set_font("Helvetica", "BI", 10)
            pdf.set_text_color(70, 70, 70)
            pdf.cell(190, 8, "   Unassigned Tasks", ln=1, align="L")
            render_task_table(old_standalone)

    filepath = f"/tmp/daily_report_{team_name if team_name else 'all'}.pdf"
    pdf.output(filepath)
    return filepath


async def handle_trigger_reminder_user(entities, user_id, context, send_reply_func):
    target_name = entities.get("target_user") or "Asif"
    
    try:
        # 1. Resolve user
        user = get_user_by_name(target_name)
        if not user or not user.get('telegram_id'):
            await send_reply_func(f"Couldn't find '{target_name}' in the system.\nMake sure the name is spelled correctly.")
            return
            
        target_tid = user['telegram_id']
        target_uuid = user['id']
        
        # 2. Fetch tasks
        tasks = get_tasks_for_user(target_uuid)
        active_tasks = [t for t in tasks if t['status'] != 'Completed']
        
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
        await send_reply_func(friendly_system_error())

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
    from db import get_buildings
    buildings = get_buildings()
    if not buildings:
        set_state(user_id, {"action": "create_project", "step": "waiting_for_name"})
        await send_reply_func("What is the name of the new project?")
        return
        
    set_state(user_id, {"action": "create_project", "step": "waiting_for_building", "buildings": [b['id'] for b in buildings]})
    # Try WhatsApp interactive buttons (max 3)
    try:
        from whatsapp.ux import send_interactive_buttons
        buttons = [{"id": f"create_proj_b_{b['name']}", "title": b['name']} for b in buildings[:3]]
        send_interactive_buttons(str(user_id), "Which building is this new project for?", buttons)
    except Exception:
        # Fallback to text list for non-WhatsApp channels
        b_list = "\n".join([f"{idx+1}. {b['name']}" for idx, b in enumerate(buildings)])
        await send_reply_func(f"Which building is this new project for? (Type the number)\n\n{b_list}")

async def handle_create_task(entities, user_id, context, send_reply_func):
    projects = get_projects()
    if not projects:
        await send_reply_func("No projects exist. Create a project first.")
        return

    # Resolve creator's DB UUID (needed for WA assignment flow)
    creator_db_id = None
    try:
        creator_info = _resolve_user(user_id)
        creator_db_id = creator_info['id'] if creator_info else None
    except Exception:
        pass

    # Resolve project — try project_name_extracted first, then task_name as fallback
    project_query = entities.get("project_name_extracted") or entities.get("project_name") or entities.get("task_name")
    match = resolve_project(project_query, projects) if project_query else None
    
    if not match and context.get("active_project_id"):
        match = next((p for p in projects if p['id'] == context["active_project_id"]), None)

    # Extract task name for direct creation (voice notes provide everything at once)
    # task_name from entities comes from LLM's task_reference field
    task_name_for_creation = entities.get("task_name")
    deadline_raw = entities.get("deadline")

    # Safety: if task_name equals the project name, it's not actually a task name
    if (task_name_for_creation and match and
            task_name_for_creation.strip().lower() == match['name'].strip().lower()):
        task_name_for_creation = None

    # Resolve assignee if provided
    assignee_name = entities.get("assigned_to")
    assigned_to_db_id = None
    if assignee_name:
        assignee_info = get_user_by_name(assignee_name)
        if assignee_info:
            assigned_to_db_id = assignee_info['id']

    # DIRECT CREATION: if we have project + task name, skip the multi-step flow
    # For personal tasks, we don't need a project match
    is_personal = entities.get("is_personal", False)
    
    if (match or is_personal) and task_name_for_creation:
        parsed_deadline = parse_human_date(deadline_raw) if deadline_raw else None

        try:
            from db import add_task
            project_id = match['id'] if match else None
            
            # Use 'Personal' project if it exists for personal tasks, else None
            if is_personal and not project_id:
                personal_proj = next((p for p in projects if p['name'].lower() == "personal"), None)
                if personal_proj:
                    project_id = personal_proj['id']
            
            result = add_task(
                project_id,
                task_name_for_creation,
                parsed_deadline,
                assigned_by=creator_db_id,
                assigned_to=assigned_to_db_id if assigned_to_db_id else (creator_db_id if is_personal else None),
                task_type="PERSONAL" if is_personal else "PROJECT"
            )
        except Exception as e:
            import logging
            logging.error(f"Direct task creation error: {e}")
            result = None

        if result:
            from core.utils import format_date_human
            f_dl = format_date_human(parsed_deadline) if parsed_deadline else "Not set"
            
            # Format custom messages based on personal or assigned status
            if is_personal:
                msg_body = f"✅ Personal reminder created successfully!\n📌 Task: {task_name_for_creation}\n📅 Deadline: {f_dl}"
            else:
                assigned_text = f"\n👤 Assigned to: {assignee_name}" if assignee_name else ""
                project_name = match['name'] if match else "None"
                msg_body = (
                    f"✅ Task created successfully!\n"
                    f"📌 Task: {task_name_for_creation}\n"
                    f"📂 Project: {project_name}{assigned_text}\n"
                    f"📅 Deadline: {f_dl}"
                )
            
            await send_reply_func(msg_body)

            # Trigger WA task assignment if creator is Kanav
            try:
                from core.update_engine import _trigger_wa_task_assignment
                _trigger_wa_task_assignment(
                    task_id=result['id'],
                    task_name=task_name_for_creation,
                    project_name=match['name'],
                    due_date=f_dl,
                    creator_telegram_id=user_id,
                    creator_db_id=creator_db_id,
                )
            except Exception as wa_err:
                import logging
                logging.error(f"WA task assignment trigger error: {wa_err}")
        else:
            await send_reply_func(
                f"Couldn't save '{task_name_for_creation}' — please try again.\n"
                f"Try: 'create task' to start over"
            )
        return

    # MULTI-STEP FALLBACK: ask for missing info step by step
    if match:
        set_state(user_id, {"action": "create_task", "step": "waiting_for_task_name",
                            "project_query": match['name'], "creator_user_id": creator_db_id})
        await send_reply_func("enter task name")
    else:
        msg = "What type of task do you want to create?\n\n1. Personal Task\n2. Team Task"
        set_state(user_id, {"action": "create_task", "step": "waiting_for_task_type",
                            "creator_user_id": creator_db_id})
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
    u_info = _resolve_user(user_id)
    name = u_info['name'] if u_info else "there"
    role = u_info['role'] if u_info else "normal"
    
    msg = f"Hi {name}, What can I help you with?\n\n🤖 Available Commands:\n"
    if role == 'director':
        msg += "• /get_report\n• /get_task\n• /create_task\n• /create_project\n• /update_date\n• /edit_date\n• /create_note\n• /ask_asif\n• /help"
    else:
        msg += "• /update_task\n• /update_date\n• /raise_ticket\n• /edit_date\n• /create_note\n• /create_task\n• /help"
    
    await send_reply_func(msg)

async def handle_edit_date(entities, user_id, context, send_reply_func):
    projects = get_projects()
    if not projects:
        await send_reply_func("No projects exist.")
        return
    msg = "Select Project to edit task date: (Type the number)\n\n"
    # Ensure consistent order (Requirement 1)
    for i, p in enumerate(projects, 1):
        msg += f"{i}. {p['name']}\n"
    set_state(user_id, {"action": "edit_date", "step": "waiting_for_project"})
    await send_reply_func(msg)

async def handle_create_note(entities, user_id, context, send_reply_func):
    projects = get_projects()
    if not projects:
        await send_reply_func("No projects exist.")
        return
    msg = "Select Project to add a note: (Type the number)\n\n"
    # Ensure consistent order (Requirement 1)
    for i, p in enumerate(projects, 1):
        msg += f"{i}. {p['name']}\n"
    set_state(user_id, {"action": "create_note", "step": "waiting_for_project"})
    await send_reply_func(msg)

async def handle_clarify(entities, user_id, context, send_reply_func):
    # Get original user message for language detection
    user_msg = ""
    msgs = context.get("messages", []) if context else []
    if msgs:
        user_msg = str(msgs[-1]) if msgs else ""

    set_state(user_id, {"action": "clarify", "step": "waiting_for_choice"})
    msg = (
        friendly_clarify(user_msg) + "\n\n"
        "Or pick what you'd like to do:\n"
        "1. Update task progress\n"
        "2. Add a blocker\n"
        "3. Complete a task\n"
        "4. Show your tasks\n"
    )
    await send_reply_func(msg)

# --- Helper Performers ---

async def perform_update(task_query, progress_str, user_id, send_reply_func, images=None, deadline=None, note=None):
    ctx = get_context(user_id)
    last_list = ctx.get('last_task_list', [])
    active_project_id = ctx.get('active_project_id')
    tasks = get_all_tasks()
    match = resolve_task_from_list(task_query, tasks, last_list_ids=last_list, active_project_id=active_project_id)
    
    # Check for ambiguous matches — ask user to choose
    if not match and resolve_task_from_list.ambiguous_matches:
        amb = resolve_task_from_list.ambiguous_matches
        msg = f"Multiple tasks match *\"{task_query}\"*. Which one?\n\n"
        for i, t in enumerate(amb, 1):
            p_name = t.get('projects', {}).get('name', '') if isinstance(t.get('projects'), dict) else ''
            msg += f"{i}. {t['name']}" + (f" ({p_name})" if p_name else "") + "\n"
        msg += "\nReply with the number."
        
        # Save state so the next message resolves the choice
        set_state(user_id, {
            "action": "disambiguate_update",
            "step": "waiting_for_choice",
            "task_options": [t['id'] for t in amb],
            "task_names": [t['name'] for t in amb],
            "progress_str": str(progress_str) if progress_str is not None else None,
            "images": images or [],
            "deadline": deadline,
        })
        await send_reply_func(msg)
        return

    if not match:
        await send_reply_func(friendly_task_not_found(str(task_query)))
        return

    # Check building access for update permission
    u_info = _resolve_user(user_id)
    emp_uuid = u_info['id'] if u_info else None
    if emp_uuid:
        from db import check_building_access
        if not check_building_access(emp_uuid, match['id']):
            await send_reply_func("🚫 Unauthorized: You do not have permission to update tasks from this building.")
            return

    try:
        if progress_str is not None:
            import re
            m = re.search(r'(\d+)', str(progress_str))
            if m:
                progress = int(m.group(1))
            else:
                import random
                progress = random.randint(10, 35)
        else:
            import random
            progress = random.randint(10, 35)
    except:
        import random
        progress = random.randint(10, 35)
        
    u_info = _resolve_user(user_id)
    emp_uuid = u_info['id'] if u_info else None
    
    save_update(match['id'], progress, "None", images or [], emp_uuid, new_deadline=deadline, note=note)
    
    # Update Context
    update_context(user_id, task_id=match['id'], task_name=match['name'], last_command="update_task")
    
    # Set state for potential follow-up note
    set_state(user_id, {
        "action": "task_update_note", 
        "step": "waiting_for_note",
        "task_id": match['id'], 
        "task_name": match['name'],
        "initial_note": note
    })
    
    dl_msg = f"\nDeadline: {deadline}" if deadline else ""
    proof_msg = f"\nProof: [Image]" if images else ""
    note_msg = f"\nNote: {note}" if note else ""
    await send_reply_func(
        f"Update saved ✅\nTask: {match['name']}\nProgress: {progress}%{dl_msg}{note_msg}{proof_msg}\n\n"
        f"Would you like to add any additional notes or comments for this task update? 📝\n"
        f"Reply with your comment, or type **No** to complete."
    )

async def perform_add_blocker(task_query, description, user_id, send_reply_func, images=None):
    ctx = get_context(user_id)
    last_list = ctx.get('last_task_list', [])
    active_project_id = ctx.get('active_project_id')
    tasks = get_all_tasks()
    match = resolve_task_from_list(task_query, tasks, last_list_ids=last_list, active_project_id=active_project_id)
    
    # Check for ambiguous matches — ask user to choose
    if not match and resolve_task_from_list.ambiguous_matches:
        amb = resolve_task_from_list.ambiguous_matches
        msg = f"Multiple tasks match *\"{task_query}\"*. Which one?\n\n"
        for i, t in enumerate(amb, 1):
            p_name = t.get('projects', {}).get('name', '') if isinstance(t.get('projects'), dict) else ''
            msg += f"{i}. {t['name']}" + (f" ({p_name})" if p_name else "") + "\n"
        msg += "\nReply with the number."
        
        set_state(user_id, {
            "action": "disambiguate_blocker",
            "step": "waiting_for_choice",
            "task_options": [t['id'] for t in amb],
            "task_names": [t['name'] for t in amb],
            "description": description,
            "images": images or [],
        })
        await send_reply_func(msg)
        return

    if not match:
        await send_reply_func(friendly_task_not_found(str(task_query)))
        return

    add_blocker(match['id'], description)
    
    # Also log an update in history
    u_info = _resolve_user(user_id)
    save_update(match['id'], match.get('progress', 0), description, images or [], u_info['id'] if u_info else None)
    
    # Update Context
    update_context(user_id, task_id=match['id'], task_name=match['name'], last_command="add_blocker")
    
    await send_reply_func(f"Blocker added successfully 🛑\nTask: {match['name']}\nIssue: {description}")

async def perform_add_image(task_query, user_id, send_reply_func, images=None):
    ctx = get_context(user_id)
    last_list = ctx.get('last_task_list', [])
    active_project_id = ctx.get('active_project_id')
    tasks = get_all_tasks()
    match = resolve_task_from_list(task_query, tasks, last_list_ids=last_list, active_project_id=active_project_id)
    
    if not match:
        await send_reply_func(friendly_task_not_found(str(task_query)))
        return

    if not images:
        await send_reply_func("No image was provided. Upload canceled.")
        return

    update_task_image(match['id'], images)
    
    # Update Context
    update_context(user_id, task_id=match['id'], task_name=match['name'], last_command="add_image")
    from core.conversation_state import clear_state
    clear_state(user_id)
    
    await send_reply_func(f"Image added and updated successfully for '{match['name']}'. 🖼️")


async def perform_remove_blocker(task_query, user_id, send_reply_func):

    
    ctx = get_context(user_id)
    last_list = ctx.get('last_task_list', [])
    tasks = get_all_tasks()
    match = resolve_task_from_list(task_query, tasks, last_list_ids=last_list)
        
    if not match:
        await send_reply_func(friendly_task_not_found(str(task_query)))
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
