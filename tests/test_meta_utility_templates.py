import pytest
from whatsapp.task_assignment import send_task_assignment_template, send_task_status_template
from whatsapp.handlers import handle_interactive_reply

def test_send_task_assignment_template_payload(mocker):
    mock_post = mocker.patch("whatsapp.task_assignment._post_wa", return_value=True)

    res = send_task_assignment_template(
        to_phone="+918595818474",
        member_name="Gautam",
        creator_name="Abhijeet",
        task_title="Testing Meta Template",
        due_date_str="10th August",
        task_id="task-999"
    )

    assert res is True
    mock_post.assert_called_once()
    payload = mock_post.call_args[0][0]

    assert payload["to"] == "918595818474"
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "task_assignment_notification"
    assert payload["template"]["language"]["code"] == "en"

    body_comp = next(c for c in payload["template"]["components"] if c["type"] == "body")
    params = [p["text"] for p in body_comp["parameters"]]
    assert params == ["Gautam", "Abhijeet", "Testing Meta Template", "10th August"]

    btn1 = next(c for c in payload["template"]["components"] if c.get("type") == "button" and c.get("index") == "0")
    btn2 = next(c for c in payload["template"]["components"] if c.get("type") == "button" and c.get("index") == "1")
    assert btn1["parameters"][0]["payload"] == "task_accept_task-999"
    assert btn2["parameters"][0]["payload"] == "task_reject_task-999"


def test_send_task_status_template_payload(mocker):
    mock_post = mocker.patch("whatsapp.task_assignment._post_wa", return_value=True)

    res = send_task_status_template(
        to_phone="+917717754421",
        creator_name="Abhijeet",
        assignee_name="Gautam",
        action_status="ACCEPTED",
        task_title="Testing Meta Template",
        due_date_str="10th August"
    )

    assert res is True
    mock_post.assert_called_once()
    payload = mock_post.call_args[0][0]

    assert payload["to"] == "917717754421"
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "task_status_update"
    assert payload["template"]["language"]["code"] == "en"

    body_comp = next(c for c in payload["template"]["components"] if c["type"] == "body")
    params = [p["text"] for p in body_comp["parameters"]]
    assert params == ["Abhijeet", "Gautam", "ACCEPTED", "Testing Meta Template", "10th August"]


def test_assignee_template_fallback_on_session_failure(mocker):
    mock_supabase = mocker.patch("whatsapp.handlers.supabase")
    mocker.patch("db.get_user_by_id", return_value={
        "id": "gautam-uuid",
        "name": "Gautam",
        "whatsapp_number": "918595818474"
    })

    mock_select = mocker.MagicMock()
    mock_select.data = [{"title": "Testing Meta Template", "deadline": "2026-08-10"}]
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_select
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = mocker.MagicMock()

    mocker.patch("whatsapp.handlers.send_text", return_value=True)
    # Simulate interactive buttons failing (recipient outside 24h window)
    mocker.patch("whatsapp.handlers.send_interactive_buttons", return_value=False)
    mock_template = mocker.patch("whatsapp.task_assignment.send_task_assignment_template", return_value=True)

    creator_user = {"id": "abhijeet-uuid", "name": "Abhijeet", "whatsapp_number": "917717754421"}

    handle_interactive_reply("917717754421", "assign_task_task-123_gautam-uuid", creator_user)

    mock_template.assert_called_once_with("918595818474", "Gautam", "Abhijeet", "Testing Meta Template", "2026-08-10", "task-123")


def test_creator_template_fallback_on_session_failure(mocker):
    mock_supabase = mocker.patch("whatsapp.handlers.supabase")
    mocker.patch("whatsapp.handlers.orchestrate_status_update")
    
    mock_task_row = mocker.MagicMock()
    mock_task_row.data = [{
        "title": "Testing Meta Template",
        "deadline": "2026-08-10",
        "created_by": "creator-uuid"
    }]
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_task_row
    
    mocker.patch("db.get_user_by_id", return_value={
        "id": "creator-uuid",
        "name": "Abhijeet",
        "whatsapp_number": "917717754421"
    })

    # Simulate freeform text fail to creator
    mocker.patch("whatsapp.handlers.send_text", side_effect=[True, False])
    mock_status_template = mocker.patch("whatsapp.task_assignment.send_task_status_template", return_value=True)

    assignee_user = {"id": "gautam-uuid", "name": "Gautam", "whatsapp_number": "918595818474"}

    handle_interactive_reply("918595818474", "task_accept_task-123", assignee_user)

    mock_status_template.assert_called_once_with("917717754421", "Abhijeet", "Gautam", "ACCEPTED", "Testing Meta Template", "2026-08-10")


def test_handle_template_button_webhook(mocker):
    from whatsapp.whatsapp_webhook import _handle_template_button
    mocker.patch("auth.middleware.authenticate_whatsapp_request", return_value={"id": "gautam-uuid", "name": "Gautam"})
    mock_handler = mocker.patch("whatsapp.handlers.handle_interactive_reply")

    msg = {
        "from": "918595818474",
        "type": "button",
        "button": {
            "text": "Accept",
            "payload": "task_accept_task-777"
        }
    }

    _handle_template_button("918595818474", msg)
    mock_handler.assert_called_once_with("918595818474", "task_accept_task-777", {"id": "gautam-uuid", "name": "Gautam"})
