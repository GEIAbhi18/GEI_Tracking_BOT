import logging
from db import supabase

logger = logging.getLogger(__name__)

def add_timeline_event(task_id: str, user_id: str, action: str, note: str = None, attachment_url: str = None):
    """Logs an event in the task's timeline."""
    try:
        data = {
            "task_id": task_id,
            "user_id": user_id,
            "action": action
        }
        if note:
            data["note"] = note
        if attachment_url:
            data["attachment_url"] = attachment_url
            
        response = supabase.table("task_timeline").insert(data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error adding timeline event to task {task_id}: {e}")
        # Non-critical, we don't strictly raise here to avoid failing the main transaction
        return None

def get_task_timeline(task_id: str):
    """Retrieves the timeline for a specific task."""
    try:
        response = supabase.table("task_timeline").select("*, users(name)").eq("task_id", task_id).order("created_at").execute()
        return response.data
    except Exception as e:
        logger.error(f"Error fetching timeline for task {task_id}: {e}")
        raise
