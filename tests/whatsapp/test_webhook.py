import pytest
import json
from whatsapp.whatsapp_webhook import app

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_webhook_verify_success(client, mocker):
    """Test Meta webhook verification GET request."""
    # We patch the VERIFY_TOKEN in the module
    mocker.patch("whatsapp.whatsapp_webhook.VERIFY_TOKEN", "test_token")
    
    response = client.get("/webhook?hub.mode=subscribe&hub.verify_token=test_token&hub.challenge=CHALLENGE_STRING")
    
    assert response.status_code == 200
    assert response.data.decode("utf-8") == "CHALLENGE_STRING"

def test_webhook_verify_failure(client, mocker):
    """Test Meta webhook verification fails with wrong token."""
    mocker.patch("whatsapp.whatsapp_webhook.VERIFY_TOKEN", "test_token")
    
    response = client.get("/webhook?hub.mode=subscribe&hub.verify_token=wrong_token&hub.challenge=CHALLENGE_STRING")
    
    assert response.status_code == 403

def test_webhook_post_text_message(client, mocker):
    """Test incoming text message."""
    mock_thread = mocker.patch("threading.Thread")
    
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "1234567890",
                        "type": "text",
                        "text": {"body": "hello"}
                    }]
                }
            }]
        }]
    }
    
    response = client.post("/webhook", json=payload)
    
    assert response.status_code == 200
    assert json.loads(response.data) == {"status": "ok"}
    # Verify thread was spawned to process it
    mock_thread.assert_called()

def test_webhook_post_interactive_reply(client, mocker):
    """Test incoming interactive message (button reply)."""
    mock_thread = mocker.patch("threading.Thread")
    
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "1234567890",
                        "type": "interactive",
                        "interactive": {
                            "type": "button_reply",
                            "button_reply": {"id": "test_button"}
                        }
                    }]
                }
            }]
        }]
    }
    
    response = client.post("/webhook", json=payload)
    
    assert response.status_code == 200
    assert json.loads(response.data) == {"status": "ok"}
    # Verify thread was spawned to process the interactive reply
    mock_thread.assert_called()

def test_webhook_post_audio_message(client, mocker):
    """Test incoming audio message."""
    mock_thread = mocker.patch("threading.Thread")
    
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "1234567890",
                        "type": "audio",
                        "audio": {"id": "audio_123"}
                    }]
                }
            }]
        }]
    }
    
    response = client.post("/webhook", json=payload)
    
    assert response.status_code == 200
    assert json.loads(response.data) == {"status": "ok"}
    mock_thread.assert_called()

def test_handle_interactive_reply_my_tasks(mocker):
    """Test menu_my_tasks sends reply text via WhatsApp send_text."""
    mock_send_text = mocker.patch("whatsapp.handlers.send_text")
    mocker.patch("core.intent_handlers.get_all_tasks", return_value=[])
    mocker.patch("core.intent_handlers._resolve_user", return_value={"id": "user-123", "name": "Abhijeet", "role": "Developer"})
    mocker.patch("db.get_tasks_by_buildings", return_value=[])
    mocker.patch("db.get_user_buildings", return_value=[])
    
    from whatsapp.handlers import handle_interactive_reply
    user = {"id": "user-123", "name": "Abhijeet", "role": "Developer"}
    handle_interactive_reply("+919876543210", "menu_my_tasks", user)
    
    mock_send_text.assert_called_once_with("+919876543210", "👤 *My Personal Tasks*\n\nNo personal tasks currently assigned.")

def test_handle_interactive_reply_team_tasks(mocker):
    """Test menu_team_tasks sends reply text via WhatsApp send_text."""
    mock_send_text = mocker.patch("whatsapp.handlers.send_text")
    mocker.patch("core.intent_handlers.get_all_tasks", return_value=[])
    mocker.patch("core.intent_handlers._resolve_user", return_value={"id": "user-123", "name": "Abhijeet", "role": "Developer"})
    mocker.patch("db.get_tasks_by_buildings", return_value=[])
    mocker.patch("db.get_user_buildings", return_value=[])
    
    from whatsapp.handlers import handle_interactive_reply
    user = {"id": "user-123", "name": "Abhijeet", "role": "Developer"}
    handle_interactive_reply("+919876543210", "menu_team_tasks", user)
    
    mock_send_text.assert_called_once_with("+919876543210", "📋 *Team Tasks*\n\nNo team tasks currently assigned for your assigned buildings.")

