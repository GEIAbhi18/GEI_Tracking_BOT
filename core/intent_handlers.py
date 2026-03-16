import logging
import json
from db import (
    get_all_tasks, save_update, create_ticket, get_user_by_telegram_id, 
    get_projects, complete_task, add_blocker, get_tasks_for_user, get_task_blockers
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
        tasks = get_all_tasks()
        open_tasks = [t for t in tasks if t.get('status') != 'completed']
        tasks_msg = "\n".join([f"- {t['name']} ({t['projects']['name']})" for t in open_tasks])
        set_state(user_id, {"action": "complete_task", "step": "waiting_for_task"})
        await send_reply_func(f"Which task did you complete?\n\n{tasks_msg}")
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
    if u_info:
        tasks = get_tasks_for_user(u_info['id'])
    else:
        tasks = get_all_tasks()
        
    if not tasks:
        await send_reply_func("No tasks found.")
        return
        
    msg = "📋 *Task List:*\n"
    for t in tasks:
        status_icon = "✅" if t.get('status') == 'completed' else "⏳"
        msg += f"{status_icon} *{t['name']}*\n   Progress: {t.get('progress', 0)}%\n"
    
    await send_reply_func(msg)

async def handle_query_blockers(entities, user_id, context, send_reply_func):
    tasks = get_all_tasks()
    blocked_tasks = [t for t in tasks if t.get('is_blocked')]
    
    if not blocked_tasks:
        await send_reply_func("No blocked tasks found. Everything is on track! 🟢")
        return
        
    msg = "🛑 *Current Blockers:*\n"
    for t in blocked_tasks:
        msg += f"- *{t['name']}*: {t.get('blocker_reason', 'Unknown reason')}\n"
    
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
