import os
import logging
import requests

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

WHATSAPP_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")
WA_API_BASE = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}" if PHONE_NUMBER_ID else ""


def _mask_phone(phone: str) -> str:
    """Return a masked phone for safe logging (shows last 4 digits only)."""
    # pyrefly: ignore[unnecessary-type-conversion]
    digits = "".join(c for c in str(phone or "") if c.isdigit())
    if len(digits) >= 6:
        return "*" * (len(digits) - 4) + digits[-4:]
    return "****"

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

def _post_wa(payload: dict, _recipient_role: str = "", _event_id: str = "") -> bool:
    """
    Post a WhatsApp message via the Meta Graph API.

    Args:
        payload:         The WhatsApp API payload dict.
        _recipient_role: Human-readable role label for structured logs (e.g. 'kanav', 'developer').
        _event_id:       Correlation ID tying all log lines for a single sheet-change event together.
    """
    token = os.getenv("META_ACCESS_TOKEN") or WHATSAPP_ACCESS_TOKEN
    phone_id = os.getenv("PHONE_NUMBER_ID") or PHONE_NUMBER_ID
    if not token or not phone_id:
        logger.error(
            "[WhatsAppNotification] CONFIGURATION_ERROR | "
            "Missing META_ACCESS_TOKEN or PHONE_NUMBER_ID"
        )
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
            logger.info(
                f"[TEST SAFETY] Rerouting test message from {_mask_phone(clean_to)} "
                f"to developer ({_mask_phone(DEVELOPER_PHONE)})"
            )
            payload["to"] = DEVELOPER_PHONE
    elif clean_to == kanav_clean:
        payload_str = str(payload).lower()
        if any(marker in payload_str for marker in ("test", "demo", "dummy", "simulation", "mock")):
            logger.warning(
                f"[TEST SAFETY] Blocked test-marker message to Kanav ({_mask_phone(KANAV_PHONE)}). "
                f"Rerouting to developer ({_mask_phone(DEVELOPER_PHONE)})"
            )
            payload["to"] = DEVELOPER_PHONE

    final_to = payload.get("to", "")
    role_tag = f" | recipient_role={_recipient_role}" if _recipient_role else ""
    event_tag = f" | event_id={_event_id}" if _event_id else ""

    logger.info(
        f"[WhatsAppNotification]{event_tag}{role_tag} | "
        f"phone={_mask_phone(final_to)} | status=SEND_ATTEMPT"
    )

    api_base = f"https://graph.facebook.com/v19.0/{phone_id}"
    url = f"{api_base}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)

        # Extract Meta message ID for delivery tracking
        message_id = ""
        try:
            resp_json = r.json()
            messages = resp_json.get("messages", [])
            if messages and isinstance(messages, list):
                message_id = messages[0].get("id", "")
        except Exception:
            pass

        if r.status_code == 200:
            logger.info(
                f"[WhatsAppNotification]{event_tag}{role_tag} | "
                f"phone={_mask_phone(final_to)} | "
                f"http_status={r.status_code} | "
                f"message_id={message_id or 'n/a'} | "
                f"status=API_ACCEPTED"
            )
        else:
            logger.error(
                f"[WhatsAppNotification]{event_tag}{role_tag} | "
                f"phone={_mask_phone(final_to)} | "
                f"http_status={r.status_code} | "
                f"response={r.text[:300]} | "
                f"status=API_REJECTED"
            )

        r.raise_for_status()
        return True
    except requests.exceptions.HTTPError as e:
        # raise_for_status() already logged above — just signal failure
        return False
    except Exception as e:
        logger.error(
            f"[WhatsAppNotification]{event_tag}{role_tag} | "
            f"phone={_mask_phone(final_to)} | "
            f"error={e} | status=SEND_ERROR"
        )
        return False

def send_text(to: str, body: str, _recipient_role: str = "", _event_id: str = "") -> bool:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    return _post_wa(payload, _recipient_role=_recipient_role, _event_id=_event_id)

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
