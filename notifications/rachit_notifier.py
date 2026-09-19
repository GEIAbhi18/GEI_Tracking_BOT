"""
Notifications module for notifying Rachit of changes to Elara Home tasks.
Provides dedicated notification dispatch for Rachit as an Elara Home team member.
"""

from __future__ import annotations
import os
import sys
import logging
from datetime import datetime
from whatsapp.ux import send_text
from notifications.kanav_notifier import format_task_change_message, get_formatted_timestamp

logger = logging.getLogger(__name__)


def get_rachit_phone() -> str:
    """Resolve Rachit's WhatsApp phone number from the database with fallback."""
    from elara.config import RACHIT_PHONE, DEVELOPER_PHONE

    # While testing, use Developer's number (917717754421) so Rachit never gets test messages
    if (
        os.getenv("TESTING") in ("1", "true", "True")
        or "pytest" in sys.modules
        or os.getenv("PYTEST_CURRENT_TEST") is not None
        or any("test" in arg.lower() for arg in sys.argv)
    ):
        return DEVELOPER_PHONE

    try:
        from db import supabase
        # Check elara_users first
        res = supabase.table("elara_users").select("phone").ilike("name", "%Rachit%").execute()
        if hasattr(res, "data") and isinstance(res.data, list) and len(res.data) > 0:
            first = res.data[0]
            if isinstance(first, dict):
                wa = first.get("phone")
                if isinstance(wa, str) and wa.strip():
                    return wa.strip()

        # Check users table fallback
        res2 = supabase.table("users").select("whatsapp_number").ilike("name", "%Rachit%").execute()
        if hasattr(res2, "data") and isinstance(res2.data, list) and len(res2.data) > 0:
            first2 = res2.data[0]
            if isinstance(first2, dict):
                wa = first2.get("whatsapp_number")
                if isinstance(wa, str) and wa.strip():
                    return wa.strip()
    except Exception as e:
        logger.warning(f"Could not fetch Rachit WhatsApp from database: {e}")

    return RACHIT_PHONE


def notify_rachit_task_change(task_id: str, task_title: str, change_made: str,
                              changed_by: str, domain: str = "Elara Home",
                              timestamp: datetime | str | None = None) -> bool:
    """
    Send Rachit a WhatsApp message regarding an Elara Home task change.
    - Prevents self-notifications if changed_by is Rachit.
    - Only applies to Elara Home tasks.
    - Never raises exceptions, ensuring calling flows are unaffected.
    """
    try:
        # Prevent self-notification / duplicates if Rachit himself made the change
        if changed_by and changed_by.strip().lower() in ("rachit", "rachit gupta"):
            logger.info(f"Skipping notification to Rachit for his own change on task {task_id}")
            return False

        from elara.config import DEVELOPER_PHONE
        is_test_task = (
            os.getenv("TESTING") in ("1", "true", "True")
            or "pytest" in sys.modules
            or os.getenv("PYTEST_CURRENT_TEST") is not None
            or any("test" in arg.lower() for arg in sys.argv)
            # pyrefly: ignore [unnecessary-type-conversion]
            or "test" in str(task_id).lower()
            # pyrefly: ignore [unnecessary-type-conversion]
            or "test" in str(task_title).lower()
            # pyrefly: ignore [unnecessary-type-conversion]
            or "test" in str(change_made).lower()
        )
        if is_test_task:
            rachit_wa = DEVELOPER_PHONE
        else:
            rachit_wa = get_rachit_phone()

        ts = timestamp or get_formatted_timestamp()
        message = format_task_change_message(
            task_id=task_id,
            task_title=task_title,
            change_made=change_made,
            changed_by=changed_by,
            timestamp=ts,
            domain=domain,
        )

        sent = send_text(rachit_wa, message)
        logger.info(f"Task change notification sent to Rachit ({rachit_wa}) for {domain} task '{task_id}': {change_made}")
        print(f"[RACHIT_NOTIFICATION] Sent to {rachit_wa} | Task: {task_id} ({task_title}) | Change: {change_made} | By: {changed_by} | Domain: {domain}", flush=True)
        # pyrefly: ignore [unnecessary-type-conversion]
        return bool(sent)
    except Exception as e:
        logger.error(f"Failed to notify Rachit of task change for {task_id}: {e}")
        return False
