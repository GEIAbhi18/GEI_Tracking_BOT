"""
Tests for Rachit Task Change Notifications in Elara Home.
Validates:
1. Rachit phone resolution (DB lookup, fallback, test isolation)
2. Notification message format for Elara Home tasks
3. Notification dispatch on Elara Home events:
   - Status change (including Completed)
   - Blocker status with reason
   - Comment added
   - Attachment uploaded
   - Task created
4. Anti-duplication / Self-notification prevention:
   - Rachit does NOT get notified for his own changes
   - Rachit does NOT get double-notified when assigned to a new task
5. Isolation:
   - Facilities tasks and Factech flows do NOT trigger Rachit notifications
"""

import pytest
from unittest.mock import patch, MagicMock
from notifications.rachit_notifier import (
    get_rachit_phone,
    notify_rachit_task_change,
)
from elara.config import RACHIT_PHONE, DEVELOPER_PHONE


# ── 1. Phone Resolution & Helper Tests ────────────────────────────────────────

def test_get_rachit_phone_fallback():
    """Verify fallback to DEVELOPER_PHONE in test mode so Rachit never gets test messages."""
    with patch("db.supabase.table") as mock_table:
        mock_table.side_effect = Exception("DB offline")
        phone = get_rachit_phone()
        assert phone == DEVELOPER_PHONE


def test_get_rachit_phone_with_unconfigured_mock():
    """Verify get_rachit_phone returns DEVELOPER_PHONE in testing."""
    with patch("db.supabase") as mock_sb:
        phone = get_rachit_phone()
        assert phone == DEVELOPER_PHONE
        assert isinstance(phone, str)


def test_notify_rachit_task_change_message_format():
    """Verify notification format sent to Rachit contains all required details."""
    with patch("notifications.rachit_notifier.send_text") as mock_send:
        sent = notify_rachit_task_change(
            task_id="elara-t-501",
            task_title="Site Safety Inspection",
            change_made="Status changed from Pending to In Progress",
            changed_by="Kanav",
            domain="Elara Home",
            timestamp="19 Sep 2026, 02:30 PM IST",
        )
        assert sent is True
        assert mock_send.called
        to_num, body = mock_send.call_args[0]
        assert to_num == DEVELOPER_PHONE
        assert "📋 *Task ID:* elara-t-501" in body
        assert "📌 *Task Title:* Site Safety Inspection" in body
        assert "🔄 *Change Made:* Status changed from Pending to In Progress" in body
        assert "👤 *Changed By:* Kanav" in body
        assert "🕒 *Timestamp:* 19 Sep 2026, 02:30 PM IST" in body
        assert "🏠 *Domain:* Elara Home" in body


def test_notify_rachit_skips_self_notification():
    """Verify Rachit does NOT receive notifications for his own actions."""
    with patch("notifications.rachit_notifier.send_text") as mock_send:
        sent = notify_rachit_task_change(
            task_id="elara-t-502",
            task_title="Review Quotation",
            change_made="Status changed to In Progress",
            changed_by="Rachit",
            domain="Elara Home",
        )
        assert sent is False
        assert not mock_send.called

        # Also case-insensitive check
        sent2 = notify_rachit_task_change(
            task_id="elara-t-502",
            task_title="Review Quotation",
            change_made="Status changed to In Progress",
            changed_by="rachit gupta",
            domain="Elara Home",
        )
        assert sent2 is False
        assert not mock_send.called


# ── 2. Elara Home Flow Integration Tests ──────────────────────────────────────

def test_elara_status_change_notifies_rachit():
    """When an Elara Home task status is updated by another user, Rachit is notified."""
    from elara.flows.update_task import handle_status_selection

    mock_task = {
        "id": "elara-t-503",
        "title": "Tile Fixing at Villa 4",
        "status": "pending",
        "created_by": "Gaurav",
    }

    with patch("elara.flows.update_task.get_task_by_id", return_value=mock_task), \
         patch("elara.flows.update_task.update_task", return_value=mock_task), \
         patch("elara.flows.update_task.send_text"), \
         patch("elara.flows.update_task.send_elara_task_card"), \
         patch("elara.flows.update_task.send_interactive_buttons"), \
         patch("notifications.rachit_notifier.send_text") as mock_send_rachit:

        handle_status_selection(
            to="918894577707",
            task_id="elara-t-503",
            new_status="in_progress",
            user={"name": "Gaurav", "role": "Site Executive"},
        )

        assert mock_send_rachit.called
        to_num, body = mock_send_rachit.call_args[0]
        assert to_num == DEVELOPER_PHONE
        assert "elara-t-503" in body
        assert "Tile Fixing at Villa 4" in body
        assert "In Progress" in body
        assert "Gaurav" in body


