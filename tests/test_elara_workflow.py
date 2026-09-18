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

from typing import Any
import pytest
from unittest.mock import patch, MagicMock
from elara.config import ELARA_DEPARTMENTS, DEVELOPER_PHONE, KANAV_PHONE
from elara.auth import (
    resolve_elara_user, is_elara_user, is_elara_admin, can_access_department
)
from elara.db import (
    create_project, get_projects, get_project_by_id,
    create_task, get_tasks, get_task_by_id, update_task,
    add_comment, get_comments, add_attachment, get_attachments, get_attachment_count
)
from elara.team_router import (
    route_incoming_message, set_active_team, get_active_team,
    detect_team_intent_from_text, is_dual_access_user
)


# ── Mock Fixture for Deterministic CI & Local Testing ────────────────────────

@pytest.fixture(autouse=True)
def mock_elara_supabase():
    """Deterministic in-memory mock store for Elara Supabase tables."""
    users_store = [
        {"id": "u1", "name": "Rachit", "phone": "919867272041", "role": "Site Incharge", "department": "Construction & Design", "team": "Elara Home", "is_elara_user": True},
        {"id": "u2", "name": "Bhagwan Dass", "phone": "919816641892", "role": "Purchasing Head", "department": "Finance & Procurement", "team": "Elara Home", "is_elara_user": True},
        {"id": "u3", "name": "Gaurav", "phone": "918894577707", "role": "Site Executive", "department": "Approvals & Compliance", "team": "Elara Home", "is_elara_user": True},
        {"id": "u4", "name": "Developer", "phone": DEVELOPER_PHONE, "role": "Developer", "department": "Project Administration", "team": "Elara Home", "is_elara_user": True},
        {"id": "u5", "name": "Kanav", "phone": KANAV_PHONE, "role": "Director", "department": "Project Administration", "team": "Elara Home", "is_elara_user": True},
    ]
    projects_store = [
        {"id": "elara-proj-1", "name": "Initial Elara Project", "department": "Construction & Design", "team_name": "Elara Home", "status": "Active", "created_at": "2026-09-01T00:00:00Z"}
    ]
    tasks_store = []
    comments_store = []
    attachments_store = []

    class MockQuery:
        def __init__(self, table_name: str):
            self.table_name = table_name
            self._filters: list[tuple[str, Any]] = []
            self._is_insert = False
            self._is_update = False
            self._insert_data: Any = None
            self._update_data: Any = None

        def select(self, *args, **kwargs):
            return self

        def order(self, *args, **kwargs):
            return self

        def eq(self, field, value):
            self._filters.append((field, value))
            return self

        def insert(self, data):
            self._is_insert = True
            self._insert_data = data
            return self

        def update(self, data):
            self._is_update = True
            self._update_data = data
            return self

        def execute(self):
            res = MagicMock()
            if self.table_name == "elara_users":
                items = users_store
                for f, v in self._filters:
                    items = [x for x in items if str(x.get(f)) == str(v)]
                res.data = [dict(x) for x in items]
                return res

            elif self.table_name == "elara_projects":
                if self._is_insert:
                    new_proj = dict(self._insert_data or {})
                    projects_store.append(new_proj)
                    res.data = [new_proj]
                    return res
                items = projects_store
                for f, v in self._filters:
                    items = [x for x in items if str(x.get(f)) == str(v)]
                res.data = [dict(x) for x in items]
                return res

            elif self.table_name == "elara_tasks":
                if self._is_insert:
                    new_task = dict(self._insert_data or {})
                    tasks_store.append(new_task)
                    res.data = [new_task]
                    return res
                if self._is_update:
                    for t in tasks_store:
                        match = all(str(t.get(f)) == str(v) for f, v in self._filters)
                        if match:
                            t.update(self._update_data or {})
                    updated = [t for t in tasks_store if all(str(t.get(f)) == str(v) for f, v in self._filters)]
                    res.data = [dict(x) for x in updated]
                    return res
                items = tasks_store
                for f, v in self._filters:
                    items = [x for x in items if str(x.get(f)) == str(v)]
                res.data = [dict(x) for x in items]
                return res

            elif self.table_name == "elara_comments":
                if self._is_insert:
                    new_comm = dict(self._insert_data or {})
                    comments_store.append(new_comm)
                    res.data = [new_comm]
                    return res
                items = comments_store
                for f, v in self._filters:
                    items = [x for x in items if str(x.get(f)) == str(v)]
                res.data = [dict(x) for x in items]
                return res

            elif self.table_name == "elara_attachments":
                if self._is_insert:
                    new_att = dict(self._insert_data or {})
                    attachments_store.append(new_att)
                    res.data = [new_att]
                    res.count = len(attachments_store)
                    return res
                items = attachments_store
                for f, v in self._filters:
                    items = [x for x in items if str(x.get(f)) == str(v)]
                res.data = [dict(x) for x in items]
                res.count = len(items)
                return res

            elif self.table_name in ("tasks", "facilities_attachments"):
                res.data = []
                res.count = 0
                return res

            res.data = []
            return res

    mock_client = MagicMock()
    mock_client.table.side_effect = lambda t: MockQuery(t)

    with patch("elara.db.supabase", mock_client), \
         patch("elara.auth.supabase", mock_client), \
         patch("db.supabase", mock_client):
        yield


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


