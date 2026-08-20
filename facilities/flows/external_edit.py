"""
Screen 09 — External Edit Detection
======================================
Handled by sync_engine.py polling job. This module provides the
notification rendering if needed as a standalone call.
"""

import logging
from datetime import datetime, timezone

from whatsapp.ux import send_text

logger = logging.getLogger(__name__)


def render_external_edit_card(ref_no: str, field: str, old_value: str,
                                new_value: str) -> str:
    """Render the Screen 09 external edit notification card."""
    now = datetime.now(timezone.utc).strftime("%H:%M UTC, %d %b %Y")

    return (
        f"📊 *Detected from Google Sheets*\n"
        f"{'─' * 25}\n\n"
        f"*Ref:* {ref_no}\n"
        f"*Field:* {field}\n"
        f"*Previous:* {old_value or '—'}\n"
        f"*Updated to:* {new_value or '—'}\n\n"
        f"🔄 Google Sheets → GEI_BOT\n"
        f"🕐 Detected at {now}\n\n"
        f"_This change was made directly on the Google Sheet "
        f"and has been synced to GEI_BOT automatically._"
    )


def send_external_edit_card(to: str, ref_no: str, field: str,
                              old_value: str, new_value: str):
    """Send the external edit notification to a user."""
    card = render_external_edit_card(ref_no, field, old_value, new_value)
    send_text(to, card)
