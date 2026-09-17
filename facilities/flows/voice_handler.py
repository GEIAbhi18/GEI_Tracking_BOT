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
from facilities.alias_normalizer import normalize_building_aliases
from facilities.flows.router import get_session, set_session, clear_session

logger = logging.getLogger(__name__)

# Words/phrases treated as trivial (not worth offering an action menu)
_TRIVIAL_WORDS = frozenset({
    "hi", "hello", "hey", "ok", "okay", "yes", "no", "test",
    "testing", "thanks", "thank", "bye", "good", "fine",
    "hmm", "hm", "um", "uh", "ah",
})

# Confidence threshold below which we ask for clarification
LOW_CONFIDENCE_THRESHOLD = 0.65


def _is_trivial_transcript(text: str) -> bool:
    """Return True if transcript is too short or just a greeting/noise."""
    words = text.strip().split()
    if len(words) < 3:
        return True
    # If every word is in the trivial set, it's noise
    return all(w.lower().strip(".,!?'\"") in _TRIVIAL_WORDS for w in words)


def handle_voice_note(sender: str, transcript: str, user: dict):
    """Process a voice note transcription."""
    send_text(sender, "🎙️ *Processing voice note...*")

    # Normalize building aliases before extraction
    transcript = normalize_building_aliases(transcript)

    # Extract operations from transcript
    result = extract_voice_operations(transcript)

    operations = result.get("operations", [])
    confidence = result.get("transcription_confidence", 0.0)
    raw = result.get("raw_transcript", transcript)

    if not operations:
        # Decide: trivial → discard message; substantial → action menu
        if _is_trivial_transcript(raw):
            send_text(
                sender,
                f"🎙️ *Voice Note Received*\n\n"
                f"📝 _\"{raw}\"_\n\n"
                f"I couldn't identify any task operations from this voice note.\n"
                f"Please try again or type your request."
            )
        else:
            _show_voice_fallback_menu(sender, raw, user)
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
    """Confirm and execute all voice operations.

    If any create_task operations are missing a building, pause execution
    and prompt the user to select a building first.
    """
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

    # Check if any create_task operations are missing a building
    needs_building = any(
        op.get("intent") == "create_task" and not op.get("entities", {}).get("building")
        for op in operations
    )

    if needs_building:
        # Save operations and transition to building-selection state
        set_session(sender, "voice_awaiting_building", context=context)
        _prompt_building_for_voice_ops(sender, user)
        return

    # All create_task ops have buildings (or there are none) — execute immediately
    _execute_all_voice_ops(sender, operations, user)


def _prompt_building_for_voice_ops(sender: str, user: dict):
    """Prompt the user to select a building for voice operations that need one."""
    from facilities.auth import get_permitted_buildings

    buildings = get_permitted_buildings(user)

    if len(buildings) <= 3:
        buttons = [{"id": f"fac_bldg_{b}", "title": b} for b in buildings]
        send_interactive_buttons(
            sender,
            "🏗️ *Building Required*\n\n"
            "Which building should these tasks be created in?\n"
            "Please select a building:",
            buttons,
        )
    else:
        from whatsapp.ux import send_list_message
        rows = [{"id": f"fac_bldg_{b}", "title": b} for b in buildings]
        sections = [{"title": "Select Building", "rows": rows}]
        send_list_message(
            sender,
            "🏗️ *Building Required*\n\n"
            "Which building should these tasks be created in?",
            "Select Building",
            sections,
        )


def handle_voice_building_selection(sender: str, building: str, user: dict):
    """Handle building selection for voice operations that were missing a building.

    Fills in the missing building on all create_task operations, then executes all ops.
    """
    session = get_session(sender)
    if not session:
        send_text(sender, "Session expired. Please try again.")
        return

    context = session.get("context_json", {})
    operations = context.get("operations", [])

    if not operations:
        send_text(sender, "No operations to execute.")
        clear_session(sender)
        return

    # Fill in the building for create_task operations that are missing it
    for op in operations:
        if op.get("intent") == "create_task" and not op.get("entities", {}).get("building"):
            op.setdefault("entities", {})["building"] = building

    _execute_all_voice_ops(sender, operations, user)


def _execute_all_voice_ops(sender: str, operations: list, user: dict):
    """Execute all voice operations and report per-item results."""
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
    """Handle text input during voice confirmation or building selection."""
    state = session.get("current_flow_state", "")

    if state == "voice_awaiting_building":
        # User typed a building name — fuzzy match it
        from facilities.auth import fuzzy_match_building
        building = fuzzy_match_building(text)
        if building:
            handle_voice_building_selection(sender, building, user)
        else:
            send_text(
                sender,
                f"🤔 I couldn't find a building matching *\"{text}\"*.\n\n"
                f"Please select from the list or type a valid building name."
            )
            _prompt_building_for_voice_ops(sender, user)
        return

    if text.strip().lower() in ("confirm", "yes", "ok", "proceed"):
        confirm_all_voice_ops(sender, user)
    elif text.strip().lower() in ("cancel", "no", "stop"):
        cancel_voice_ops(sender, user)
    else:
        send_text(sender, "Please type *confirm* to proceed or *cancel* to discard.")