def test_team_task_scoping_for_team_members(mocker):
    """Test team members only see tasks matching their team_id while Developer sees all."""
    mock_send_text = mocker.patch("whatsapp.handlers.send_text")
    mock_tasks = [
        {"id": "t1", "name": "Facilities Repair", "task_type": "TEAM", "team_id": "facilities-123"},
        {"id": "t2", "name": "IT Server Maintenance", "task_type": "TEAM", "team_id": "it-456"}
    ]
    mocker.patch("db.get_all_tasks", return_value=mock_tasks)
    mocker.patch("core.intent_handlers.get_all_tasks", return_value=mock_tasks)
    
    # 1. Non-developer Facilities member should only see facilities task (t1)
    mocker.patch("core.intent_handlers._resolve_user", return_value={"id": "user-fac", "name": "Facilities Member", "role": "Employee", "team_id": "facilities-123"})
    from whatsapp.handlers import handle_interactive_reply
    user = {"id": "user-fac", "name": "Facilities Member", "role": "Employee", "team_id": "facilities-123"}
    handle_interactive_reply("+919800000001", "menu_team_tasks", user)
    
def test_handle_interactive_reply_reports_developer(mocker):
    """Test menu_reports triggers PDF generation and sending for Developer/Director roles."""
    mock_send_text = mocker.patch("whatsapp.handlers.send_text")
    mock_send_doc = mocker.patch("whatsapp.task_assignment._send_document_wa")
    mocker.patch("core.intent_handlers.generate_pdf_report", return_value="/tmp/test_report.pdf")
    
    from whatsapp.handlers import handle_interactive_reply
    user = {"id": "dev-1", "name": "Abhijeet", "role": "Developer"}
    handle_interactive_reply("+919876543210", "menu_reports", user)
    
    mock_send_doc.assert_called_once_with("+919876543210", "/tmp/test_report.pdf")
    assert mock_send_text.call_count >= 1

def test_handle_interactive_reply_reports_employee(mocker):
    """Test menu_reports sends permission notice for non-Developer/Director roles."""
    mock_send_text = mocker.patch("whatsapp.handlers.send_text")
    mock_send_doc = mocker.patch("whatsapp.task_assignment._send_document_wa")
    
    from whatsapp.handlers import handle_interactive_reply
    user = {"id": "emp-1", "name": "Employee User", "role": "Employee"}
    handle_interactive_reply("+919876543210", "menu_reports", user)
    
    mock_send_doc.assert_not_called()
    mock_send_text.assert_called_once()
    assert "reserved for Directors" in mock_send_text.call_args[0][1]

def test_handle_interactive_reply_analytics_options(mocker):
    """Test menu_analytics sends interactive buttons with Team and Personal options."""
    mock_send_buttons = mocker.patch("whatsapp.handlers.send_interactive_buttons")
    
    from whatsapp.handlers import handle_interactive_reply
    user = {"id": "user-1", "name": "Abhijeet", "role": "Developer"}
    handle_interactive_reply("+919876543210", "menu_analytics", user)
    
    mock_send_buttons.assert_called_once()
    args, _ = mock_send_buttons.call_args
    assert args[0] == "+919876543210"
    assert "analytics_team" in [b["id"] for b in args[2]]
    assert "analytics_personal" in [b["id"] for b in args[2]]

def test_handle_interactive_reply_analytics_team(mocker):
    """Test analytics_team renders person-wise task breakdown."""
    mock_send_text = mocker.patch("whatsapp.handlers.send_text")
    mock_tasks = [
        {"id": "t1", "name": "Task A", "task_type": "TEAM", "status": "Completed", "progress": 100, "assigned_to_user": {"name": "Asif"}},
        {"id": "t2", "name": "Task B", "task_type": "TEAM", "status": "In Progress", "progress": 40, "blocker_reason": "Material delay", "assigned_to_user": {"name": "Asif"}},
        {"id": "t3", "name": "Task C", "task_type": "TEAM", "status": "Pending", "progress": 0, "assigned_to_user": {"name": "Abhijeet"}}
    ]
    mocker.patch("db.get_all_tasks", return_value=mock_tasks)
    
    from whatsapp.handlers import handle_interactive_reply
    user = {"id": "dev-1", "name": "Abhijeet", "role": "Developer"}
    handle_interactive_reply("+919876543210", "analytics_team", user)
    
    mock_send_text.assert_called_once()
    output = mock_send_text.call_args[0][1]
    assert "Person-Wise Breakdown" in output
    assert "Asif" in output
    assert "Abhijeet" in output
    assert "Completed: 1" in output or "Done: 1" in output
    assert "Blocked: 1" in output

