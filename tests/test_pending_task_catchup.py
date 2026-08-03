import pytest
from unittest.mock import MagicMock
from whatsapp.task_assignment import check_and_deliver_pending_task_notifications

def test_check_and_deliver_pending_task_notifications(mocker):
    mock_supabase = mocker.patch("db.supabase")
    mock_send_buttons = mocker.patch("whatsapp.ux.send_interactive_buttons", return_value=True)

    gautam_user = {
        "id": "gautam-uuid",
        "name": "Gautam",
        "whatsapp_number": "918595818474"
    }

    mock_tasks = [
        {
            "id": "task-testing-2",
            "title": "Testing two",
            "deadline": "2026-08-04",
            "assigned_to": "gautam-uuid",
            "assigned_by": "creator-uuid",
            "assignment_status": "pending_acceptance",
            "status": "Pending",
            "creator": {"name": "Abhijeet"}
        }
    ]

    mock_res = MagicMock()
    mock_res.data = mock_tasks
    mock_supabase.table.return_value.select.return_value.eq.return_value.neq.return_value.execute.return_value = mock_res

    check_and_deliver_pending_task_notifications(gautam_user)

    # Verify interactive buttons (Accept / Reject) sent to Gautam
    mock_send_buttons.assert_called_once()
    btn_to = mock_send_buttons.call_args[0][0]
    btn_body = mock_send_buttons.call_args[0][1]
    assert btn_to == "918595818474"
    assert "Testing two" in btn_body
    assert "Abhijeet" in btn_body
