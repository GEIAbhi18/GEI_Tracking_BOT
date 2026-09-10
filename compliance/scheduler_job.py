"""
Compliance Module — Scheduled Daily Job
========================================
Daily job executed once per day by the background scheduler.
1. Downloads and reads GEBB1, GEBB2, and GETT from the Compliance Sheet.
2. Identifies all items whose "Valid Till / Next Due" date matches today's date.
3. Ensures each item is notified only once per day (duplicate prevention).
4. Dispatches the Meta Utility Template 'compliance_due_reminder' solely to Anoop Sir.
5. Logs all attempts, delivery statuses, and errors.
"""

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pytz

from compliance.config import TIMEZONE
from compliance.notifier import (
    resolve_anoop_phone_number,
    send_compliance_reminder_to_anoop,
)
from compliance.sheets_client import fetch_all_compliance_records
from compliance.tracker import (
    has_reminder_been_sent_today,
    log_reminder_attempt,
)

logger = logging.getLogger(__name__)


def get_current_ist_date() -> date:
    """Get the current calendar date in the configured timezone (Asia/Kolkata)."""
    tz = pytz.timezone(TIMEZONE)
    return datetime.now(tz).date()


def run_compliance_daily_check(
    target_date: Optional[date] = None,
    force_send: bool = False,
    sheet_id: Optional[str] = None,
    records_cache: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Main entrypoint for the compliance daily check.

    Args:
        target_date: Date to compare due dates against. Defaults to today in IST.
        force_send: If True, bypasses the duplicate check (used for testing).
        sheet_id: Optional sheet ID override.
        records_cache: Optional pre-loaded records list (for testing).

    Returns:
        Summary dict of execution results.
    """
    check_date = target_date or get_current_ist_date()
    logger.info(f"🚀 Starting Compliance daily check for date: {check_date.isoformat()} (TZ: {TIMEZONE})")

    summary: Dict[str, Any] = {
        "check_date": check_date.isoformat(),
        "total_checked": 0,
        "due_count": 0,
        "sent_count": 0,
        "skipped_duplicate": 0,
        "failed_count": 0,
        "due_items": [],
        "errors": [],
    }

    # 1. Fetch compliance records
    try:
        if records_cache is not None:
            records = records_cache
        else:
            records = fetch_all_compliance_records(sheet_id=sheet_id)
        summary["total_checked"] = len(records)
    except Exception as fetch_err:
        err_msg = f"Failed to fetch compliance spreadsheet records: {fetch_err}"
        logger.error(err_msg, exc_info=True)
        summary["errors"].append(err_msg)
        return summary

    # 2. Filter records due today
    due_items = []
    for rec in records:
        r_due = rec.get("due_date")
        if r_due and r_due == check_date:
            due_items.append(rec)

    summary["due_count"] = len(due_items)
    logger.info(f"Found {len(due_items)} compliance items due on {check_date.isoformat()}.")

    if not due_items:
        logger.info("No compliance items due today. Check completed.")
        return summary

    anoop_phone = resolve_anoop_phone_number()

    # 3. Process each due item
    for rec in due_items:
        c_id = rec.get("compliance_id", "UNKNOWN")
        building = rec.get("building", "UNKNOWN")
        due_val = rec.get("due_date", check_date)
        req_name = rec.get("requirement", "")

        item_desc = f"[{building}] {c_id} ({req_name})"
        summary["due_items"].append({
            "compliance_id": c_id,
            "building": building,
            "requirement": req_name,
            "due_date": due_val.isoformat() if isinstance(due_val, date) else str(due_val),
        })

        # Check duplicate
        if not force_send and has_reminder_been_sent_today(c_id, building, due_val, check_date):
            logger.info(f"⏭️ Skipping {item_desc}: Reminder already sent today.")
            summary["skipped_duplicate"] += 1
            continue

        # Send reminder to Anoop Sir
        logger.info(f"📤 Sending compliance due reminder to Anoop ({anoop_phone}) for {item_desc}...")
        success, resp_data, error_msg = send_compliance_reminder_to_anoop(rec, override_phone=anoop_phone)

        if success:
            summary["sent_count"] += 1
            wa_status = "accepted"
            deliv_status = "sent"
            log_reminder_attempt(
                compliance_id=c_id,
                building=building,
                due_date=due_val,
                recipient_phone=anoop_phone,
                whatsapp_status=wa_status,
                delivery_status=deliv_status,
                sent_date=check_date,
                error=None,
                metadata={"response": resp_data, "record": rec},
            )
        else:
            summary["failed_count"] += 1
            wa_status = "failed"
            deliv_status = "failed"
            summary["errors"].append(f"{item_desc}: {error_msg}")
            log_reminder_attempt(
                compliance_id=c_id,
                building=building,
                due_date=due_val,
                recipient_phone=anoop_phone,
                whatsapp_status=wa_status,
                delivery_status=deliv_status,
                sent_date=check_date,
                error=error_msg,
                metadata={"response": resp_data, "record": rec},
            )

    logger.info(
        f"🏁 Compliance daily check finished: {summary['sent_count']} sent, "
        f"{summary['skipped_duplicate']} skipped (duplicates), {summary['failed_count']} failed."
    )
    return summary
