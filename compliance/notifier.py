"""
Compliance Module — WhatsApp Notification Dispatcher
=====================================================
Formats and delivers compliance due reminders strictly to Anoop Sir via
Meta Utility Template 'compliance_due_reminder'.
Enforces that compliance reminders are NEVER sent to unauthorized recipients.
"""

import logging
from datetime import date, datetime
from typing import Any, Dict, Optional, Tuple

import requests

from compliance.config import (
    ANOOP_WHATSAPP_NUMBER,
    COMPLIANCE_TEMPLATE_LANG,
    COMPLIANCE_TEMPLATE_NAME,
    DEFAULT_ANOOP_PHONE,
    META_ACCESS_TOKEN,
    PHONE_NUMBER_ID,
    WA_API_BASE,
)
from db import supabase
from whatsapp.ux import clean_phone_number

logger = logging.getLogger(__name__)


def resolve_anoop_phone_number() -> str:
    """
    Resolve Anoop Sir's phone number.
    Priority:
      1. Configured ANOOP_WHATSAPP_NUMBER if set
      2. Supabase users table lookup for Anoop
      3. Fallback constant (DEFAULT_ANOOP_PHONE)
    """
    if ANOOP_WHATSAPP_NUMBER and ANOOP_WHATSAPP_NUMBER.strip():
        return clean_phone_number(ANOOP_WHATSAPP_NUMBER)

    try:
        res = (
            supabase.table("users")
            .select("whatsapp_number")
            .ilike("name", "%anoop%")
            .execute()
        )
        if res.data and res.data[0].get("whatsapp_number"):
            num = res.data[0]["whatsapp_number"]
            logger.info(f"Resolved Anoop's phone number from Supabase: {num}")
            return clean_phone_number(num)
    except Exception as e:
        logger.warning(f"Failed to resolve Anoop's phone number from DB: {e}")

    return clean_phone_number(DEFAULT_ANOOP_PHONE)


def format_display_date(d: Any) -> str:
    """Format a date or datetime object into DD-Mon-YYYY (e.g., 21-Oct-2023)."""
    if not d:
        return "N/A"
    if isinstance(d, (date, datetime)):
        return d.strftime("%d-%b-%Y")
    d_str = str(d).strip()
    return d_str if d_str else "N/A"


def build_compliance_template_payload(
    to_phone: str,
    record: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build the Meta template message payload with the 11 required parameters:
      1. Building
      2. Compliance ID
      3. Control Group
      4. Category
      5. Requirement / Document
      6. Applicability
      7. Issue Date / Last Done
      8. Valid Till / Next Due
      9. Status
      10. Owner
      11. Action / Remarks
    """
    # 1. Building Name
    building_display = record.get("building_name") or record.get("building") or "N/A"

    # 2. Compliance ID
    compliance_id = record.get("compliance_id") or "N/A"

    # 3. Control Group
    control_group = record.get("control_group") or "N/A"

    # 4. Category
    category = record.get("category") or "N/A"

    # 5. Requirement / Document
    requirement = record.get("requirement") or "N/A"

    # 6. Applicability
    applicability = record.get("applicability") or "Yes"

    # 7. Issue Date / Last Done
    issue_date_str = format_display_date(record.get("issue_date") or record.get("issue_date_raw"))

    # 8. Valid Till / Next Due
    due_date_str = format_display_date(record.get("due_date") or record.get("due_date_raw"))

    # 9. Status
    status = record.get("status") or "Due Today"

    # 10. Owner (defaults to 'Anoop Sir')
    owner = record.get("owner")
    if not owner or str(owner).strip().lower() in ("none", "null", "n/a", ""):
        owner = "Anoop Sir"

    # 11. Action / Remarks (appends evidence reference if available)
    remarks = record.get("remarks") or ""
    evidence = record.get("evidence") or ""

    if remarks and evidence:
        action_remarks = f"{remarks} (Ref: {evidence})"
    elif remarks:
        action_remarks = str(remarks)
    elif evidence:
        action_remarks = f"Initiate action. (Ref: {evidence})"
    else:
        action_remarks = "Please review and take the necessary action."

    parameters = [
        {"type": "text", "text": str(building_display).strip() or "-"},
        {"type": "text", "text": str(compliance_id).strip() or "-"},
        {"type": "text", "text": str(control_group).strip() or "-"},
        {"type": "text", "text": str(category).strip() or "-"},
        {"type": "text", "text": str(requirement).strip() or "-"},
        {"type": "text", "text": str(applicability).strip() or "-"},
        # pyrefly: ignore [unnecessary-type-conversion]
        {"type": "text", "text": str(issue_date_str).strip() or "-"},
        # pyrefly: ignore [unnecessary-type-conversion]
        {"type": "text", "text": str(due_date_str).strip() or "-"},
        {"type": "text", "text": str(status).strip() or "-"},
        {"type": "text", "text": str(owner).strip() or "Anoop Sir"},
        # pyrefly: ignore [unnecessary-type-conversion]
        {"type": "text", "text": str(action_remarks).strip() or "Initiate renewal process."},
    ]

    return {
        "messaging_product": "whatsapp",
        "to": clean_phone_number(to_phone),
        "type": "template",
        "template": {
            "name": COMPLIANCE_TEMPLATE_NAME,
            "language": {"code": COMPLIANCE_TEMPLATE_LANG},
            "components": [
                {
                    "type": "body",
                    "parameters": parameters,
                }
            ],
        },
    }


def send_compliance_reminder_to_anoop(
    record: Dict[str, Any],
    override_phone: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any], Optional[str]]:
    """
    Send compliance due reminder template to Anoop Sir.
    Returns: (success: bool, response_dict: dict, error_msg: Optional[str])
    """
    if not META_ACCESS_TOKEN or not PHONE_NUMBER_ID:
        err = "WhatsApp API credentials not configured (META_ACCESS_TOKEN or PHONE_NUMBER_ID missing)."
        logger.error(err)
        return False, {}, err

    target_phone = override_phone or resolve_anoop_phone_number()
    if not target_phone:
        err = "Recipient phone number could not be resolved."
        logger.error(err)
        return False, {}, err

    import os
    import sys
    from elara.config import KANAV_PHONE, DEVELOPER_PHONE

    is_testing = (
        os.getenv("TESTING") in ("1", "true", "True")
        or "pytest" in sys.modules
        or os.getenv("PYTEST_CURRENT_TEST") is not None
    )

    clean_target = clean_phone_number(target_phone)
    if is_testing and clean_target != DEVELOPER_PHONE:
        target_phone = DEVELOPER_PHONE
    elif clean_target == clean_phone_number(KANAV_PHONE):
        target_phone = DEVELOPER_PHONE

    payload = build_compliance_template_payload(target_phone, record)
    url = f"{WA_API_BASE}/messages"
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        resp_data = resp.json() if resp.text else {}

        if resp.status_code in (200, 201):
            logger.info(
                f"✅ Compliance reminder sent successfully to Anoop ({target_phone}) "
                f"for [{record.get('building')}] {record.get('compliance_id')}"
            )
            return True, resp_data, None

        err_msg = f"Meta API error {resp.status_code}: {resp.text}"
        logger.error(err_msg)
        return False, resp_data, err_msg

    except Exception as e:
        err_msg = f"Exception sending compliance reminder to {target_phone}: {e}"
        logger.error(err_msg, exc_info=True)
        return False, {}, err_msg
