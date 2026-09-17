"""
Tests for Kanav Task Change Notifications (Facilities & Elara Home).
Validates:
1. Task creator detection (Kanav vs other users)
2. Notification message format (ID, Title, Change Made, Changed By, Timestamp, Domain)
3. Notification dispatch on update, reassign, status-changed, and closed in Facilities
4. Notification dispatch on update, status-changed, blocker, and closed in Elara Home
5. Filtering: Non-Kanav tasks do NOT trigger notifications to Kanav
"""

import pytest
from unittest.mock import patch, MagicMock
from notifications.kanav_notifier import (
    get_kanav_phone,
    format_task_change_message,
    is_facilities_task_created_by_kanav,
    is_elara_task_created_by_kanav,
    notify_kanav_task_change,
)
from elara.config import KANAV_PHONE


# ── 1. Helper & Formatting Tests ─────────────────────────────────────────────

def test_get_kanav_phone_fallback():
    """Verify fallback to KANAV_PHONE constant if db has no entry or fails."""
    with patch("db.supabase.table") as mock_table:
        mock_table.side_effect = Exception("DB offline")
        phone = get_kanav_phone()
        assert phone == KANAV_PHONE


def test_format_task_change_message():
    """Verify message formatting contains all required parameters."""
    msg = format_task_change_message(
        task_id="GEBB1-042",
        task_title="Repair Main Elevator",
        change_made="Status changed from Open to WIP",
        changed_by="Anoop",
        timestamp="17 Sep 2026, 11:30 AM IST",
        domain="Facilities",
    )
    assert "📋 *Task ID:* GEBB1-042" in msg
    assert "📌 *Task Title:* Repair Main Elevator" in msg
    assert "🔄 *Change Made:* Status changed from Open to WIP" in msg
    assert "👤 *Changed By:* Anoop" in msg
    assert "🕒 *Timestamp:* 17 Sep 2026, 11:30 AM IST" in msg
    assert "🏢 *Domain:* Facilities" in msg


# ── 2. Facilities Creator Detection Tests ────────────────────────────────────

def test_is_facilities_task_created_by_kanav():
    """Verify detection of Kanav as creator for Facilities tasks."""
    # When Kanav creates a task, added_by is 'Facilities Director'
    assert is_facilities_task_created_by_kanav({"added_by": "Facilities Director"}) is True
    assert is_facilities_task_created_by_kanav({"last_modified_by_at": "Facilities Director / 2026-08-31 09:40 UTC"}) is True
    assert is_facilities_task_created_by_kanav({"added_by": "Kanav"}) is True
    assert is_facilities_task_created_by_kanav({"actor": "kanav"}) is True
    assert is_facilities_task_created_by_kanav({"created_by": "Kanav"}) is True

    # Other employees should return False
    assert is_facilities_task_created_by_kanav({"added_by": "Facility Head"}) is False
    assert is_facilities_task_created_by_kanav({"added_by": "Facility Manager"}) is False
    assert is_facilities_task_created_by_kanav({"last_modified_by_at": "Anoop / 2026-08-31 09:40 UTC"}) is False
    assert is_facilities_task_created_by_kanav({"added_by": "Vikramjeet"}) is False
    assert is_facilities_task_created_by_kanav({}) is False


# ── 3. Elara Home Creator Detection Tests ────────────────────────────────────

def test_is_elara_task_created_by_kanav():
    """Verify detection of Kanav as creator for Elara Home tasks."""
    # Direct field
    assert is_elara_task_created_by_kanav({"created_by": "Kanav"}) is True
    assert is_elara_task_created_by_kanav({"created_by": "kk"}) is True

    # Via comments provenance
    task_with_comment = {
        "id": "task-101",
        "comments": [
            {"user_name": "Kanav", "user_role": "Director", "content": "Task created by Kanav"}
        ]
    }
    assert is_elara_task_created_by_kanav(task_with_comment) is True

    # Other creator
    task_other = {
        "id": "task-102",
        "created_by": "Rachit",
        "comments": [
            {"user_name": "Rachit", "user_role": "Site Incharge", "content": "Task created by Rachit"}
        ]
    }
    assert is_elara_task_created_by_kanav(task_other) is False


# ── 4. Facilities Integration Flow Tests ─────────────────────────────────────

