"""
Screen 18 — Voice Note Handling
==================================
Transcribe → extract multiple operations → confidence check.
Low confidence: ask for clarification per item.
On confirm: write each independently, report per-item sync status.
"""

import logging

from whatsapp.ux import send_text, send_interactive_buttons
from facilities.llm import extract_voice_operations
from facilities.flows.router import get_session, set_session, clear_session

logger = logging.getLogger(__name__)

# Confidence threshold below which we ask for clarification
LOW_CONFIDENCE_THRESHOLD = 0.65


def handle_voice_note(sender: str, transcript: str, user: dict):
    """Process a voice note transcription."""
    send_text(sender, "🎙️ *Processing voice note...*")

    # Extract operations from transcript
    result = extract_voice_operations(transcript)

    operations = result.get("operations", [])
    confidence = result.get("transcription_confidence", 0.0)
    raw = result.get("raw_transcript", transcript)

    if not operations:
        send_text(
            sender,
            f"🎙️ *Voice Note Received*\n\n"
            f"📝 _\"{raw}\"_\n\n"
            f"I couldn't identify any task operations from this voice note.\n"
            f"Please try again or type your request."
        )
        return

    # Store operations in session
    context = {
        "operations": operations,
        "confidence": confidence,
        "raw_transcript": raw,
    }
    set_session(sender, "voice_confirm", context=context)

    # Check confidence
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        _show_low_confidence_clarification(sender, operations, raw, user)
    else:
        _show_voice_confirmation(sender, operations, raw, confidence, user)


def _show_voice_confirmation(sender: str, operations: list, raw: str,
                               confidence: float, user: dict):
    """Show confirmation summary for extracted operations."""
    msg_parts = [
        f"🎙️ *Voice Note — {len(operations)} Operation(s) Detected*\n",
        f"📝 _\"{raw[:200]}\"_\n",
        f"🎯 Confidence: {int(confidence * 100)}%\n",
    ]

    for i, op in enumerate(operations, 1):
        intent = op.get("intent", "unknown")
        entities = op.get("entities", {})
        op_confidence = op.get("confidence", 0)

        msg_parts.append(f"\n*Operation {i}:* {_format_intent(intent)}")

        if entities.get("ref_no"):
            msg_parts.append(f"  📋 Ref: {entities['ref_no']}")
        if entities.get("building"):
            msg_parts.append(f"  🏗️ Building: {entities['building']}")
        if entities.get("issue_action"):
            msg_parts.append(f"  🔧 Action: {entities['issue_action'][:60]}")
        if entities.get("status"):
            msg_parts.append(f"  📊 Status: {entities['status']}")
        if entities.get("owner"):
            msg_parts.append(f"  👤 Owner: {entities['owner']}")

        msg_parts.append(f"  🎯 _{int(op_confidence * 100)}% confident_")

    message = "\n".join(msg_parts)

    buttons = [
        {"id": "fac_voice_confirm_all", "title": "✅ Confirm All"},
        {"id": "fac_voice_cancel", "title": "❌ Cancel"},
    ]
    send_interactive_buttons(sender, message, buttons)


def _show_low_confidence_clarification(sender: str, operations: list,
                                          raw: str, user: dict):
    """When confidence is low, ask for clarification instead of Confirm All."""
    msg_parts = [
        f"🎙️ *Voice Note — Low Confidence*\n",
        f"📝 _\"{raw[:200]}\"_\n",
        f"⚠️ _I'm not fully confident in the transcription. "
        f"Please review each item:_\n",
    ]

    for i, op in enumerate(operations, 1):
        intent = op.get("intent", "unknown")
        entities = op.get("entities", {})

        msg_parts.append(f"\n*Item {i}:* {_format_intent(intent)}")
        if entities.get("issue_action"):
            msg_parts.append(f"  🔧 _{entities['issue_action'][:60]}_")

    msg_parts.append(
        "\n\nPlease re-state each item clearly, or type *confirm* "
        "if the above is correct."
    )

    send_text(sender, "\n".join(msg_parts))


