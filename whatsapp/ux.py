import os
import logging
import requests

logger = logging.getLogger(__name__)

WHATSAPP_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")
WA_API_BASE = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}"

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


def _post_wa(payload: dict) -> bool:
    if not WHATSAPP_ACCESS_TOKEN or not PHONE_NUMBER_ID:
        logger.error("WA UX: Missing META_ACCESS_TOKEN or PHONE_NUMBER_ID")
        return False

    if "to" in payload:
        payload["to"] = clean_phone_number(payload["to"])

    url = f"{WA_API_BASE}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
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
    Max 3 buttons.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                    for b in buttons
                ]
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
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body},
            "action": {
                "button": button_text,
                "sections": sections
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