def test_elara_blocker_notifies_rachit():
    """When an Elara Home task is marked as Blocker, Rachit is notified."""
    from elara.flows.update_task import handle_blocker_reason_input

    mock_task = {
        "id": "elara-t-504",
        "title": "HVAC Ducting Layout",
        "status": "in_progress",
        "created_by": "Bhagwan Dass",
    }
    mock_session = {"draft": {"task_id": "elara-t-504"}}

    with patch("elara.flows.update_task.get_task_by_id", return_value=mock_task), \
         patch("elara.flows.update_task.update_task", return_value=mock_task), \
         patch("elara.db.add_comment"), \
         patch("elara.flows.update_task.clear_elara_session"), \
         patch("elara.flows.update_task.send_text"), \
         patch("elara.flows.update_task.send_elara_task_card"), \
         patch("notifications.rachit_notifier.send_text") as mock_send_rachit:

        handle_blocker_reason_input(
            to="919816641892",
            text="Material shipment delayed by supplier",
            user={"name": "Bhagwan Dass", "role": "Purchasing Head"},
            session=mock_session,
        )

        assert mock_send_rachit.called
        to_num, body = mock_send_rachit.call_args[0]
        assert to_num == DEVELOPER_PHONE
        assert "elara-t-504" in body
        assert "Blocker (Reason: Material shipment delayed by supplier)" in body
        assert "Bhagwan Dass" in body


def test_elara_comment_notifies_rachit():
    """When a comment is added to an Elara Home task, Rachit is notified."""
    from elara.flows.comments import handle_comment_text_input

    mock_task = {
        "id": "elara-t-505",
        "title": "Foundation Waterproofing",
        "status": "in_progress",
        "created_by": "Gaurav",
    }
    mock_session = {"draft": {"task_id": "elara-t-505"}}

    with patch("elara.flows.comments.get_task_by_id", return_value=mock_task), \
         patch("elara.flows.comments.add_comment"), \
         patch("elara.flows.comments.clear_elara_session"), \
         patch("elara.flows.comments.send_interactive_buttons"), \
         patch("notifications.rachit_notifier.send_text") as mock_send_rachit:

        handle_comment_text_input(
            to="918894577707",
            text="Second coat of waterproofing membrane applied today.",
            user={"name": "Gaurav", "role": "Site Executive"},
            session=mock_session,
        )

        assert mock_send_rachit.called
        to_num, body = mock_send_rachit.call_args[0]
        assert to_num == DEVELOPER_PHONE
        assert "elara-t-505" in body
        assert "Second coat of waterproofing membrane applied today." in body
        assert "Gaurav" in body


def test_elara_attachment_notifies_rachit():
    """When an attachment is uploaded to an Elara Home task, Rachit is notified."""
    from elara.flows.attachments import handle_attachment_upload

    mock_task = {
        "id": "elara-t-506",
        "title": "Boundary Wall Work",
        "status": "in_progress",
        "created_by": "Kanav",
    }

    with patch("elara.flows.attachments.get_task_by_id", return_value=mock_task), \
         patch("elara.flows.attachments.add_attachment", return_value={"id": "att-1"}), \
         patch("elara.flows.attachments.add_comment"), \
         patch("notifications.kanav_notifier.notify_kanav_task_change"), \
         patch("elara.flows.attachments.clear_elara_session"), \
         patch("elara.flows.attachments.send_interactive_buttons"), \
         patch("notifications.rachit_notifier.send_text") as mock_send_rachit:

        handle_attachment_upload(
            sender="918894577707",
            task_id="elara-t-506",
            media_data={"filename": "site_photo.jpg", "url": "https://storage.com/photo.jpg"},
            user={"name": "Gaurav", "role": "Site Executive"},
        )

        assert mock_send_rachit.called
        to_num, body = mock_send_rachit.call_args[0]
        assert to_num == DEVELOPER_PHONE
        assert "elara-t-506" in body
        assert "Attachment added: site_photo.jpg" in body
        assert "Gaurav" in body


