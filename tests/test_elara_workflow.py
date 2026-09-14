"""
Elara Home Integration & Team Isolation Tests
=============================================
Verifies:
1. User identification (Elara users vs Facilities users)
2. Dual-access handling for Kanav (Director) and Developer (+91 77177 754421)
3. Kanav greeting showing both teams ("Hi" / "Hello")
4. Kanav ambiguous request team selection flow ([Facilities Team] / [Elara Home])
5. Team context persistence
6. The 6 canonical Elara Home departments
7. Elara project creation in elara_projects (no legacy projects leak)
8. Elara task creation in elara_tasks (no legacy tasks leak)
9. Elara task updates (in_progress, blocker, completed with completion date)
10. Multiple comments in elara_comments (never overwriting, Kanban sync)
11. Strict zero-cross-team data leakage
"""

import pytest
from unittest.mock import patch, MagicMock
from elara.config import ELARA_DEPARTMENTS, DEVELOPER_PHONE, KANAV_PHONE
from elara.auth import (
    resolve_elara_user, is_elara_user, is_elara_admin, can_access_department
)
from elara.db import (
    create_project, get_projects, get_project_by_id,
    create_task, get_tasks, get_task_by_id, update_task,
    add_comment, get_comments
)
from elara.team_router import (
    route_incoming_message, set_active_team, get_active_team,
    detect_team_intent_from_text, is_dual_access_user
)


# ── 1. User Identification & Team Separation Tests ───────────────────────────

def test_elara_user_identification():
    """Verify Elara-only team members are recognized from elara_users."""
    # Rachit
    rachit = resolve_elara_user("919867272041")
    assert rachit is not None
    assert rachit["name"] == "Rachit"
    assert rachit["department"] == "Construction & Design"
    assert rachit["team"] == "Elara Home"
    assert is_elara_user("919867272041") is True

    # Bhagwan Dass
    bd = resolve_elara_user("919816641892")
    assert bd is not None
    assert bd["name"] == "Bhagwan Dass"
    assert bd["department"] == "Finance & Procurement"

    # Gaurav
    gaurav = resolve_elara_user("918894577707")
    assert gaurav is not None
    assert gaurav["name"] == "Gaurav"
    assert gaurav["department"] == "Approvals & Compliance"


def test_dual_access_users():
    """Verify Kanav and Developer have dual access."""
    assert is_dual_access_user(KANAV_PHONE) is True
    assert is_dual_access_user(DEVELOPER_PHONE) is True

    kanav = resolve_elara_user(KANAV_PHONE)
    assert kanav is not None
    assert is_elara_admin(kanav) is True

    dev = resolve_elara_user(DEVELOPER_PHONE)
    assert dev is not None
    assert is_elara_admin(dev) is True


def test_facilities_user_not_elara():
    """Anoop is in Facilities only, not an Elara user."""
    anoop_wa = "919211501013"
    assert is_elara_user(anoop_wa) is False
    assert is_dual_access_user(anoop_wa) is False


# ── 2. The 6 Departments Verification ────────────────────────────────────────

def test_six_canonical_departments():
    """Verify exact 6 Elara Home departments."""
    expected = [
        "Sales & CRM",
        "Construction & Design",
        "Approvals & Compliance",
        "Finance & Procurement",
        "Marketing & Customer Experience",
        "Project Administration",
    ]
    assert len(ELARA_DEPARTMENTS) == 6
    for dept in expected:
        assert dept in ELARA_DEPARTMENTS


# ── 3. Kanav Greeting Shows Both Teams ───────────────────────────────────────

@patch("elara.team_router.send_team_selection_prompt")
def test_kanav_greeting_shows_both_teams(mock_prompt):
    """When Kanav sends 'hi' or 'hello', he must see options for both teams."""
    handled = route_incoming_message(KANAV_PHONE, text="hi")
    assert handled is True
    mock_prompt.assert_called_once()
    args, kwargs = mock_prompt.call_args
    assert args[0] == KANAV_PHONE
    assert "Which Team would you like to access today?" in kwargs["custom_body"]


