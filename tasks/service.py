import logging
from datetime import datetime
from tasks.repository import create_task, update_task, get_task_by_id
from tasks.timeline import add_timeline_event
from tasks.validation import validate_task_creation, validate_status_transition, validate_assignment
from db import supabase

logger = logging.getLogger(__name__)

def orchestrate_task_creation(current_user: dict, data: dict):
    """Orchestrates creating a task and logging the initial timeline event."""
    is_valid, err = validate_task_creation(data)
    if not is_valid:
        raise ValueError(err)
        
    # Build core task object
    new_task = {
        "title": data["title"].strip(),
        "description": data.get("description", ""),
        "task_type": data["task_type"],
        "priority": data.get("priority", "Medium"),
        "status": "Pending",
        "created_by": current_user["id"],
        "team_id": current_user.get("team_id") if data["task_type"] == "TEAM" else None
    }
    
    # Optional fields
    if "due_date" in data: new_task["due_date"] = data["due_date"]
    if "due_time" in data: new_task["due_time"] = data["due_time"]
    if "parent_task_id" in data: new_task["parent_task_id"] = data["parent_task_id"]
    if "attachments" in data: new_task["attachments"] = data["attachments"]
    if "notes" in data: new_task["notes"] = data["notes"]
    
    # Handle initial assignment
    assigned_to = data.get("assigned_to")
    if assigned_to:
        target = supabase.table("users").select("id, team_id").eq("id", assigned_to).execute().data
        if not target: raise ValueError("Assigned user not found.")
        
        can_assign, assign_err = validate_assignment(current_user, target[0])
        if not can_assign: raise ValueError(assign_err)
        
        new_task["assigned_to"] = assigned_to
    
    task = create_task(new_task)
    
    # Log timeline event
    add_timeline_event(
        task_id=task["id"],
        user_id=current_user["id"],
        action="Task Created",
        note=f"Assigned to: {assigned_to}" if assigned_to else "Created as Unassigned"
    )
    
    return task

def orchestrate_status_update(current_user: dict, task_id: str, new_status: str, note: str = None, proof_url: str = None):
    """Handles status changes with strict validation and timeline logging."""
    task = get_task_by_id(task_id)
    if not task:
        raise ValueError("Task not found.")
        
    current_status = task["status"]
    
    if current_status == new_status:
        return task
        
    can_transition, err = validate_status_transition(current_status, new_status)
    if not can_transition:
        raise ValueError(err)
        
    update_data = {
        "status": new_status,
        "updated_by": current_user["id"],
        "updated_at": datetime.utcnow().isoformat()
    }
    
    if new_status == "Completed" and proof_url:
        update_data["completion_proof"] = proof_url
        
    if new_status == "Closed":
        update_data["closed_by"] = current_user["id"]
        update_data["closed_at"] = datetime.utcnow().isoformat()
        
    updated = update_task(task_id, update_data)
    
    # Log timeline event
    add_timeline_event(
        task_id=task_id,
        user_id=current_user["id"],
        action=f"Status changed from {current_status} to {new_status}",
        note=note,
        attachment_url=proof_url
    )
    
    return updated

def orchestrate_task_assignment(current_user: dict, task_id: str, new_assignee_id: str):
    """Reassigns a task to someone else."""
    task = get_task_by_id(task_id)
    if not task: raise ValueError("Task not found.")
    
    target = supabase.table("users").select("id, team_id, name").eq("id", new_assignee_id).execute().data
    if not target: raise ValueError("Assigned user not found.")
    
    can_assign, assign_err = validate_assignment(current_user, target[0])
    if not can_assign: raise ValueError(assign_err)
    
    update_data = {
        "assigned_to": new_assignee_id,
        "updated_by": current_user["id"],
        "updated_at": datetime.utcnow().isoformat()
    }
    
    updated = update_task(task_id, update_data)
    
    add_timeline_event(
        task_id=task_id,
        user_id=current_user["id"],
        action="Task Reassigned",
        note=f"Assigned to {target[0]['name']}"
    )
    
    return updated

def create_followup_task(current_user: dict, parent_task_id: str):
    """Creates a follow-up task based on a closed parent task."""
    parent_task = get_task_by_id(parent_task_id)
    if not parent_task:
        raise ValueError("Parent task not found.")
        
    followup_data = {
        "title": f"Follow-up: {parent_task['title']}",
        "task_type": parent_task.get("task_type", "PERSONAL"),
        "priority": parent_task.get("priority", "Medium"),
        "parent_task_id": parent_task_id
    }
    
    # Inherit assignment if exists
    if parent_task.get("assigned_to"):
        followup_data["assigned_to"] = parent_task["assigned_to"]
        
    return orchestrate_task_creation(current_user, followup_data)

def _validate_personal_task_access(current_user: dict, task: dict):
    if task.get("task_type") != "PERSONAL":
        return True # Handled by team logic elsewhere
    if str(task.get("created_by")) == str(current_user["id"]) or str(task.get("assigned_to")) == str(current_user["id"]):
        return True
    return False

def orchestrate_archive_task(current_user: dict, task_id: str):
    task = get_task_by_id(task_id)
    if not task: raise ValueError("Task not found.")
    if not _validate_personal_task_access(current_user, task):
        raise ValueError("Permission denied.")
    
    from db import archive_task
    return archive_task(task_id)

def orchestrate_restore_task(current_user: dict, task_id: str):
    task = get_task_by_id(task_id)
    if not task: raise ValueError("Task not found.")
    if not _validate_personal_task_access(current_user, task):
        raise ValueError("Permission denied.")
    
    from db import restore_task
    return restore_task(task_id)

def orchestrate_delete_task(current_user: dict, task_id: str):
    task = get_task_by_id(task_id)
    if not task: raise ValueError("Task not found.")
    if not _validate_personal_task_access(current_user, task):
        raise ValueError("Permission denied.")
    
    from db import delete_task
    return delete_task(task_id)

def orchestrate_set_reminder(current_user: dict, task_id: str, reminder_time: str):
    task = get_task_by_id(task_id)
    if not task: raise ValueError("Task not found.")
    if not _validate_personal_task_access(current_user, task):
        raise ValueError("Permission denied.")
    
    from db import set_task_reminder
    return set_task_reminder(task_id, reminder_time)

def orchestrate_bulk_update_tasks(current_user: dict, task_ids: list, update_data: dict):
    from db import bulk_update_tasks
    # validate all
    for tid in task_ids:
        t = get_task_by_id(tid)
        if not t or not _validate_personal_task_access(current_user, t):
            raise ValueError(f"Permission denied or task {tid} not found.")
            
    return bulk_update_tasks(task_ids, update_data)