def test_facilities_confirm_update_notifies_kanav():
    """When a task created by Kanav is updated/closed, send Kanav a WhatsApp notification."""
    from facilities.flows.update_task import confirm_update

    mock_row = {
        "ref_no": "GEBB1-010",
        "issue_action": "Fix Chiller Pump",
        "added_by": "Facilities Director",
        "owner": "Facility Manager",
        "status": "Open",
    }
    mock_session = {
        "context_json": {
            "ref_no": "GEBB1-010",
            "current_status": "Open",
            "new_status": "Closed",
            "new_update": "Pump repaired and running",
            "new_estimated_completion_date": None,
        }
    }

    with patch("facilities.flows.update_task.get_session", return_value=mock_session), \
         patch("facilities.flows.update_task.read_row", return_value=mock_row), \
         patch("facilities.flows.update_task.write_field", return_value={"status": "synced"}), \
         patch("facilities.flows.update_task.send_text") as mock_send_ui, \
         patch("facilities.flows.update_task.clear_session"), \
         patch("notifications.kanav_notifier.send_text") as mock_send_wa:

        confirm_update("918826896085", user={"name": "Anoop", "role": "Facility Head"})

        # WhatsApp message to Kanav must be sent
        assert mock_send_wa.called
        call_args = mock_send_wa.call_args[0]
        to_number, body = call_args[0], call_args[1]
        assert to_number == KANAV_PHONE
        assert "GEBB1-010" in body
        assert "Fix Chiller Pump" in body
        assert "Status changed from Open to Closed" in body
        assert "Anoop" in body
        assert "Facilities" in body


def test_facilities_confirm_update_skips_non_kanav_task():
    """When a task NOT created by Kanav is updated, Kanav does NOT receive a notification."""
    from facilities.flows.update_task import confirm_update

    mock_row = {
        "ref_no": "GEBB1-011",
        "issue_action": "Paint Stairwell",
        "added_by": "Facility Manager",
        "owner": "Facility Manager",
        "status": "Open",
    }
    mock_session = {
        "context_json": {
            "ref_no": "GEBB1-011",
            "current_status": "Open",
            "new_status": "WIP",
            "new_update": "Primer applied",
        }
    }

    with patch("facilities.flows.update_task.get_session", return_value=mock_session), \
         patch("facilities.flows.update_task.read_row", return_value=mock_row), \
         patch("facilities.flows.update_task.write_field", return_value={"status": "synced"}), \
         patch("facilities.flows.update_task.send_text"), \
         patch("facilities.flows.update_task.clear_session"), \
         patch("notifications.kanav_notifier.send_text") as mock_send_wa:

        confirm_update("918826896085", user={"name": "Anoop", "role": "Facility Head"})
        assert not mock_send_wa.called


def test_facilities_reassign_notifies_kanav():
    """When a task created by Kanav is reassigned, Kanav receives a notification."""
    from facilities.flows.task_card import handle_reassign_selection

    mock_row = {
        "ref_no": "GETT-005",
        "issue_action": "Inspect Terrace Garden",
        "added_by": "Facilities Director",
        "owner": "Vikash",
    }
    mock_session = {
        "context_json": {
            "ref_no": "GETT-005",
            "old_owner": "Vikash",
        }
    }

    with patch("facilities.flows.router.get_session", return_value=mock_session), \
         patch("facilities.flows.task_card.read_row", return_value=mock_row), \
         patch("facilities.flows.task_card.write_field", return_value={"status": "synced"}), \
         patch("facilities.flows.task_card.send_text"), \
         patch("facilities.flows.task_card._notify_new_owner"), \
         patch("facilities.flows.router.clear_session"), \
         patch("notifications.kanav_notifier.send_text") as mock_send_wa:

        handle_reassign_selection("918826896085", "Anoop", user={"name": "Vikramjeet", "role": "Manager"})

        assert mock_send_wa.called
        to_number, body = mock_send_wa.call_args[0]
        assert to_number == KANAV_PHONE
        assert "GETT-005" in body
        assert "Reassigned from Vikash to Anoop" in body
        assert "Vikramjeet" in body


# ── 5. Elara Home Integration Flow Tests ─────────────────────────────────────