# ── 4. Kanav Ambiguous Request Team Selection Flow ───────────────────────────

@patch("elara.team_router.send_team_selection_prompt")
def test_kanav_ambiguous_request_prompts_selection(mock_prompt):
    """Ambiguous task request from Kanav must prompt for team selection."""
    ambiguous_text = "Create a task to check the work tomorrow"
    handled = route_incoming_message(KANAV_PHONE, text=ambiguous_text)
    assert handled is True
    mock_prompt.assert_called_once_with(KANAV_PHONE)


@patch("whatsapp.ux.send_text")
@patch("elara.flows.router.route_elara_message")
def test_kanav_selects_elara_resumes_pending(mock_route_elara, mock_send_text):
    """When Kanav selects Elara Home, pending ambiguous request runs in Elara."""
    from elara.team_router import set_pending_action
    set_pending_action(KANAV_PHONE, "Create a task to check the work tomorrow")

    handled = route_incoming_message(KANAV_PHONE, button_id="team_sel_elara")
    assert handled is True
    assert get_active_team(KANAV_PHONE) == "elara"
    mock_route_elara.assert_called_once()
    _, kwargs = mock_route_elara.call_args
    assert kwargs["text"] == "Create a task to check the work tomorrow"


@patch("whatsapp.ux.send_text")
@patch("facilities.flows.router.route_facilities_message")
def test_kanav_selects_facilities_resumes_pending(mock_route_fac, mock_send_text):
    """When Kanav selects Facilities Team, pending ambiguous request runs in Facilities."""
    from elara.team_router import set_pending_action
    set_pending_action(KANAV_PHONE, "Create a task to check the work tomorrow")

    handled = route_incoming_message(KANAV_PHONE, button_id="team_sel_facilities")
    assert handled is True
    assert get_active_team(KANAV_PHONE) == "facilities"
    mock_route_fac.assert_called_once()
    _, kwargs = mock_route_fac.call_args
    assert kwargs["text"] == "Create a task to check the work tomorrow"


# ── 5. Intent Detection & Team Context Persistence ───────────────────────────

def test_detect_team_intent_explicit():
    """Explicit department/team words must route without ambiguity."""
    assert detect_team_intent_from_text("Create task under Sales & CRM for leads") == "elara"
    assert detect_team_intent_from_text("New project for Construction & Design") == "elara"
    assert detect_team_intent_from_text("Check AC cooling in GEBB1") == "facilities"
    assert detect_team_intent_from_text("Close GETT-015") == "facilities"
    assert detect_team_intent_from_text("Create a general task for tomorrow") is None


def test_team_context_persistence():
    """Once team is set, it persists for subsequent messages."""
    set_active_team(KANAV_PHONE, "elara")
    assert get_active_team(KANAV_PHONE) == "elara"

    set_active_team(KANAV_PHONE, "facilities")
    assert get_active_team(KANAV_PHONE) == "facilities"


# ── 6. Elara Project Creation & Retrieval ────────────────────────────────────

def test_elara_project_crud():
    """Create project in elara_projects and retrieve."""
    test_proj_name = "Automated Test Project"
    created = create_project(
        name=test_proj_name,
        department="Construction & Design",
        description="Automated unit test project"
    )

    assert created is not None
    assert created["name"] == test_proj_name
    assert created["department"] == "Construction & Design"
    assert created["team_name"] == "Elara Home"
    assert created["status"] == "Active"

    # Verify retrieval by ID
    fetched = get_project_by_id(created["id"])
    assert fetched is not None
    assert fetched["id"] == created["id"]


# ── 7. Elara Task Creation, Status Updates & Blocker ─────────────────────────

