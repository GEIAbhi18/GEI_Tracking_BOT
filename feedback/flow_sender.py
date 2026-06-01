"""
WhatsApp Flow Template Sender
==============================
Sends the gei_feedback_request template message with an attached
WhatsApp Flow button for interactive feedback collection.
"""

import logging
import requests

from feedback.config import (
    META_ACCESS_TOKEN,
    PHONE_NUMBER_ID,
    WHATSAPP_FLOW_ID,
    WHATSAPP_FLOW_TEMPLATE_NAME,
)

logger = logging.getLogger(__name__)

WA_API_BASE = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}"


def _post_wa(payload: dict) -> bool:
    """POST any payload to the WhatsApp messages endpoint. Returns True on success."""
    if not META_ACCESS_TOKEN or not PHONE_NUMBER_ID:
        logger.error("Flow sender: Missing META_ACCESS_TOKEN or PHONE_NUMBER_ID")
        return False
    url = f"{WA_API_BASE}/messages"
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code == 400:
            # Log the full error body — most likely cause: Flow is in DRAFT (not published)
            logger.error(
                f"WA Flow API 400 Bad Request. "
                f"If your WhatsApp Flow is in DRAFT mode, publish it first. "
                f"Full response: {r.text[:500]}"
            )
            return False
        logger.info(f"WA Flow API {r.status_code}: {r.text[:300]}")
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"WA Flow API error: {e}")
        return False


def send_flow_template(
    phone: str,
    client_name: str,
    complaint_id: str,
    complaint_nature: str,
    unit_no: str,
) -> bool:
    """
    Send the gei_feedback_request WhatsApp template message with Flow button.

    Template structure (must match what's registered on Meta):
      HEADER: Good Earth — Complaint Resolved ✅
      BODY:   Dear {{1}}, Your complaint *{{2}}* regarding *{{3}}* at Unit {{4}} ...
      FOOTER: Good Earth Imaging Facilities Team
      BUTTON: Type=FLOW, Label="Give Feedback", Flow ID=WHATSAPP_FLOW_ID

    Args:
        phone:            Normalized phone number (e.g. "917717754421")
        client_name:      {{1}} — Client Name
        complaint_id:     {{2}} — Complaint ID
        complaint_nature: {{3}} — Complaint Nature
        unit_no:          {{4}} — Unit No

    Returns:
        True if sent successfully, False otherwise.
    """
    if not WHATSAPP_FLOW_ID:
        logger.error("WHATSAPP_FLOW_ID not configured — cannot send Flow template")
        return False

    if not WHATSAPP_FLOW_TEMPLATE_NAME:
        logger.error("WHATSAPP_FLOW_TEMPLATE_NAME not configured")
        return False

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": WHATSAPP_FLOW_TEMPLATE_NAME,
            "language": {"code": "en"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": client_name},
                        {"type": "text", "text": complaint_id},
                        {"type": "text", "text": complaint_nature},
                        {"type": "text", "text": str(unit_no)},
                    ],
                },
                {
                    "type": "button",
                    "sub_type": "flow",
                    "index": "0",
                    "parameters": [
                        {
                            "type": "action",
                            "action": {
                                "flow_token": complaint_id,
                            },
                        }
                    ],
                },
            ],
        },
    }

    logger.info(f"Sending Flow template to {phone} for complaint {complaint_id}")
    return _post_wa(payload)
