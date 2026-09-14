from __future__ import annotations
import time
import logging
from datetime import datetime, timezone
from db import supabase
from elara.config import DEPARTMENT_COLORS

logger = logging.getLogger(__name__)


# ── Projects ─────────────────────────────────────────────────────────────────

def get_projects(department: str | None = None) -> list:
    """Fetch projects from elara_projects, optionally filtered by department."""
    try:
        query = supabase.table("elara_projects").select("*").order("created_at")
        if department:
            query = query.eq("department", department)
        res = query.execute()
        return res.data or []
    except Exception as e:
        logger.error(f"get_projects failed: {e}")
        return []


def get_project_by_id(project_id: str) -> dict | None:
    """Get an Elara project by ID."""
    try:
        res = supabase.table("elara_projects").select("*").eq("id", project_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.error(f"get_project_by_id failed for {project_id}: {e}")
        return None


def create_project(name: str, department: str, description: str | None = None, color: str | None = None) -> dict:
    """
    Create a project in `elara_projects`.
    DO NOT write to legacy `projects` table.
    """
    proj_id = f"elara-proj-{int(time.time() * 1000)}"
    now_iso = datetime.now(timezone.utc).isoformat()
    proj_color = color or DEPARTMENT_COLORS.get(department, "#3b82f6")

    data = {
        "id": proj_id,
        "name": name.strip(),
        "department": department.strip(),
        "description": description.strip() if description else f"Department: {department}",
        "color": proj_color,
        "status": "Active",
        "team_name": "Elara Home",
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    res = supabase.table("elara_projects").insert(data).execute()
    if isinstance(res.data, list) and len(res.data) > 0 and isinstance(res.data[0], dict):
        return res.data[0]
    return data


# ── Tasks ────────────────────────────────────────────────────────────────────

def get_tasks(project_id: str | None = None, department: str | None = None, assigned_user: str | None = None, status: str | None = None) -> list:
    """
    Fetch tasks from `elara_tasks`.
    Optionally filter by project_id, department, assigned_user, or status.
    """
    try:
        query = supabase.table("elara_tasks").select("*").order("created_at", desc=True)

        if project_id:
            query = query.eq("project_id", project_id)
        if status:
            query = query.eq("status", status.lower())

        res = query.execute()
        tasks = res.data or []

        # If department filter is needed, filter by matching projects
        if department:
            dept_projects = get_projects(department)
            dept_proj_ids = {p["id"] for p in dept_projects}
            tasks = [t for t in tasks if t.get("project_id") in dept_proj_ids]

        # If assigned_user filter is needed (matches name in assigned_users text[])
        if assigned_user:
            norm_target = assigned_user.strip().lower()
            tasks = [
                t for t in tasks
                if any(norm_target in str(u).lower() for u in (t.get("assigned_users") or []))
            ]

        return tasks
    except Exception as e:
        logger.error(f"get_tasks failed: {e}")
        return []


def get_task_by_id(task_id: str) -> dict | None:
    """Get a task by ID from `elara_tasks`."""
    try:
        res = supabase.table("elara_tasks").select("*").eq("id", task_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.error(f"get_task_by_id failed for {task_id}: {e}")
        return None


def create_task(title: str, project_id: str, description: str | None = None, priority: str = "medium",
                due_date: str | None = None, assigned_users: list | None = None, status: str = "pending") -> dict:
    """
    Create a new task in `elara_tasks`.
    DO NOT write to legacy `tasks` table.
    """
    task_id = f"task-{int(time.time() * 1000)}"
    now_iso = datetime.now(timezone.utc).isoformat()
    assignees = assigned_users if assigned_users else ["Developer"]

    data = {
        "id": task_id,
        "project_id": project_id,
        "title": title.strip(),
        "description": description.strip() if description else None,
        "status": status.lower() if status else "pending",
        "priority": priority.lower() if priority else "medium",
        "progress": 0,
        "assigned_users": assignees,
        "due_date": due_date,
        "is_blocked": (status == "blocker"),
        "comments": [],
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    res = supabase.table("elara_tasks").insert(data).execute()
    if isinstance(res.data, list) and len(res.data) > 0 and isinstance(res.data[0], dict):
        return res.data[0]
    return data


def update_task(task_id: str, updates: dict) -> dict | None:
    """
    Update an existing task in `elara_tasks`.
    """
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {k: v for k, v in updates.items()}
        payload["updated_at"] = now_iso

        # If completed, set completion date and 100% progress
        if payload.get("status") == "completed":
            payload["actual_completion_date"] = now_iso
            payload["progress"] = 100
        elif payload.get("status") == "blocker":
            payload["is_blocked"] = True
        elif "status" in payload and payload.get("status") != "blocker":
            payload["is_blocked"] = False

        res = supabase.table("elara_tasks").update(payload).eq("id", task_id).execute()
        if isinstance(res.data, list) and len(res.data) > 0 and isinstance(res.data[0], dict):
            return res.data[0]
        return {"id": task_id, **payload}
    except Exception as e:
        logger.error(f"update_task failed for {task_id}: {e}")
        return None


# ── Comments ─────────────────────────────────────────────────────────────────

def add_comment(task_id: str, user_name: str, user_role: str = "Team Member", content: str = "") -> dict:
    """
    Add a comment to an Elara Home task.
    1. Writes to `elara_comments` table (one row per comment, never overwrites).
    2. Also appends to `elara_tasks.comments` JSONB array for immediate Kanban sync.
    """
    comment_id = f"cmt-{int(time.time() * 1000)}"
    now_iso = datetime.now(timezone.utc).isoformat()

    comment_row = {
        "id": comment_id,
        "task_id": task_id,
        "user_name": user_name,
        "user_role": user_role,
        "user_avatar": None,
        "content": content.strip(),
        "created_at": now_iso,
    }

    # 1. Insert into dedicated elara_comments table
    res = supabase.table("elara_comments").insert(comment_row).execute()
    created_comment = res.data[0] if (isinstance(res.data, list) and len(res.data) > 0 and isinstance(res.data[0], dict)) else comment_row

    # 2. Append to elara_tasks comments JSONB array for instant Kanban UI sync
    try:
        task = get_task_by_id(task_id)
        if task:
            existing_comments = task.get("comments") or []
            if not isinstance(existing_comments, list):
                existing_comments = []
            updated_comments = existing_comments + [created_comment]
            supabase.table("elara_tasks").update({
                "comments": updated_comments,
                "updated_at": now_iso
            }).eq("id", task_id).execute()
    except Exception as sync_err:
        logger.warning(f"Failed to sync comment into elara_tasks JSONB: {sync_err}")

    return created_comment


def get_comments(task_id: str) -> list:
    """Retrieve all comments for a specific task from `elara_comments`."""
    try:
        res = supabase.table("elara_comments").select("*").eq("task_id", task_id).order("created_at").execute()
        return res.data or []
    except Exception as e:
        logger.error(f"get_comments failed for {task_id}: {e}")
        return []
