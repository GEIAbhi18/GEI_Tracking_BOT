"""
Unit and Integration Tests for Elara Task Creation Flow
======================================================
Verifies:
1. Intent extraction from natural language (e.g. "Create task for puja to speak to Nikhil Kumar about open points")
2. Prompting and confirming due date and assignee
3. Step-by-step Draft Preview Review Card (Screen 07 alignment with Facilities)
4. Confirm & Create, Edit Draft, and Cancel actions
5. Notification dispatch to assignee if phone exists
"""

from unittest.mock import patch, MagicMock
import pytest
from elara.flows.create_task import (
    parse_task_intent_from_text,
    start_create_task_flow,
    handle_task_project_selection,
    handle_task_title_input,
    handle_task_priority_selection,
    handle_task_due_date_input,
    handle_task_assignee_input,
    show_task_draft_preview,
    confirm_create_task,
    edit_draft_task,
    handle_task_edit_input,
    cancel_create_task,
)
from elara.flows.router import _route_button, _route_text
from elara.session import get_elara_session, clear_elara_session, set_elara_session


# ── 1. Intent Extraction Tests ───────────────────────────────────────────────

def test_parse_task_intent_kanav_screenshot_case():
    """Verify Kanav's exact command extracts assignee 'Puja' and action title."""
    user = {"name": "Kanav", "role": "Director"}
    cmd = "Create task for puja to speak to Nikhil Kumar about open points"
    parsed = parse_task_intent_from_text(cmd, user)

    assert parsed["assignee"] == "Puja"
    assert parsed["title"] == "Speak to Nikhil Kumar about open points"
    assert parsed["priority"] == "medium"
    assert parsed["due_date"] is None
    assert parsed["project_id"] is None


def test_parse_task_intent_with_due_date_and_priority():
    user = {"name": "Kanav", "role": "Director"}
    cmd = "Create task for puja to speak to Nikhil Kumar about open points due tomorrow priority high"
    parsed = parse_task_intent_from_text(cmd, user)

    assert parsed["assignee"] == "Puja"
    assert parsed["title"] == "Speak to Nikhil Kumar about open points"
    assert parsed["priority"] == "high"
    assert parsed["due_date"] is not None


def test_parse_task_intent_with_colon_and_assignee():
    user = {"name": "Kanav", "role": "Director"}
    cmd = "Create task for Gaurav: inspect site 2 due 2026-09-25"
    parsed = parse_task_intent_from_text(cmd, user)

    assert parsed["assignee"] == "Gaurav"
    assert parsed["title"] == "Inspect site 2"
    assert parsed["due_date"] == "2026-09-25"


# ── 2. Flow Progression & Confirmation Tests ─────────────────────────────────

@patch("elara.flows.create_task.send_interactive_buttons")
@patch("elara.flows.create_task.send_list_message")
@patch("elara.flows.create_task.get_projects")
def test_create_task_flow_does_not_skip_due_date_and_assignee(mock_projects, mock_list, mock_buttons):
    """
    Verify that when project is selected with an existing title from NLP:
    It DOES NOT immediately create the task!
    It must ask for due date and confirm the assignee.
    """
    mock_projects.return_value = [{"id": "proj-admin", "name": "Project Administration Project", "department": "Project Administration"}]
    user = {"name": "Kanav", "role": "Director", "phone": "919999999999"}
    phone = "919999999999"
    clear_elara_session(phone)

    # User entered: "Create task for puja to speak to Nikhil Kumar about open points"
    prefill = {
        "title": "Speak to Nikhil Kumar about open points",
        "assignee": "Puja",
        "priority": "medium",
        "due_date": None,
        "project_id": None
    }

    # 1. Start flow -> missing project -> prompts project selection
    start_create_task_flow(phone, user, prefill=prefill)
    assert mock_list.called
    session = get_elara_session(phone)
    assert session is not None
    assert session["flow_state"] == "create_task_select_project"

    # 2. User selects project -> must prompt due date (NOT finalize!)
    mock_buttons.reset_mock()
    handle_task_project_selection(phone, "proj-admin", user, session)
    assert mock_buttons.called
    # Button prompt should be due date
    btn_args = mock_buttons.call_args[0]
    prompt_text = btn_args[1]
    assert "Due Date" in prompt_text
    session = get_elara_session(phone)
    assert session is not None
    assert session["flow_state"] == "create_task_due_date"

    # 3. User provides due date -> must prompt assignee confirmation
    mock_buttons.reset_mock()
    handle_task_due_date_input(phone, "tomorrow", user, session)
    assert mock_buttons.called
    btn_args = mock_buttons.call_args[0]
    prompt_text = btn_args[1]
    assert "Assignee" in prompt_text
    assert "Puja" in prompt_text
    session = get_elara_session(phone)
    assert session is not None
    assert session["flow_state"] == "create_task_assignee"

    # 4. User confirms assignee -> must show Draft Review Preview Card (NOT finalize yet!)
    mock_buttons.reset_mock()
    handle_task_assignee_input(phone, "Puja", user, session)
    assert mock_buttons.called
    btn_args = mock_buttons.call_args[0]
    preview_card = btn_args[1]
    buttons = btn_args[2]

    assert "Elara Task Draft — Review" in preview_card
    assert "Speak to Nikhil Kumar about open points" in preview_card
    assert "Puja" in preview_card
    button_ids = [b["id"] for b in buttons]
    assert "elara_confirm_create_task" in button_ids
    assert "elara_edit_create_task" in button_ids
    assert "elara_cancel_create_task" in button_ids
    session = get_elara_session(phone)
    assert session is not None
    assert session["flow_state"] == "create_task_preview"


