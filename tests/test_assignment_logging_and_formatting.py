import pytest
from db import get_user_by_name
from whatsapp.ux import clean_phone_number
from whatsapp.handlers import handle_interactive_reply

def test_clean_phone_number():
    assert clean_phone_number("+919996221554") == "919996221554"
    assert clean_phone_number("9996221554") == "919996221554"
    assert clean_phone_number("919996221554") == "919996221554"
    assert clean_phone_number("+91 999 622 1554") == "919996221554"
    assert clean_phone_number("") == ""

def test_get_user_by_name_vikas_alias(mocker):
    mock_supabase = mocker.patch("db.supabase")
    
    first_res = mocker.MagicMock()
    first_res.data = []
    second_res = mocker.MagicMock()
    second_res.data = [{"id": "vikas-uuid", "name": "Vikash", "whatsapp_number": "919996221554"}]
    
    execute_mock = mocker.MagicMock()
    execute_mock.execute.side_effect = [first_res, second_res]
    mock_supabase.table.return_value.select.return_value.ilike.return_value = execute_mock

    user = get_user_by_name("Vikas")
    assert user is not None
    assert user["name"] == "Vikash"

def test_task_assignment_logger_and_fallback(mocker, caplog):
    import logging
    mock_supabase = mocker.patch("whatsapp.handlers.supabase")
    mocker.patch("db.get_user_by_id", return_value={
        "id": "gautam-uuid",
        "name": "Gautam",
        "whatsapp_number": "8595818474"
    })
    
    mock_select = mocker.MagicMock()
    mock_select.data = [{"title": "Notification testing", "deadline": "2026-08-10"}]
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_select
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = mocker.MagicMock()

    mock_send_text = mocker.patch("whatsapp.handlers.send_text", return_value=True)
    # Simulate interactive buttons failing (e.g. outside 24h window), triggering template fallback
    mock_send_buttons = mocker.patch("whatsapp.handlers.send_interactive_buttons", return_value=False)
    mock_send_template = mocker.patch("whatsapp.task_assignment.send_task_assignment_template", return_value=True)

    creator_user = {"id": "abhijeet-uuid", "name": "Abhijeet", "whatsapp_number": "917717754421"}

    with caplog.at_level(logging.INFO):
        handle_interactive_reply("917717754421", "assign_task_task-123_gautam-uuid", creator_user)

    # Verify template fallback message sent when buttons return False
    mock_send_template.assert_called_once_with("918595818474", "Gautam", "Abhijeet", "Notification testing", "2026-08-10", "task-123")

    # Verify required backend log message
    expected_log = "WhatsApp message for task acceptance has been sent to Gautam (918595818474) for task 'Notification testing' (ID: task-123)"
    assert any(expected_log in record.message for record in caplog.records)