def test_handle_interactive_reply_analytics_personal(mocker):
    """Test analytics_personal renders user's personal task stats."""
    mock_send_text = mocker.patch("whatsapp.handlers.send_text")
    mock_tasks = [
        {"id": "pt1", "name": "Personal Task 1", "task_type": "PERSONAL", "status": "Completed", "progress": 100, "assigned_to": "dev-1"},
        {"id": "pt2", "name": "Personal Task 2", "task_type": "PERSONAL", "status": "In Progress", "progress": 50, "assigned_to": "dev-1"}
    ]
    mocker.patch("db.get_all_tasks", return_value=mock_tasks)
    
    from whatsapp.handlers import handle_interactive_reply
    user = {"id": "dev-1", "name": "Abhijeet", "role": "Developer"}
    handle_interactive_reply("+919876543210", "analytics_personal", user)
    
    mock_send_text.assert_called_once()
def test_system_admin_menu_visibility_only_for_developer(mocker):
    """Test that System Admin menu option is strictly shown ONLY to Developer role."""
    mock_send_list = mocker.patch("whatsapp.menus.send_list_message")
    from whatsapp.menus import send_main_menu
    
    # 1. Developer user -> should have System Admin
    dev_user = {"id": "dev-1", "name": "Abhijeet", "role": "Developer"}
    send_main_menu("+919876543210", dev_user)
    sections = mock_send_list.call_args[0][3]
    row_ids = [r["id"] for r in sections[0]["rows"]]
    assert "menu_admin" in row_ids
    
    # 2. Director user -> MUST NOT have System Admin
    mock_send_list.reset_mock()
    dir_user = {"id": "dir-1", "name": "Kanav", "role": "Director"}
    send_main_menu("+919876543210", dir_user)
    sections = mock_send_list.call_args[0][3]
    row_ids = [r["id"] for r in sections[0]["rows"]]
    assert "menu_admin" not in row_ids
    
    # 3. Employee user -> MUST NOT have System Admin
    mock_send_list.reset_mock()
    emp_user = {"id": "emp-1", "name": "Asif", "role": "Employee"}
    send_main_menu("+919876543210", emp_user)
    sections = mock_send_list.call_args[0][3]
    row_ids = [r["id"] for r in sections[0]["rows"]]
    assert "menu_admin" not in row_ids
    
    # 4. Guest user -> MUST NOT have System Admin (unless original_role is Developer)
    mock_send_list.reset_mock()
    guest_user = {"id": "g-1", "name": "Visitor", "role": "Guest"}
    send_main_menu("+919876543210", guest_user)
    sections = mock_send_list.call_args[0][3]
    row_ids = [r["id"] for r in sections[0]["rows"]]
    assert "menu_admin" not in row_ids

def test_add_task_fallback_project_id(mocker):
    """Test that add_task uses fallback project_id when project_id is None."""
    mock_supabase = mocker.patch("db.supabase")
    mocker.patch("db.get_projects", return_value=[{"id": "p-default-123", "name": "General Project"}])
    mock_insert = mock_supabase.table.return_value.insert
    mock_insert.return_value.execute.return_value.data = [{"id": "t-100", "title": "Test Task"}]
    
    from db import add_task
    res = add_task(project_id=None, name="Testing Fallback", task_type="PERSONAL")
    
    assert res is not None
    inserted_data = mock_insert.call_args[0][0]
    assert inserted_data["project_id"] == "p-default-123"

def test_create_team_task_assignment_and_notification(mocker):
    """Test Team Task creation sends interactive Accept/Reject buttons to assigned member when assigned by someone else."""
    mock_send_text = mocker.patch("whatsapp.handlers.send_text")
    mock_send_buttons = mocker.patch("whatsapp.handlers.send_interactive_buttons")
    mock_supabase = mocker.patch("whatsapp.handlers.supabase")
    
    # Mock user resolution for assignee (Vikas)
    mocker.patch("db.get_user_by_id", return_value={"id": "vikas-uuid", "name": "Vikas", "whatsapp_number": "+919800000002"})
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{}]
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{"title": "Pay water bill", "deadline": "2026-08-10"}]
    
    from whatsapp.handlers import handle_interactive_reply
    creator_user = {"id": "kanav-uuid", "name": "Kanav", "role": "Director"}
    
    # Trigger assign_task button click (Kanav assigns to Vikas)
    handle_interactive_reply("+919876543210", "assign_task_task-99_vikas-uuid", creator_user)
    
    # Creator gets text confirmation
    call_args_list = [c[0] for c in mock_send_text.call_args_list]
    phones = [c[0] for c in call_args_list]
    assert "+919876543210" in phones # Creator phone
    
    # Assignee gets interactive buttons (Accept / Reject) with task title, creator name, and due date
    mock_send_buttons.assert_called_once()
    btn_args = mock_send_buttons.call_args[0]
    assert btn_args[0] in ["919800000002", "+919800000002"]
    assert "Kanav" in btn_args[1]
    assert "Pay water bill" in btn_args[1]
    assert "2026-08-10" in btn_args[1]
    button_list = mock_send_buttons.call_args[0][2]
    assert any(b["id"] == "task_accept_task-99" for b in button_list)
    assert any(b["id"] == "task_reject_task-99" for b in button_list)


