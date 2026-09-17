"""
Notifications module for notifying Kanav of changes to tasks he created.
Supports both Facilities and Elara Home tasks.
"""

from __future__ import annotations
import os
import logging
from datetime import datetime, timezone, timedelta
from whatsapp.ux import send_text

# Standard Indian Standard Time (UTC+5:30) compatible across Python versions
IST = timezone(timedelta(hours=5, minutes=30), name="IST")

logger = logging.getLogger(__name__)


def get_kanav_phone() -> str:
    """Resolve Kanav's WhatsApp phone number from the database with fallback."""
    from elara.config import KANAV_PHONE
    try:
        from db import supabase
        res = supabase.table("users").select("whatsapp_number").ilike("name", "%Kanav%").execute()
        if hasattr(res, "data") and isinstance(res.data, list) and len(res.data) > 0:
            first = res.data[0]
            if isinstance(first, dict):
                wa = first.get("whatsapp_number")
                if isinstance(wa, str) and wa.strip():
                    return wa.strip()
    except Exception as e:
        logger.warning(f"Could not fetch Kanav WhatsApp from users table: {e}")
    return KANAV_PHONE


def get_formatted_timestamp(dt: datetime | None = None) -> str:
    """Format current or given timestamp in a human-readable format (IST preferred)."""
    if not dt:
        dt = datetime.now(IST)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    else:
        dt = dt.astimezone(IST)
    return dt.strftime("%d %b %Y, %I:%M %p IST").strip()


def format_task_change_message(task_id: str, task_title: str, change_made: str,
                               changed_by: str, timestamp: datetime | str | None = None,
                               domain: str = "Facilities") -> str:
    """
    Format a standardized task-change notification WhatsApp message.
    """
    if isinstance(timestamp, str):
        time_str = timestamp
    elif isinstance(timestamp, datetime):
        time_str = get_formatted_timestamp(timestamp)
    else:
        time_str = get_formatted_timestamp()

    domain_emoji = "🏢" if domain.lower() == "facilities" else "🏠"

    return (
        f"🔔 *Task Update Notification*\n\n"
        f"📋 *Task ID:* {task_id}\n"
        f"📌 *Task Title:* {task_title}\n"
        f"🔄 *Change Made:* {change_made}\n"
        f"👤 *Changed By:* {changed_by}\n"
        f"🕒 *Timestamp:* {time_str}\n"
        f"{domain_emoji} *Domain:* {domain}"
    )


def is_facilities_task_created_by_kanav(task_row: dict) -> bool:
    """
    Determine if a Facilities task was created/added by Kanav.
    Evaluates:
      - added_by (e.g. 'Facilities Director', 'Kanav')
      - last_modified_by_at (Column E in row_cache, e.g. 'Facilities Director / 2026-08-31 09:40 UTC')
      - created_by / actor
    """
    if not task_row:
        return False

    candidates = [
        task_row.get("added_by"),
        task_row.get("last_modified_by_at"),
        task_row.get("created_by"),
        task_row.get("actor")
    ]
    for c in candidates:
        if not c or not isinstance(c, str):
            continue
        c_str = c.lower()
        if any(k in c_str for k in ["facilities director", "facility director", "kanav", "director"]):
            return True
    return False


def is_elara_task_created_by_kanav(task: dict) -> bool:
    """
    Determine if an Elara Home task was created/added by Kanav.
    Evaluates:
      - task.get('created_by')
      - comments in task.get('comments')
      - query elara_comments table for task_id (fallback)
    """
    if not task:
        return False

    # 1. Direct created_by field
    cb = task.get("created_by")
    if cb and isinstance(cb, str):
        cb_lower = cb.lower()
        if any(k in cb_lower for k in ["kanav", "kk"]):
            return True
        return False

    # 2. In-memory comments array
    comments = task.get("comments")
    if isinstance(comments, list):
        for c in comments:
            if isinstance(c, dict):
                uname = str(c.get("user_name", "")).lower()
                content = str(c.get("content", "")).lower()
                if "task created by" in content:
                    if any(k in content for k in ["kanav", "kk"]) or any(k in uname for k in ["kanav", "kk"]):
                        return True
                    return False
                if uname in ("kanav", "kk") and "created" in content:
                    return True
        if len(comments) > 0:
            return False

    # 3. Database elara_comments check (only fallback if comments not loaded on task)
    task_id = task.get("id")
    if task_id:
        try:
            from db import supabase
            res = supabase.table("elara_comments").select("id, content").eq("task_id", task_id).ilike("content", "%Task created by%Kanav%").execute()
            if hasattr(res, "data") and isinstance(res.data, list) and len(res.data) > 0:
                first = res.data[0]
                if isinstance(first, dict) and first.get("id"):
                    return True
            res2 = supabase.table("elara_comments").select("id, content").eq("task_id", task_id).ilike("content", "%Task created by%KK%").execute()
            if hasattr(res2, "data") and isinstance(res2.data, list) and len(res2.data) > 0:
                first2 = res2.data[0]
                if isinstance(first2, dict) and first2.get("id"):
                    return True
        except Exception:
            pass

    return False


def notify_kanav_task_change(task_id: str, task_title: str, change_made: str,
                             changed_by: str, domain: str = "Facilities",
                             timestamp: datetime | None = None) -> bool:
    """
    Send Kanav a WhatsApp message regarding a task change.
    Never raises exceptions, ensuring calling flows are unaffected.
    """
    try:
        kanav_wa = get_kanav_phone()
        ts = timestamp or get_formatted_timestamp()
        message = format_task_change_message(
            task_id=task_id,
            task_title=task_title,
            change_made=change_made,
            changed_by=changed_by,
            timestamp=ts,
            domain=domain
        )

        sent = send_text(kanav_wa, message)
        logger.info(f"Task change notification sent to Kanav ({kanav_wa}) for {domain} task '{task_id}': {change_made}")
        print(f"[KANAV_NOTIFICATION] Sent to {kanav_wa} | Task: {task_id} ({task_title}) | Change: {change_made} | By: {changed_by} | Domain: {domain}", flush=True)
        # pyrefly: ignore [unnecessary-type-conversion]
        return bool(sent)
    except Exception as e:
        logger.error(f"Failed to notify Kanav of task change for {task_id}: {e}")
        return False
