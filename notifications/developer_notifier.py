"""
Notifications module for notifying Developer (Abhijeet) of Facilities
Google Sheet changes.

Provides a dedicated notification function for Facilities external
changes so that the Developer always receives updates alongside Anoop
and Kanav.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime

from whatsapp.ux import send_text
from notifications.kanav_notifier import format_task_change_message, get_formatted_timestamp

logger = logging.getLogger(__name__)


def get_developer_phone() -> str:
    """Resolve the Developer's WhatsApp phone number."""
    from elara.config import DEVELOPER_PHONE
    return DEVELOPER_PHONE


def notify_developer_facilities_change(
    ref_no: str,
    task_title: str,
    change_desc: str,
    changed_by: str,
    timestamp: datetime | str | None = None,
) -> bool:
    """
    Send the Developer a WhatsApp message regarding a Facilities
    Google Sheet change.

    Never raises exceptions, ensuring calling flows are unaffected.
    """
    try:
        developer_wa = get_developer_phone()

        ts = timestamp or get_formatted_timestamp()
        message = format_task_change_message(
            task_id=ref_no,
            task_title=task_title,
            change_made=change_desc,
            changed_by=changed_by,
            timestamp=ts,
            domain="Facilities",
        )

        sent = send_text(developer_wa, message)
        logger.info(
            f"Facilities change notification sent to Developer ({developer_wa}) "
            f"for {ref_no}: {change_desc}"
        )
        print(
            f"[DEVELOPER_NOTIFICATION] Sent to {developer_wa} | "
            f"Task: {ref_no} ({task_title}) | "
            f"Change: {change_desc} | By: {changed_by} | Domain: Facilities",
            flush=True,
        )
        # pyrefly: ignore [unnecessary-type-conversion]
        return bool(sent)
    except Exception as e:
        logger.error(f"Failed to notify Developer of facilities change for {ref_no}: {e}")
        return False