def test_task_accept_notifies_creator(mocker):
    """Test clicking Accept updates task status and sends notification to creator with due date."""
    mock_send_text = mocker.patch("whatsapp.handlers.send_text")
    mock_supabase = mocker.patch("whatsapp.handlers.supabase")
    mocker.patch("tasks.service.validate_status_transition", return_value=(True, None))
    mocker.patch("tasks.service.get_task_by_id", return_value={"id": "task-99", "status": "Pending"})
    mocker.patch("tasks.service.update_task", return_value={"id": "task-99", "status": "Accepted"})
    mocker.patch("tasks.service.add_timeline_event")

    mocker.patch("db.get_user_by_id", return_value={"id": "kanav-uuid", "name": "Kanav", "whatsapp_number": "+919876543210"})
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{
        "title": "Pay water bill",
        "deadline": "2026-08-10",
        "assigned_by": "kanav-uuid"
    }]

    from whatsapp.handlers import handle_interactive_reply
    assignee_user = {"id": "vikas-uuid", "name": "Vikas", "role": "Employee"}

    handle_interactive_reply("+919800000002", "task_accept_task-99", assignee_user)

    call_args_list = [c[0] for c in mock_send_text.call_args_list]
    phones = [c[0] for c in call_args_list]
    messages = [c[1] for c in call_args_list]

    assert "+919800000002" in phones # Assignee text confirmation
    assert "+919876543210" in phones # Creator notification
    creator_msg = [m for p, m in zip(phones, messages) if p == "+919876543210"][0]
    assert "Task Accepted!" in creator_msg
    assert "Vikas" in creator_msg
    assert "Pay water bill" in creator_msg
    assert "2026-08-10" in creator_msg


def test_handle_interactive_reply_update_task(mocker):
    """Test menu_update_task presents Personal Task and Team Task options."""
    mock_send_buttons = mocker.patch("whatsapp.handlers.send_interactive_buttons")
    from whatsapp.handlers import handle_interactive_reply
    user = {"id": "user-123", "name": "Abhijeet", "role": "Developer"}
    handle_interactive_reply("+919876543210", "menu_update_task", user)
    
    mock_send_buttons.assert_called_once()
    args = mock_send_buttons.call_args[0]
    assert args[0] == "+919876543210"
    assert "Which task list would you like to update?" in args[1]
    assert any(b["id"] == "update_task_personal" for b in args[2])
    assert any(b["id"] == "update_task_team" for b in args[2])


def test_handle_interactive_reply_update_task_personal(mocker):
    """Test update_task_personal displays numbered personal tasks and sets WA state."""
    mock_send_text = mocker.patch("whatsapp.handlers.send_text")
    mock_set_state = mocker.patch("whatsapp.handlers.set_wa_state")
    mock_auth = mocker.patch("auth.middleware.authenticate_whatsapp_request", return_value={"id": "user-123", "name": "Abhijeet"})
    
    mock_table = mocker.patch("whatsapp.handlers.supabase.table")
    mock_table.return_value.select.return_value.neq.return_value.execute.return_value.data = [
        {"id": "t-1", "title": "Personal Task 1", "task_type": "PERSONAL", "created_by": "user-123", "progress": 20, "status": "Pending"},
        {"id": "t-2", "title": "Personal Task 2", "task_type": "PERSONAL", "created_by": "user-123", "progress": 50, "status": "In Progress"}
    ]
    
    from whatsapp.handlers import handle_interactive_reply
    user = {"id": "user-123", "name": "Abhijeet", "role": "Developer"}
    handle_interactive_reply("+919876543210", "update_task_personal", user)
    
    mock_send_text.assert_called_once()
    msg = mock_send_text.call_args[0][1]
    assert "Select a Personal Task to Update" in msg
    assert "1. *Personal Task 1*" in msg
    assert "2. *Personal Task 2*" in msg
    mock_set_state.assert_called_once_with("+919876543210", "WAITING_FOR_TASK_UPDATE", metadata={"task_id": "t-1"})