def confirm_all_voice_ops(sender: str, user: dict):
    """Confirm and execute all voice operations."""
    session = get_session(sender)
    if not session:
        send_text(sender, "Session expired. Please try again.")
        return

    context = session.get("context_json", {})
    operations = context.get("operations", [])

    if not operations:
        send_text(sender, "No operations to confirm.")
        clear_session(sender)
        return

    results = []

    for i, op in enumerate(operations, 1):
        intent = op.get("intent", "unknown")
        entities = op.get("entities", {})

        try:
            result = _execute_single_operation(intent, entities, user)
            results.append({"index": i, "status": "success", "detail": result})
        except Exception as e:
            results.append({"index": i, "status": "failed", "detail": str(e)})
            logger.error(f"Voice op {i} failed: {e}")

    # Report per-item status
    msg_parts = [f"🎙️ *Voice Operations — Results*\n"]

    for r in results:
        if r["status"] == "success":
            msg_parts.append(f"  ✅ Operation {r['index']}: {r['detail']}")
        else:
            msg_parts.append(f"  ❌ Operation {r['index']}: Failed — {r['detail']}")

    succeeded = sum(1 for r in results if r["status"] == "success")
    msg_parts.append(f"\n*{succeeded}/{len(results)}* operations completed successfully.")

    send_text(sender, "\n".join(msg_parts))
    clear_session(sender)


def cancel_voice_ops(sender: str, user: dict):
    """Cancel all voice operations."""
    clear_session(sender)
    send_text(sender, "❌ Voice operations cancelled.\n\n_Type *menu* to go back._")


def handle_voice_confirm_text(sender: str, text: str, user: dict, session: dict):
    """Handle text input during voice confirmation."""
    if text.strip().lower() in ("confirm", "yes", "ok", "proceed"):
        confirm_all_voice_ops(sender, user)
    elif text.strip().lower() in ("cancel", "no", "stop"):
        cancel_voice_ops(sender, user)
    else:
        send_text(sender, "Please type *confirm* to proceed or *cancel* to discard.")


def _execute_single_operation(intent: str, entities: dict, user: dict) -> str:
    """Execute a single voice operation. Returns a result description."""
    actor = user.get("name")

    if intent == "create_task":
        building = entities.get("building")
        if not building:
            return "Missing building — skipped"

        from facilities.sheets_client import create_row
        result = create_row(building, {
            "type": entities.get("type", ""),
            "issue_action": entities.get("issue_action", ""),
            "owner": entities.get("owner", actor),
            "target_date": entities.get("target_date", ""),
            "status": entities.get("status", "Open"),
        }, actor=actor)

        return f"Created {result.get('ref_no', '—')} ({result.get('sheet_status', '—')})"

    elif intent == "update_task":
        ref_no = entities.get("ref_no")
        if not ref_no:
            return "Missing Ref No — skipped"

        from facilities.sheets_client import write_field
        results = []

        if entities.get("status"):
            r = write_field(ref_no, "status", entities["status"], source="gei_bot", actor=actor)
            results.append(f"Status→{r['status']}")

        if entities.get("latest_update"):
            r = write_field(ref_no, "latest_update", entities["latest_update"], source="gei_bot", actor=actor)
            results.append(f"Note→{r['status']}")

        return f"Updated {ref_no}: {', '.join(results)}" if results else f"No fields to update for {ref_no}"

    elif intent == "reassign_task":
        ref_no = entities.get("ref_no")
        new_owner = entities.get("owner")
        if not ref_no or not new_owner:
            return "Missing Ref No or owner — skipped"

        from facilities.sheets_client import write_field
        r = write_field(ref_no, "owner", new_owner, source="gei_bot", actor=actor)
        return f"Reassigned {ref_no} to {new_owner} ({r['status']})"

    else:
        return f"Unknown operation: {intent}"


def _format_intent(intent: str) -> str:
    """Format an intent name for display."""
    mapping = {
        "create_task": "➕ Create Task",
        "update_task": "🔄 Update Task",
        "reassign_task": "👤 Reassign",
        "attach_file": "📎 Attach",
    }
    return mapping.get(intent, intent)