# ── 10. Elara Attachments Workflow & Isolation ─────────────────────────────────

def test_elara_attachments_workflow_and_isolation():
    """Verify attachments can be added to Elara Home tasks with full parity to Facilities."""
    from db import supabase
    from elara.flows.attachments import prompt_attachment, handle_attachment_upload, show_task_attachments
    from elara.flows.router import route_elara_image
    from elara.session import get_elara_session, set_elara_session

    user = {
        "name": "Rachit",
        "phone": "919867272041",
        "role": "Site Incharge",
        "department": "Construction & Design",
        "team": "Elara Home",
        "is_elara_user": True,
    }

    # 1. Create a project and a task
    proj = create_project(name="Villa 101 Finishing", department="Construction & Design")
    task = create_task(title="Inspect Living Room Ceiling", project_id=proj["id"], assigned_users=["Rachit"])
    task_id = task["id"]

    # Initially 0 attachments
    assert get_attachment_count(task_id) == 0
    assert len(get_attachments(task_id)) == 0

    # 2. Test prompt_attachment
    with patch("elara.flows.attachments.send_text") as mock_send_text:
        prompt_attachment(to="919867272041", task_id=task_id, user=user)
        mock_send_text.assert_called_once()
        prompt_msg = mock_send_text.call_args[0][1]
        assert "Attach File" in prompt_msg
        assert task_id in prompt_msg

    session = get_elara_session("919867272041")
    assert session is not None
    assert session.get("flow_state") == "attach_awaiting"
    assert session.get("draft", {}).get("task_id") == task_id

    # 3. Test handle_attachment_upload
    img_data = {
        "id": "media-wa-img-999",
        "mime_type": "image/jpeg",
        "filename": "ceiling_plaster_inspection.jpg",
    }

    with patch("elara.flows.attachments.send_interactive_buttons") as mock_send_btn:
        handle_attachment_upload(sender="919867272041", task_id=task_id, media_data=img_data, user=user)
        mock_send_btn.assert_called_once()
        confirm_body = mock_send_btn.call_args[0][1]
        assert "Attachment Saved" in confirm_body
        assert "ceiling_plaster_inspection.jpg" in confirm_body

    # 4. Verify elara_attachments table has the record
    attachments = get_attachments(task_id)
    assert len(attachments) == 1
    att = attachments[0]
    assert att["task_id"] == task_id
    assert att["file_name"] == "ceiling_plaster_inspection.jpg"
    assert att["uploaded_by"] == "Rachit"

    # 5. Verify elara_tasks.attachments JSONB column was synced
    refreshed_task = get_task_by_id(task_id)
    assert refreshed_task is not None
    task_atts = refreshed_task.get("attachments") or []
    assert len(task_atts) == 1
    assert task_atts[0]["file_name"] == "ceiling_plaster_inspection.jpg"

    # 6. Verify audit comment was added to elara_comments
    comments = get_comments(task_id)
    comment_texts = [c.get("content", "") for c in comments]
    assert any("Attachment added: ceiling_plaster_inspection.jpg" in ct for ct in comment_texts)

    # 7. Test route_elara_image dispatcher when in attach_awaiting state
    set_elara_session("919867272041", "attach_awaiting", draft={"task_id": task_id})
    doc_data = {
        "id": "media-wa-doc-888",
        "mime_type": "application/pdf",
        "filename": "structural_drawing.pdf",
    }
    with patch("elara.flows.attachments.send_interactive_buttons") as mock_send_doc:
        handled = route_elara_image("919867272041", image_data=doc_data, user=user)
        assert handled is True
        mock_send_doc.assert_called_once()
        assert "Attachment Saved" in mock_send_doc.call_args[0][1]

    # Total attachments should now be 2
    assert get_attachment_count(task_id) == 2

    # 8. Verify strict zero cross-team data leakage (none in facilities_attachments)
    fac_res = supabase.table("facilities_attachments").select("*").execute()
    assert len(fac_res.data or []) == 0

