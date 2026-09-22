import os
import logging
import requests

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

WHATSAPP_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")
WA_API_BASE = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}" if PHONE_NUMBER_ID else ""

def clean_phone_number(phone) -> str:
    """
    Cleans phone numbers for WhatsApp API.
    Strips non-digit characters except numeric digits.
    If 10 digits (e.g. 9996221554), prefixes default country code '91'.
    Returns clean numeric string (e.g. '919996221554').
    """
    if not phone:
        return ""
    digits = "".join(c for c in str(phone) if c.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    return digits


def is_testing_env() -> bool:
    import sys
    return (
        os.getenv("TESTING") in ("1", "true", "True")
        or "pytest" in sys.modules
        or os.getenv("PYTEST_CURRENT_TEST") is not None
    )

def _post_wa(payload: dict) -> bool:
    token = os.getenv("META_ACCESS_TOKEN") or WHATSAPP_ACCESS_TOKEN
    phone_id = os.getenv("PHONE_NUMBER_ID") or PHONE_NUMBER_ID
    if not token or not phone_id:
        logger.error("WA UX: Missing META_ACCESS_TOKEN or PHONE_NUMBER_ID")
        return False

    if "to" in payload:
        payload["to"] = clean_phone_number(payload["to"])

    # ── Test Safety Guard ─────────────────────────────────────────────
    # Kanav is not a developer and must NEVER receive test messages.
    # While testing anything, only the developer (917717754421) should receive test messages.
    from elara.config import KANAV_PHONE, DEVELOPER_PHONE
    clean_to = payload.get("to", "")
    kanav_clean = clean_phone_number(KANAV_PHONE)

    if is_testing_env():
        if clean_to != DEVELOPER_PHONE:
            logger.info(f"[TEST SAFETY] Rerouting test message from {clean_to} to developer ({DEVELOPER_PHONE})")
            payload["to"] = DEVELOPER_PHONE
    elif clean_to == kanav_clean:
        payload_str = str(payload).lower()
        if any(marker in payload_str for marker in ("test", "demo", "dummy", "simulation", "mock")):
            logger.warning(f"[TEST SAFETY] Blocked test message to Kanav ({KANAV_PHONE}). Rerouting to developer ({DEVELOPER_PHONE})")
            payload["to"] = DEVELOPER_PHONE

    api_base = f"https://graph.facebook.com/v19.0/{phone_id}"
    url = f"{api_base}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        logger.info(f"WA API {r.status_code} [to={payload.get('to')} type={payload.get('type')}]: {r.text[:200]}")
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"WA API error [to={payload.get('to')}]: {e}")
        return False

def send_text(to: str, body: str) -> bool:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    return _post_wa(payload)

def send_interactive_buttons(to: str, body: str, buttons: list) -> bool:
    """
    buttons: [{"id": "btn_id", "title": "Button Title"}, ...]
    Max 3 buttons. Meta body limit: 1024 chars.
    """
    if len(body) > 1000:
        send_text(to, body)
        body = "Please select an option:"

    # Sanitize button titles (max 20 chars for WhatsApp API)
    sanitized_buttons = []
    for b in buttons[:3]:
        title = b["title"]
        if len(title) > 20:
            title = title[:20]
        sanitized_buttons.append({"type": "reply", "reply": {"id": b["id"], "title": title}})

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": sanitized_buttons
            },
        },
    }
    return _post_wa(payload)

def send_list_message(to: str, body: str, button_text: str, sections: list) -> bool:
    """
    sections: [
      {
        "title": "Section Title",
        "rows": [{"id": "row_id", "title": "Row Title", "description": "Optional"}, ...]
      }
    ]
    Meta body limit: 1024 chars.
    """
    if len(body) > 1000:
        send_text(to, body)
        body = "Tap below to select an option:"

    # Sanitize button_text (max 20 chars)
    if len(button_text) > 20:
        button_text = button_text[:20]

    # Sanitize sections
    sanitized_sections = []
    for sec in sections:
        sec_title = sec.get("title", "Options")
        if len(sec_title) > 24:
            sec_title = sec_title[:24]

        sanitized_rows = []
        for r in sec.get("rows", []):
            rtitle = r.get("title", "")
            if len(rtitle) > 24:
                rtitle = rtitle[:24]
            rdesc = r.get("description", "")
            if rdesc and len(rdesc) > 72:
                rdesc = rdesc[:72]

            row_obj = {"id": r["id"], "title": rtitle}
            if rdesc:
                row_obj["description"] = rdesc
            sanitized_rows.append(row_obj)

        sanitized_sections.append({
            "title": sec_title,
            "rows": sanitized_rows[:10]  # Max 10 rows per section
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body},
            "action": {
                "button": button_text,
                "sections": sanitized_sections
            }
        }
    }
    return _post_wa(payload)

def send_followup_prompt(to: str, parent_task_id: str) -> bool:
    """Sends a prompt to ask the user if they want to create a follow-up task."""
    body = "Would you like to create a Follow-up Task?"
    buttons = [
        {"id": f"task_followup_{parent_task_id}", "title": "Create Follow-up"},
        {"id": f"task_ignorefollowup_{parent_task_id}", "title": "Ignore"}
    ]
    return send_interactive_buttons(to, body, buttons)