def _execute_single_operation(intent: str, entities: dict, user: dict) -> str:
    """Execute a single voice operation. Returns a result description."""
    actor = str(user.get("name") or "GEI_BOT")

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

        # Notify Kanav if this task was created by him
        try:
            from facilities.sheets_client import read_row
            from notifications.kanav_notifier import is_facilities_task_created_by_kanav, notify_kanav_task_change
            task_row = read_row(ref_no)
            if task_row and is_facilities_task_created_by_kanav(task_row):
                changes = []
                if entities.get("status"):
                    st = entities["status"]
                    if st.lower() == "closed":
                        changes.append("Status changed to Closed (Task closed)")
                    else:
                        changes.append(f"Status changed to {st}")
                if entities.get("latest_update"):
                    changes.append(f"Note: {entities['latest_update']}")
                change_made = " | ".join(changes) if changes else "Task updated via voice"
                notify_kanav_task_change(
                    task_id=ref_no,
                    task_title=task_row.get("issue_action", ref_no),
                    change_made=change_made,
                    changed_by=actor or "Team Member",
                    domain="Facilities"
                )
        except Exception as e:
            logger.error(f"Voice update Kanav notification failed: {e}")

        return f"Updated {ref_no}: {', '.join(results)}" if results else f"No fields to update for {ref_no}"

    elif intent == "reassign_task":
        ref_no = entities.get("ref_no")
        new_owner = entities.get("owner")
        if not ref_no or not new_owner:
            return "Missing Ref No or owner — skipped"

        from facilities.sheets_client import write_field, read_row
        r = write_field(ref_no, "owner", new_owner, source="gei_bot", actor=actor)

        # Notify Kanav if this task was created by him
        try:
            from notifications.kanav_notifier import is_facilities_task_created_by_kanav, notify_kanav_task_change
            task_row = read_row(ref_no)
            if task_row and is_facilities_task_created_by_kanav(task_row):
                old_owner = task_row.get("owner", "—")
                reassign_str = f"Reassigned to {new_owner}" if old_owner == "—" else f"Reassigned from {old_owner} to {new_owner}"
                notify_kanav_task_change(
                    task_id=ref_no,
                    task_title=task_row.get("issue_action", ref_no),
                    change_made=reassign_str,
                    changed_by=actor or "Team Member",
                    domain="Facilities"
                )
        except Exception as e:
            logger.error(f"Voice reassign Kanav notification failed: {e}")

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


# ── Post-Voice Fallback (unclear intent) ─────────────────────────────────────

def _show_voice_fallback_menu(sender: str, transcript: str, user: dict):
    """Show action options when a voice note has content but no clear intent."""
    # Store transcript in session so the chosen action can reuse it
    set_session(sender, "voice_fallback", context={
        "raw_transcript": transcript,
    })

    msg = (
        f"🎙️ *Voice Note Received*\n\n"
        f"📝 _\"{transcript[:300]}\"_\n\n"
        f"I captured your note but couldn't detect a specific action.\n"
        f"What would you like to do with this?"
    )

    buttons = [
        {"id": "fac_voice_create_task", "title": "➕ Create a Task"},
        {"id": "fac_voice_update_task", "title": "🔄 Update a Task"},
        {"id": "fac_voice_discard", "title": "❌ Discard"},
    ]
    send_interactive_buttons(sender, msg, buttons)


def handle_voice_fallback_create(sender: str, user: dict):
    """User chose 'Create a Task' from the voice fallback menu."""
    session = get_session(sender)
    transcript = ""
    if session:
        transcript = session.get("context_json", {}).get("raw_transcript", "")
    clear_session(sender)

    from facilities.flows.create_task import start_create_flow
    prefill = {}
    if transcript:
        prefill["issue_action"] = transcript
    start_create_flow(sender, user, prefill=prefill)


def handle_voice_fallback_update(sender: str, user: dict):
    """User chose 'Update an Existing Task' from the voice fallback menu."""
    session = get_session(sender)
    transcript = ""
    if session:
        transcript = session.get("context_json", {}).get("raw_transcript", "")

    # Store transcript as pending note, then prompt for Ref No
    set_session(sender, "update_ref_no_input", context={
        "pending_note": transcript,
    })

    send_text(
        sender,
        "📋 *Update an Existing Task*\n\n"
        "Please enter the task Ref No you'd like to update "
        "(e.g., GEBB1-001, GETT-042)."
    )


def handle_voice_fallback_discard(sender: str, user: dict):
    """User chose 'Discard' from the voice fallback menu."""
    clear_session(sender)
    send_text(sender, "🗑️ Voice note discarded.\n\n_Type *menu* to go back._")

