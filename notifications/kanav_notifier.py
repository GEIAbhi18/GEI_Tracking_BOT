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
        if res.data and res.data[0].get("whatsapp_number"):
            return res.data[0]["whatsapp_number"]
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
                               changed_by: str, timestamp: str | None = None,
                               domain: str = "Facilities") -> str:
    """
    Format task-change notification message for Kanav.
    Fields included:
      - Task ID
      - Task Title
      - Change Made
      - Changed By
      - Timestamp
      - Domain
    """
    ts = timestamp or get_formatted_timestamp()
    domain_emoji = "🏢" if domain.lower() == "facilities" else "🏠"
    body = (
        f"🔔 *Task Update Notification*\n\n"
        f"📋 *Task ID:* {task_id}\n"
        f"📌 *Task Title:* {task_title}\n"
        f"🔄 *Change Made:* {change_made}\n"
        f"👤 *Changed By:* {changed_by}\n"
        f"🕒 *Timestamp:* {ts}\n"
        f"{domain_emoji} *Domain:* {domain}"
    )
    return body


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
        if not c:
            continue
        c_str = str(c).lower()
        if any(k in c_str for k in ["facilities director", "facility director", "kanav", "director"]):
            return True
    return False


def is_elara_task_created_by_kanav(task: dict) -> bool:
    """
    Determine if an Elara Home task was created/added by Kanav.
    Evaluates:
      - task.get('created_by')
      - comments in task.get('comments')
      - query elara_comments table for task_id
    """
    if not task:
        return False

    # 1. Direct created_by field
    cb = str(task.get("created_by") or "").lower()
    if any(k in cb for k in ["kanav", "kk"]):
        return True

    # 2. In-memory comments array
    comments = task.get("comments") or []
    if isinstance(comments, list):
        for c in comments:
            if isinstance(c, dict):
                uname = str(c.get("user_name", "")).lower()
                content = str(c.get("content", "")).lower()
                if "task created by" in content and ("kanav" in content or "kanav" in uname or "kk" in uname):
                    return True
                if uname in ("kanav", "kk") and "created" in content:
                    return True

    # 3. Database elara_comments check
    task_id = task.get("id")
    if task_id:
        try:
            from db import supabase
            res = supabase.table("elara_comments").select("*").eq("task_id", task_id).ilike("content", "%Task created by%Kanav%").execute()
            if res.data:
                return True
            res2 = supabase.table("elara_comments").select("*").eq("task_id", task_id).ilike("content", "%Task created by%KK%").execute()
            if res2.data:
                return True
        except Exception:
            pass

    return False


def notify_kanav_task_change(task_id: str, task_title: str, change_made: str,
                             changed_by: str, domain: str = "Facilities",
                             timestamp: str | None = None) -> bool:
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