def test_elara_status_update_notifies_kanav():
    """When an Elara task created by Kanav has its status updated, Kanav receives a WhatsApp notification."""
    from elara.flows.update_task import handle_status_selection

    mock_task = {
        "id": "elara-t-100",
        "title": "Vendor Quotation Review",
        "status": "pending",
        "created_by": "Kanav",
    }

    with patch("elara.flows.update_task.get_task_by_id", return_value=mock_task), \
         patch("elara.flows.update_task.update_task", return_value=mock_task), \
         patch("elara.flows.update_task.send_text"), \
         patch("elara.flows.update_task.send_elara_task_card"), \
         patch("elara.flows.update_task.send_interactive_buttons"), \
         patch("notifications.kanav_notifier.send_text") as mock_send_wa:

        handle_status_selection(
            to="919867272041",
            task_id="elara-t-100",
            new_status="completed",
            user={"name": "Bhagwan Dass", "role": "Purchasing Head"}
        )

        assert mock_send_wa.called
        to_number, body = mock_send_wa.call_args[0]
        assert to_number == KANAV_PHONE
        assert "elara-t-100" in body
        assert "Vendor Quotation Review" in body
        assert "Completed (Task closed)" in body
        assert "Bhagwan Dass" in body
        assert "Elara Home" in body


def test_elara_status_update_skips_non_kanav_task():
    """When an Elara task NOT created by Kanav is updated, Kanav is NOT notified."""
    from elara.flows.update_task import handle_status_selection

    mock_task = {
        "id": "elara-t-101",
        "title": "Site Inspection",
        "status": "pending",
        "created_by": "Rachit",
        "comments": [{"user_name": "Rachit", "content": "Task created by Rachit"}],
    }

    with patch("elara.flows.update_task.get_task_by_id", return_value=mock_task), \
         patch("elara.flows.update_task.update_task", return_value=mock_task), \
         patch("elara.flows.update_task.send_text"), \
         patch("elara.flows.update_task.send_elara_task_card"), \
         patch("elara.flows.update_task.send_interactive_buttons"), \
         patch("notifications.kanav_notifier.send_text") as mock_send_wa:

        handle_status_selection(
            to="919867272041",
            task_id="elara-t-101",
            new_status="in_progress",
            user={"name": "Gaurav", "role": "Site Executive"}
        )

        assert not mock_send_wa.called


def test_elara_blocker_notifies_kanav():
    """When an Elara task created by Kanav is marked as a Blocker, Kanav is notified."""
    from elara.flows.update_task import handle_blocker_reason_input

    mock_task = {
        "id": "elara-t-102",
        "title": "RERA Document Submission",
        "status": "pending",
        "created_by": "Kanav",
    }
    mock_session = {"draft": {"task_id": "elara-t-102"}}

    with patch("elara.flows.update_task.get_task_by_id", return_value=mock_task), \
         patch("elara.flows.update_task.update_task", return_value=mock_task), \
         patch("elara.db.add_comment"), \
         patch("elara.flows.update_task.clear_elara_session"), \
         patch("elara.flows.update_task.send_text"), \
         patch("elara.flows.update_task.send_elara_task_card"), \
         patch("notifications.kanav_notifier.send_text") as mock_send_wa:

        handle_blocker_reason_input(
            to="918894577707",
            text="Waiting for architect seal",
            user={"name": "Gaurav", "role": "Site Executive"},
            session=mock_session
        )

        assert mock_send_wa.called
        to_number, body = mock_send_wa.call_args[0]
        assert to_number == KANAV_PHONE
        assert "elara-t-102" in body
        assert "Blocker (Reason: Waiting for architect seal)" in body
        assert "Gaurav" in body


def test_elara_comment_notifies_kanav():
    """When a comment is added to an Elara task created by Kanav, Kanav is notified."""
    from elara.flows.comments import handle_comment_text_input

    mock_task = {
        "id": "elara-t-103",
        "title": "Electrical Layout Drawing",
        "status": "in_progress",
        "created_by": "Kanav",
    }
    mock_session = {"draft": {"task_id": "elara-t-103"}}

    with patch("elara.flows.comments.get_task_by_id", return_value=mock_task), \
         patch("elara.db.add_comment"), \
         patch("elara.flows.comments.clear_elara_session"), \
         patch("elara.flows.comments.send_interactive_buttons"), \
         patch("notifications.kanav_notifier.send_text") as mock_send_wa:

        handle_comment_text_input(
            to="919867272041",
            text="Revised drawing submitted to client for approval",
            user={"name": "Rachit", "role": "Site Incharge"},
            session=mock_session
        )

        assert mock_send_wa.called
        to_number, body = mock_send_wa.call_args[0]
        assert to_number == KANAV_PHONE
        assert "elara-t-103" in body
        assert "Revised drawing submitted to client for approval" in body
        assert "Rachit" in body
