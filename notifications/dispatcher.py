import logging
from db import supabase
from notifications.templates import get_notification_template
from datetime import datetime

logger = logging.getLogger(__name__)

def queue_notification(user_id: str, task_id: str, event_type: str, context: dict):
    """
    Evaluates rules and queues a notification if applicable.
    """
    # Build the message from the template
    message = get_notification_template(event_type, context)
    
    data = {
        "user_id": user_id,
        "task_id": task_id,
        "event_type": event_type,
        "message": message,
        "status": "Pending",
        "retry_count": 0
    }
    
    try:
        supabase.table("notifications").insert(data).execute()
        logger.info(f"Queued notification for user {user_id}, event: {event_type}")
    except Exception as e:
        logger.error(f"Failed to queue notification: {e}")

def dispatch_task_event(task_id: str, event_type: str):
    """
    Fetches task details and queues notifications based on the rules.
    Rules:
    - Task creator receives updates only for tasks they created.
    - Assigned To user receives assignment notifications.
    """
    try:
        # Fetch task details including related users and projects
        task_res = supabase.table("tasks").select(
            "*, projects(name), created_by_user:users!created_by(id, name), assigned_to_user:users!assigned_to(id, name)"
        ).eq("id", task_id).execute()
        
        if not task_res.data:
            logger.error(f"Task {task_id} not found for dispatching event {event_type}")
            return
            
        task = task_res.data[0]
        
        creator_id = task.get("created_by")
        assignee_id = task.get("assigned_to")
        
        creator = task.get("created_by_user", {})
        assignee = task.get("assigned_to_user", {})
        project = task.get("projects", {})
        
        context = {
            "task_title": task.get("title", ""),
            "project_name": project.get("name", "") if project else "",
            "creator_name": creator.get("name", "Creator") if creator else "Creator",
            "assignee_name": assignee.get("name", "Assignee") if assignee else "Assignee",
            "due_date": task.get("due_date", "No date")
        }
        
        # Rule Evaluation
        # 1. Assignment
        if event_type == "Assigned" and assignee_id:
            queue_notification(assignee_id, task_id, event_type, context)
            
        # 2. Updates for Creator
        if event_type in ["Accepted", "Started", "Completed", "Closed", "Follow-up Created"]:
            if creator_id and creator_id != assignee_id:
                queue_notification(creator_id, task_id, event_type, context)
                
        # 3. Reminders and Overdue
        if event_type in ["Reminder", "Overdue"] and assignee_id:
            queue_notification(assignee_id, task_id, event_type, context)

    except Exception as e:
        logger.error(f"Error dispatching task event {event_type} for task {task_id}: {e}")