def test_elara_task_crud_and_status_update():
    """Create task in elara_tasks, update status, blocker, and completion."""
    projects = get_projects()
    assert len(projects) > 0
    project_id = projects[0]["id"]

    # 1. Create Task
    task = create_task(
        title="Automated Test Task Inspection",
        project_id=project_id,
        description="Inspect site setup",
        priority="high",
        due_date="2026-09-20T00:00:00Z",
        assigned_users=["Rachit"],
        status="pending"
    )

    assert task is not None
    assert task["title"] == "Automated Test Task Inspection"
    assert task["project_id"] == project_id
    assert task["status"] == "pending"
    assert task["priority"] == "high"
    assert "Rachit" in task["assigned_users"]

    task_id = task["id"]

    # 2. Update to In Progress
    updated = update_task(task_id, {"status": "in_progress", "progress": 40})
    assert updated is not None
    assert updated["status"] == "in_progress"
    assert updated["progress"] == 40
    assert updated["is_blocked"] is False

    # 3. Update to Blocker
    blocked = update_task(task_id, {"status": "blocker", "blocker_reason": "Waiting for cement delivery"})
    assert blocked is not None
    assert blocked["status"] == "blocker"
    assert blocked["is_blocked"] is True

    # 4. Update to Completed
    completed = update_task(task_id, {"status": "completed"})
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["progress"] == 100
    assert completed["actual_completion_date"] is not None


# ── 8. Multiple Comments in elara_comments (Never Overwriting) ───────────────

def test_elara_multiple_comments_never_overwrite():
    """Ensure multiple comments are saved separately in elara_comments and synced."""
    projects = get_projects()
    task = create_task(title="Comment Test Task", project_id=projects[0]["id"])
    task_id = task["id"]

    # Add Comment 1
    c1 = add_comment(task_id, user_name="Rachit", user_role="Team Member", content="First site report submitted.")
    assert c1 is not None
    assert c1["task_id"] == task_id
    assert c1["content"] == "First site report submitted."

    # Add Comment 2
    c2 = add_comment(task_id, user_name="Kanav", user_role="Director", content="Approved, proceed to phase 2.")
    assert c2 is not None
    assert c2["content"] == "Approved, proceed to phase 2."

    # Add Comment 3
    c3 = add_comment(task_id, user_name="Developer", user_role="Developer", content="Tested system sync.")
    assert c3 is not None
    assert c3["content"] == "Tested system sync."

    # Verify retrieval from elara_comments table
    all_comments = get_comments(task_id)
    assert len(all_comments) >= 3
    comment_texts = [c["content"] for c in all_comments]
    assert "First site report submitted." in comment_texts
    assert "Approved, proceed to phase 2." in comment_texts
    assert "Tested system sync." in comment_texts

    # Verify elara_tasks JSONB comments array also has all comments for Kanban sync
    refreshed_task = get_task_by_id(task_id)
    assert refreshed_task is not None
    task_comments = refreshed_task.get("comments") or []
    assert len(task_comments) >= 3


# ── 9. Zero Cross-Team Data Leaks ────────────────────────────────────────────

def test_zero_cross_team_data_leakage():
    """Verify Elara tasks and Facilities tasks never mix."""
    from db import supabase

    # 1. Check all elara_projects have team_name 'Elara Home'
    elara_projs = get_projects()
    for p in elara_projs:
        assert p.get("team_name") == "Elara Home"

    # 2. Legacy facilities queries only query 'tasks', never 'elara_tasks'
    elara_tasks = get_tasks()
    elara_task_ids = {t["id"] for t in elara_tasks}

    # Query legacy tasks
    res = supabase.table("tasks").select("id").execute()
    legacy_task_ids = {t["id"] for t in (res.data or [])}

    # Verify intersection is empty
    overlap = elara_task_ids.intersection(legacy_task_ids)
    assert len(overlap) == 0, f"Cross-team leakage detected! Shared task IDs: {overlap}"
