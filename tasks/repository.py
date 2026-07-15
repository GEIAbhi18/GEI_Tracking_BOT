import logging
from db import supabase

logger = logging.getLogger(__name__)

def create_task(data: dict):
    try:
        response = supabase.table("tasks").insert(data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        raise

def get_task_by_id(task_id: str):
    try:
        response = supabase.table("tasks").select("*, teams(name), users!tasks_created_by_fkey(name), users!tasks_assigned_to_fkey(name)").eq("id", task_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error fetching task {task_id}: {e}")
        raise

def get_tasks_by_team(team_id: str):
    try:
        response = supabase.table("tasks").select("*").eq("team_id", team_id).order("created_at", desc=True).execute()
        return response.data
    except Exception as e:
        logger.error(f"Error fetching tasks for team {team_id}: {e}")
        raise

def update_task(task_id: str, data: dict):
    try:
        response = supabase.table("tasks").update(data).eq("id", task_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error updating task {task_id}: {e}")
        raise

def delete_task(task_id: str):
    try:
        response = supabase.table("tasks").delete().eq("id", task_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error deleting task {task_id}: {e}")
        raise
