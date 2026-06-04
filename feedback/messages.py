"""
Feedback Message Templates
==========================
All WhatsApp messages sent by the feedback bot.
Updated for WhatsApp Flows — conversational Q&A messages removed.
"""


def message_b(client_name: str, complaint_id: str, sheet_updated: bool = True) -> str:
    """Thank You message sent after successful Flow form submission."""
    if sheet_updated:
        return (
            f"🙏 Thank you, {client_name}!\n\n"
            f"Your feedback for complaint *{complaint_id}* has been "
            f"officially recorded and our records have been updated. ✅\n\n"
            f"Your feedback session is now *complete*.\n\n"
            f"Your response helps us serve you better and improve "
            f"our facility services continuously.\n\n"
            f"— *Good Earth Infra Facilities Team* 🏢"
        )
    else:
        return (
            f"🙏 Thank you, {client_name}!\n\n"
            f"Your feedback for complaint *{complaint_id}* has been "
            f"received. ✅\n\n"
            f"Your feedback session is now *complete*. "
            f"Our team will update the records shortly.\n\n"
            f"Your response helps us serve you better and improve "
            f"our facility services continuously.\n\n"
            f"— *Good Earth Infra Facilities Team* 🏢"
        )


def reminder_message(client_name: str, complaint_id: str) -> str:
    """Gentle reminder for pending feedback (plain text, no Flow button)."""
    return (
        f"Hi {client_name}, 👋\n\n"
        f"This is a gentle reminder that your feedback for complaint "
        f"*{complaint_id}* is pending.\n\n"
        f"Your opinion helps us serve you better. Please tap the "
        f"button in our previous message to share your feedback.\n\n"
        f"— Good Earth Infra Team 🏢"
    )


def feedback_in_progress_reply(client_name: str, complaint_id: str) -> str:
    """Sent when a client texts during an active Flow session."""
    return (
        f"Hi {client_name}, we're waiting for your feedback on "
        f"complaint *{complaint_id}*.\n\n"
        f"Please tap the *\"Give Feedback\"* button in our previous "
        f"message to open the feedback form. 🙏"
    )


def session_cancelled() -> str:
    return "Your feedback session has been cancelled. Thank you."