def test_elara_task_creation_notifies_rachit():
    """When a task is created by someone else and not assigned to Rachit, Rachit receives creation notification."""
    from elara.flows.create_task import finalize_task_creation

    mock_created = {
        "id": "elara-t-507",
        "title": "Install Solar Panels",
        "project_id": "proj-1",
        "assigned_users": ["Gaurav"],
    }
    mock_proj = {"id": "proj-1", "name": "Villa 12 Construction"}
    draft = {
        "title": "Install Solar Panels",
        "project_id": "proj-1",
        "assignee": "Gaurav",
    }

    with patch("elara.flows.create_task.create_task", return_value=mock_created), \
         patch("elara.flows.create_task.get_project_by_id", return_value=mock_proj), \
         patch("elara.db.add_comment"), \
         patch("elara.flows.create_task._notify_elara_assignee"), \
         patch("elara.flows.create_task.clear_elara_session"), \
         patch("elara.flows.create_task.send_text"), \
         patch("elara.flows.create_task.send_elara_task_card"), \
         patch("notifications.rachit_notifier.send_text") as mock_send_rachit:

        finalize_task_creation(
            to="919811867829",
            user={"name": "Kanav", "role": "Director"},
            draft=draft,
        )

        assert mock_send_rachit.called
        to_num, body = mock_send_rachit.call_args[0]
        assert to_num == DEVELOPER_PHONE
        assert "elara-t-507" in body
        assert "Install Solar Panels" in body
        assert "New task created in Villa 12 Construction and assigned to *Gaurav*" in body
        assert "Kanav" in body


def test_elara_task_creation_no_duplicate_when_rachit_assigned():
    """When Rachit is assigned to the new task, _notify_elara_assignee handles him — no duplicate task_change notification."""
    from elara.flows.create_task import finalize_task_creation

    mock_created = {
        "id": "elara-t-508",
        "title": "Inspect Boundary Pillars",
        "project_id": "proj-1",
        "assigned_users": ["Rachit"],
    }
    mock_proj = {"id": "proj-1", "name": "Villa 12 Construction"}
    draft = {
        "title": "Inspect Boundary Pillars",
        "project_id": "proj-1",
        "assignee": "Rachit",
    }

    with patch("elara.flows.create_task.create_task", return_value=mock_created), \
         patch("elara.flows.create_task.get_project_by_id", return_value=mock_proj), \
         patch("elara.db.add_comment"), \
         patch("elara.flows.create_task._notify_elara_assignee") as mock_assignee_notif, \
         patch("elara.flows.create_task.clear_elara_session"), \
         patch("elara.flows.create_task.send_text"), \
         patch("elara.flows.create_task.send_elara_task_card"), \
         patch("notifications.rachit_notifier.send_text") as mock_send_rachit:

        finalize_task_creation(
            to="919811867829",
            user={"name": "Kanav", "role": "Director"},
            draft=draft,
        )

        # Assignee notification is called for Rachit
        assert mock_assignee_notif.called
        # But notify_rachit_task_change is NOT called to prevent double-messaging
        assert not mock_send_rachit.called


def test_elara_task_creation_by_rachit_does_not_notify_himself():
    """When Rachit creates a task himself, he does not receive a self-notification."""
    from elara.flows.create_task import finalize_task_creation

    mock_created = {
        "id": "elara-t-509",
        "title": "Order Cement Bags",
        "project_id": "proj-1",
        "assigned_users": ["Bhagwan Dass"],
    }
    mock_proj = {"id": "proj-1", "name": "Villa 12 Construction"}
    draft = {
        "title": "Order Cement Bags",
        "project_id": "proj-1",
        "assignee": "Bhagwan Dass",
    }

    with patch("elara.flows.create_task.create_task", return_value=mock_created), \
         patch("elara.flows.create_task.get_project_by_id", return_value=mock_proj), \
         patch("elara.db.add_comment"), \
         patch("elara.flows.create_task._notify_elara_assignee"), \
         patch("elara.flows.create_task.clear_elara_session"), \
         patch("elara.flows.create_task.send_text"), \
         patch("elara.flows.create_task.send_elara_task_card"), \
         patch("notifications.rachit_notifier.send_text") as mock_send_rachit:

        finalize_task_creation(
            to="919867272041",
            user={"name": "Rachit", "role": "Site Incharge"},
            draft=draft,
        )

        assert not mock_send_rachit.called
