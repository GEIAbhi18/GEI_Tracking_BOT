import logging
from core.message_parser import parse_message
from db import get_projects, get_all_tasks, get_user_by_telegram_id, save_update

logger = logging.getLogger(__name__)

async def process_update_message(text: str, user_id: int, images: list, send_reply_func):
    parsed = parse_message(text)
    
    if parsed["confidence"] == "low":
        await send_reply_func(
            "Update samajh nahi aaya.\n"
            "Please send in format:\n"
            "Project name + task + % + blocker.\n"
            "Example:\n"
            "Top Terrace waterproofing 40% material delay"
        )
        return

    # We match it to the DB project and task
    project_name = parsed["project"]
    task_keyword = parsed["task_keyword"]
    
    # We know confidence is high or medium, so we have task_keyword and progress
    projects = get_projects()
    tasks = get_all_tasks()
    
    # Resolve project_id if possible
    project_id = None
    if project_name:
        for p in projects:
            if p['name'].lower() == project_name.lower():
                project_id = p['id']
                break
                
    task_id = None
    resolved_task_name = "Unknown Task"
    resolved_project_name = project_name or "Unknown Project"

    # resolve task ID from keyword and project
    for t in tasks:
        # if we know project ID, only search within that project
        if project_id and t['project_id'] != project_id:
            continue
            
        if task_keyword.lower() in t['name'].lower():
            task_id = t['id']
            resolved_task_name = t['name']
            if not project_id:
                # auto-resolve project
                for p in projects:
                    if p['id'] == t['project_id']:
                        project_id = p['id']
                        resolved_project_name = p['name']
                        break
            break

    if not task_id:
        # Fallback if somehow not strictly matched
        await send_reply_func(
            "Could not exactly match your task in the database.\n"
            "Please ensure you mention correct task details."
        )
        return
        
    u_info = get_user_by_telegram_id(user_id)
    emp_uuid = u_info['id'] if u_info else None
    
    assigned_blocker = parsed["blocker"] or "None"
        
    # save update
    save_update(task_id, parsed["progress"], assigned_blocker, images, emp_uuid)

    await send_reply_func(
        f"Update saved ✅\n"
        f"Project: {resolved_project_name}\n"
        f"Task: {resolved_task_name}\n"
        f"Progress: {parsed['progress']}%\n"
        f"Blocker: {assigned_blocker}"
    )