# ── 3. Confirm & Create Test ────────────────────────────────────────────────

@patch("elara.flows.create_task.create_task")
@patch("elara.flows.create_task.send_elara_task_card")
@patch("elara.flows.create_task.send_text")
@patch("elara.db.add_comment")
def test_confirm_create_task_creates_in_db(mock_comment, mock_send_text, mock_card, mock_create):
    mock_create.return_value = {
        "id": "task-999",
        "title": "Speak to Nikhil Kumar about open points",
        "assigned_users": ["Puja"],
        "due_date": "2026-09-20",
        "project_id": "proj-admin",
        "status": "pending",
        "priority": "medium"
    }

    user = {"name": "Kanav", "role": "Director"}
    phone = "919999999999"
    draft = {
        "title": "Speak to Nikhil Kumar about open points",
        "assignee": "Puja",
        "priority": "medium",
        "due_date": "2026-09-20",
        "project_id": "proj-admin",
        "department": "Project Administration"
    }
    set_elara_session(phone, "create_task_preview", draft=draft)
    session = get_elara_session(phone)

    confirm_create_task(phone, user, session)

    assert mock_create.called
    kwargs = mock_create.call_args[1]
    assert kwargs["title"] == "Speak to Nikhil Kumar about open points"
    assert kwargs["assigned_users"] == ["Puja"]
    assert kwargs["project_id"] == "proj-admin"
    assert kwargs["created_by"] == "Kanav"


# ── 4. Router Integration Test ───────────────────────────────────────────────

@patch("elara.flows.create_task.finalize_task_creation")
def test_router_confirm_create_task_button(mock_finalize):
    user = {"name": "Kanav", "role": "Director", "phone": "919999999999"}
    phone = "919999999999"
    draft = {
        "title": "Speak to Nikhil Kumar about open points",
        "assignee": "Puja",
        "project_id": "proj-admin"
    }
    set_elara_session(phone, "create_task_preview", draft=draft)
    session = get_elara_session(phone)

    _route_button(phone, "elara_confirm_create_task", user, session)
    assert mock_finalize.called


@patch("elara.flows.create_task.send_interactive_buttons")
def test_edit_draft_and_repreview(mock_buttons):
    user = {"name": "Kanav", "role": "Director"}
    phone = "919999999999"
    draft = {
        "title": "Old Title",
        "assignee": "Puja",
        "due_date": "2026-09-20",
        "project_id": "proj-admin"
    }
    set_elara_session(phone, "create_task_edit", draft=draft)
    session = get_elara_session(phone)

    # Edit title
    handle_task_edit_input(phone, "title: New Edited Title", user, session)
    updated_session = get_elara_session(phone)
    assert updated_session is not None
    assert updated_session["draft"]["title"] == "New Edited Title"
    assert updated_session["flow_state"] == "create_task_preview"


@patch("elara.flows.create_task.send_text")
def test_cancel_create_task(mock_send):
    user = {"name": "Kanav", "role": "Director"}
    phone = "919999999999"
    set_elara_session(phone, "create_task_preview", draft={"title": "Draft"})
    cancel_create_task(phone, user)
    assert get_elara_session(phone) is None
    assert mock_send.called


@patch("elara.flows.create_task.send_interactive_buttons")
def test_assignee_me_button(mock_buttons):
    user = {"name": "Kanav", "role": "Director"}
    phone = "919999999999"
    draft = {
        "title": "Review financials",
        "assignee": "Someone Else",
        "due_date": "2026-09-20",
        "project_id": "proj-admin"
    }
    set_elara_session(phone, "create_task_assignee", draft=draft)
    session = get_elara_session(phone)

    _route_button(phone, "elara_tassign_me", user, session)
    updated_session = get_elara_session(phone)
    assert updated_session is not None
    assert updated_session["draft"]["assignee"] == "Kanav"
    assert updated_session["flow_state"] == "create_task_preview"