def test_handle_direct_task_update_text_and_voice(mocker):
    """Test typing update like '1 75% done' updates task and sends confirmation."""
    mock_send_text = mocker.patch("whatsapp.handlers.send_text")
    mock_save_update = mocker.patch("db.save_update")
    
    mock_table = mocker.patch("whatsapp.handlers.supabase.table")
    mock_table.return_value.select.return_value.execute.return_value.data = [
        {"id": "t-1", "title": "Personal Task 1", "progress": 20, "status": "Pending"},
        {"id": "t-2", "title": "Personal Task 2", "progress": 50, "status": "In Progress"}
    ]
    
    from core.context_manager import update_context
    update_context("+919876543210", last_task_list=["t-1", "t-2"])
    
    from whatsapp.handlers import handle_direct_task_update
    user_info = {"id": "user-123", "name": "Abhijeet"}
    
    res = handle_direct_task_update("+919876543210", "1 75% done", user_info)
    assert res is True
    mock_save_update.assert_called_once_with("t-1", 75, "None", [], "user-123", note=None)
    
    mock_send_text.assert_called_once()
    reply = mock_send_text.call_args[0][1]
    assert "Personal Task 1" in reply
    assert "Would you like to add any notes or comments" in reply


def test_task_completion_flow_no_image_with_comment(mocker):
    """Test completing a task: selecting No image, typing a comment, saving to daily report (save_update) and completing."""
    mock_send_text = mocker.patch("whatsapp.handlers.send_text")
    mock_send_buttons = mocker.patch("whatsapp.handlers.send_interactive_buttons")
    mock_set_state = mocker.patch("whatsapp.handlers.set_wa_state")

    from whatsapp.handlers import handle_interactive_reply
    user_info = {"id": "user-123", "name": "Abhijeet"}

    # 1. Click complete button
    handle_interactive_reply("+919876543210", "task_complete_task-123", user_info)
    mock_send_buttons.assert_called_once()
    mock_set_state.assert_called_with("+919876543210", "WAITING_FOR_COMPLETION_IMAGE_DECISION", metadata={"task_id": "task-123"})

    # 2. Click No image
    handle_interactive_reply("+919876543210", "complete_img_no_task-123", user_info)
    mock_set_state.assert_called_with("+919876543210", "WAITING_FOR_COMPLETION_COMMENT", metadata={"task_id": "task-123"})
    assert any("Would you like to add a final comment" in c[0][1] for c in mock_send_text.call_args_list)


def test_handle_direct_task_update_completed_triggers_flow(mocker):
    """Test typing '1 completed' initiates completion flow (asking for proof image decision)."""
    mock_send_buttons = mocker.patch("whatsapp.handlers.send_interactive_buttons")
    mock_set_state = mocker.patch("whatsapp.handlers.set_wa_state")

    mock_table = mocker.patch("whatsapp.handlers.supabase.table")
    mock_table.return_value.select.return_value.execute.return_value.data = [
        {"id": "t-100", "title": "GEI BOT Testing", "progress": 0, "status": "Pending"}
    ]

    from core.context_manager import update_context
    update_context("+919876543210", last_task_list=["t-100"])

    from whatsapp.handlers import handle_direct_task_update
    user_info = {"id": "user-123", "name": "Abhijeet"}

    res = handle_direct_task_update("+919876543210", "1 completed", user_info)
    assert res is True
    mock_send_buttons.assert_called_once()
    mock_set_state.assert_called_once_with(
        "+919876543210",
        "WAITING_FOR_COMPLETION_IMAGE_DECISION",
        metadata={"task_id": "t-100"}
    )


def test_handle_image_proof_upload(mocker):
    """Test receiving an image message advances state to WAITING_FOR_COMPLETION_COMMENT."""
    mocker.patch("auth.middleware.authenticate_whatsapp_request", return_value={"id": "user-123"})
    mock_send_text = mocker.patch("whatsapp.whatsapp_webhook.send_text")

    mock_table = mocker.patch("db.supabase.table")
    mock_table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"whatsapp_number": "+919876543210", "action": "WAITING_FOR_COMPLETION_IMAGE", "task_id": "task-123"}
    ]

    from whatsapp.whatsapp_webhook import _handle_image
    msg_payload = {
        "image": {"id": "img-media-123", "caption": ""}
    }

    _handle_image("+919876543210", msg_payload)
    mock_send_text.assert_called_once()
    reply = mock_send_text.call_args[0][1]
    assert "Image proof received!" in reply




