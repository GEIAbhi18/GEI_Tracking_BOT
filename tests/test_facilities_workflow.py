"""
Comprehensive unit tests for the Facilities workflow overhaul:
- Central Owner Position Resolver
- Task Filtering Engine & NL parsing
- Overdue logic & Delay Days
- Overdue tasks building-first flow
- Position-based notifications
"""

# pyrefly: ignore [missing-import]
import pytest
from unittest.mock import MagicMock, patch
from facilities.owner_resolver import (
    resolve_position_to_user,
    resolve_user_to_positions,
    get_position_titles_for_user,
    match_employee_name,
)
from facilities.task_filter import (
    TaskFilterCriteria,
    filter_tasks,
    is_task_overdue,
    is_task_future,
    calculate_delay_days,
    parse_filter_from_text,
    enrich_task_with_responsible,
)
from facilities.facilities_notifications import (
    format_task_update_notification,
    format_overdue_notification,
    format_task_update_confirmation,
)


@pytest.fixture(autouse=True)
def mock_supabase_positions():
    """Mock the DB response for facilities_owner_positions."""
    mock_data = [
        {"position_title": "Facility Head", "user_name": "Anoop", "building": None},
        {"position_title": "Facility Manager GEBB1", "user_name": "Vikramjeet", "building": "GEBB1"},
        {"position_title": "Facility Manager GEBB2", "user_name": "Vikramjeet", "building": "GEBB2"},
        {"position_title": "Facility Manager GETT", "user_name": "Vikash", "building": "GETT"},
        {"position_title": "Facility Director", "user_name": "Kanav", "building": None},
    ]
    with patch("facilities.owner_resolver.supabase") as mock_sb:
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.execute.return_value = MagicMock(data=mock_data)
        from facilities.owner_resolver import refresh_cache
        refresh_cache()
        yield


class TestOwnerResolver:
    def test_resolve_position_to_user(self):
        # Mandatory mappings
        assert resolve_position_to_user("Facility Head")["user_name"] == "Anoop"
        assert resolve_position_to_user("Facility Manager GEBB1")["user_name"] == "Vikramjeet"
        assert resolve_position_to_user("Facility Manager GEBB2")["user_name"] == "Vikramjeet"
        assert resolve_position_to_user("Facility Manager GETT")["user_name"] == "Vikash"
        assert resolve_position_to_user("Facility Director")["user_name"] == "Kanav"

    def test_resolve_user_to_positions(self):
        # Vikramjeet holds both GEBB1 and GEBB2 positions
        vikram_positions = get_position_titles_for_user("Vikramjeet")
        assert "Facility Manager GEBB1" in vikram_positions
        assert "Facility Manager GEBB2" in vikram_positions

        # Alias: Vikram -> Vikramjeet
        vikram_alias_positions = get_position_titles_for_user("Vikram")
        assert "Facility Manager GEBB1" in vikram_alias_positions
        assert "Facility Manager GEBB2" in vikram_alias_positions

        # Building-specific resolution
        gebb1_pos = get_position_titles_for_user("Vikramjeet", building="GEBB1")
        assert "Facility Manager GEBB1" in gebb1_pos
        assert "Facility Manager GEBB2" not in gebb1_pos

        gebb2_pos = get_position_titles_for_user("Vikramjeet", building="GEBB2")
        assert "Facility Manager GEBB2" in gebb2_pos
        assert "Facility Manager GEBB1" not in gebb2_pos

        # Vikash -> GETT
        vikash_pos = get_position_titles_for_user("Vikash")
        assert "Facility Manager GETT" in vikash_pos

        # Anoop -> Facility Head
        anoop_pos = get_position_titles_for_user("Anoop")
        assert "Facility Head" in anoop_pos

        # Kanav -> Facility Director
        kanav_pos = get_position_titles_for_user("Kanav")
        assert "Facility Director" in kanav_pos

    def test_match_employee_name(self):
        assert match_employee_name("vikash") == "Vikash"
        assert match_employee_name("Vikramjeet") == "Vikramjeet"
        assert match_employee_name("vikram") == "Vikramjeet"
        assert match_employee_name("anoop") == "Anoop"
        assert match_employee_name("kanav") == "Kanav"
        assert match_employee_name("random_person") is None


class TestOverdueLogic:
    def test_is_task_overdue(self):
        # Past target date + Open -> Overdue
        task_overdue = {
            "ref_no": "GEBB1-001",
            "status": "Open",
            "target_date": "2020-01-01",
            "delay_days": "10",
        }
        assert is_task_overdue(task_overdue) is True

        # Past target date + Closed -> NOT Overdue
        task_closed = {
            "ref_no": "GEBB1-002",
            "status": "Closed",
            "target_date": "2020-01-01",
            "delay_days": "10",
        }
        assert is_task_overdue(task_closed) is False

        # Future target date + Open -> NOT Overdue
        task_future = {
            "ref_no": "GEBB1-003",
            "status": "Open",
            "target_date": "2030-01-01",
            "delay_days": "0",
        }
        assert is_task_overdue(task_future) is False

    def test_calculate_delay_days(self):
        # Uses Sheet formula value if present
        task = {"target_date": "2020-01-01", "delay_days": "5"}
        assert calculate_delay_days(task) == 5

        # Computes if delay_days is empty
        task_compute = {"target_date": "2026-08-20", "delay_days": ""}
        # If current date is after 2026-08-20, should be > 0
        assert calculate_delay_days(task_compute) >= 0


class TestNaturalLanguageFilterParsing:
    user = {"name": "Vikramjeet", "permitted_buildings": ["GEBB1", "GEBB2", "GETT"]}

    def test_parse_overdue(self):
        criteria = parse_filter_from_text("show overdue tasks", self.user)
        assert criteria.overdue is True

    def test_parse_overdue_with_building(self):
        criteria = parse_filter_from_text("show overdue tasks in GEBB2", self.user)
        assert criteria.overdue is True
        assert criteria.building == "GEBB2"

    def test_parse_employee_tasks(self):
        criteria = parse_filter_from_text("show Vikash tasks", self.user)
        assert criteria.employee_name == "Vikash"

        criteria2 = parse_filter_from_text("show Vikramjeet tasks in GEBB1", self.user)
        assert criteria2.employee_name == "Vikramjeet"
        assert criteria2.building == "GEBB1"

    def test_parse_status_tasks(self):
        criteria = parse_filter_from_text("show pending tasks for GEBB1", self.user)
        assert criteria.status == "Open"
        assert criteria.building == "GEBB1"

        criteria2 = parse_filter_from_text("show completed tasks", self.user)
        assert criteria2.status == "Closed"

    def test_parse_future_tasks(self):
        criteria = parse_filter_from_text("show future tasks for GETT", self.user)
        assert criteria.future is True
        assert criteria.building == "GETT"

    def test_parse_combination(self):
        criteria = parse_filter_from_text("show Vikramjeet's overdue tasks in GEBB1", self.user)
        assert criteria.employee_name == "Vikramjeet"
        assert criteria.overdue is True
        assert criteria.building == "GEBB1"

    def test_parse_date_range(self):
        criteria = parse_filter_from_text("show tasks between 20 and 29 Aug", self.user)
        assert criteria.date_range_start is not None
        assert criteria.date_range_end is not None
        assert criteria.date_field == "target_date"

        criteria_raised = parse_filter_from_text("show tasks raised between 20 and 29 Aug", self.user)
        assert criteria_raised.date_field == "created_date"


class TestEnrichmentAndNotifications:
    def test_enrich_task_with_responsible(self):
        task = {
            "ref_no": "GEBB1-001",
            "owner": "Facility Manager GEBB1",
            "issue_action": "Fix AC",
        }
        enrich_task_with_responsible(task)
        assert task["responsible_user"] == "Vikramjeet"

        task_head = {
            "ref_no": "Common-001",
            "owner": "Facility Head",
            "issue_action": "Inspection",
        }
        enrich_task_with_responsible(task_head)
        assert task_head["responsible_user"] == "Anoop"

    def test_format_notifications(self):
        task = {
            "ref_no": "GEBB1-001",
            "issue_action": "Electrical work pending",
            "building": "GEBB1",
            "type": "Electrical",
            "target_date": "20 Aug 2026",
            "status": "Pending",
            "delay_days": "5",
        }
        update_notif = format_task_update_notification(task)
        assert "Task Update Required" in update_notif
        assert "Electrical work pending" in update_notif

        overdue_notif = format_overdue_notification(task)
        assert "Overdue Task Alert" in overdue_notif

        confirm_msg = format_task_update_confirmation(task, "Work completed", "In Progress")
        assert "Task updated successfully" in confirm_msg


class TestCreateTaskFlowAndDirectorAccess:
    def test_director_and_developer_permissions(self):
        from facilities.auth import get_permitted_buildings, assert_building_access
        director = {"name": "Kanav", "role": "Director", "permitted_buildings": []}
        developer = {"name": "Abhijeet", "role": "Developer", "permitted_buildings": []}

        # Both get all buildings
        assert "GEBB1" in get_permitted_buildings(director)
        assert "GEBB2" in get_permitted_buildings(director)
        assert "GETT" in get_permitted_buildings(director)
        assert assert_building_access(director, "GEBB1") is True
        assert assert_building_access(developer, "GETT") is True

    def test_handle_building_selection_in_create_flow(self):
        from facilities.flows.router import _handle_building_selection
        user = {"name": "Kanav", "role": "Director", "permitted_buildings": ["GEBB1", "GEBB2", "GETT"]}
        session = {"current_flow_state": "create_building", "context_json": {"next_action": "create_task"}}

        with patch("facilities.flows.create_task.handle_building_selection") as mock_create_bldg, \
             patch("facilities.flows.team_tasks.show_team_tasks") as mock_team_tasks:
            _handle_building_selection("919811867829", "GEBB1", user, session)
            # Must call handle_building_selection in create flow, NOT show_team_tasks!
            mock_create_bldg.assert_called_once_with("919811867829", "GEBB1", user)
            mock_team_tasks.assert_not_called()

    def test_description_with_employee_name_not_hijacked(self):
        from facilities.flows.router import route_facilities_message
        sender = "919811867829"
        user = {"name": "Kanav", "role": "Director", "permitted_buildings": ["GEBB1", "GEBB2", "GETT", "Common"]}
        session_store = {
            "current_flow_state": "create_issue",
            "draft_task_json": {"building": "GEBB1", "type": "Project", "status": "Open"},
            "context_json": {"next_action": "create_task"}
        }

        def mock_set_session(s, state, draft=None, context=None):
            session_store["current_flow_state"] = state
            if draft:
                session_store["draft_task_json"] = draft
            if context:
                session_store["context_json"] = context

        def mock_get_session(s):
            return session_store

        with patch("facilities.flows.create_task.set_session", side_effect=mock_set_session), \
             patch("facilities.flows.create_task.get_session", side_effect=mock_get_session), \
             patch("facilities.flows.router.set_session", side_effect=mock_set_session), \
             patch("facilities.flows.router.get_session", side_effect=mock_get_session), \
             patch("whatsapp.ux.send_text"):
            route_facilities_message(sender, text="Test task created by Kanav", user=user)
            assert session_store.get("current_flow_state") == "create_target_date"
            assert session_store.get("draft_task_json", {}).get("issue_action") == "Test task"
            assert session_store.get("draft_task_json", {}).get("owner") == "Facilities Director"

    def test_sheet_row_building_for_all_tabs(self):
        from facilities.sheets_client import _build_sheet_row
        from facilities.config import VALID_TASK_TYPES, VALID_STATUSES, VALID_OWNER_POSITIONS

        task_data = {
            "ref_no": "TEST-001",
            "type": "Project",
            "issue_action": "Test task description",
            "latest_update": "Work in progress",
            "last_modified_by_at": "Abhijeet / 2026-08-26 10:00 UTC",
            "owner": "Vikramjeet",
            "created_date": "2026-08-26",
            "target_date": "2026-09-15",
            "status": "Open",
        }

        # All building tabs (GETT, GEBB1, GEBB2, Common) now have 11 columns (Cols A to K)
        for bldg in ["GETT", "GEBB1", "GEBB2", "Common"]:
            row = _build_sheet_row(bldg, task_data, row_idx=12)
            assert len(row) == 11
            assert row[1] in VALID_TASK_TYPES
            assert row[4] == "Abhijeet"
            assert row[5] in VALID_OWNER_POSITIONS
            assert row[6] == "26-Aug-2026"
            assert row[7] == "15-Sep-2026"
            assert '=IF(H12="","",IF(J12="Closed",0,MAX(0,TODAY()-H12)))' in row[8]
            assert row[9] in VALID_STATUSES
            assert row[10] == ""

    def test_direct_task_update_mark_as_closed(self):
        from facilities.flows.router import route_facilities_message
        user = {
            "name": "Abhijeet",
            "role": "Developer",
            "permitted_buildings": ["GEBB1", "GEBB2", "GETT", "Common"],
            "is_facilities_user": True
        }
        sender = "917717754421"
        mock_task = {
            "ref_no": "GETT-013",
            "building": "GETT",
            "type": "Project",
            "issue_action": "dummy test task",
            "owner": "Facility Manager",
            "status": "Open",
            "latest_update": ""
        }

        with patch("facilities.flows.router.resolve_facilities_user", return_value=user), \
             patch("facilities.flows.update_task.read_row", return_value=mock_task), \
             patch("facilities.flows.update_task.send_interactive_buttons") as mock_btn, \
             patch("facilities.flows.router.get_session", return_value=None), \
             patch("facilities.flows.router.set_session"), \
             patch("facilities.flows.update_task.set_session"):
            route_facilities_message(sender, text="Mark gett-013 as closed", user=user)
            assert mock_btn.called
            msg_text = mock_btn.call_args[0][1]
            assert "GETT-013" in msg_text
            assert "Open → 🟢 Closed" in msg_text
            buttons = mock_btn.call_args[0][2]
            assert buttons[0]["id"] == "fac_confirm_update"

    def test_normalize_added_by_kanav(self):
        from facilities.sheets_client import normalize_added_by, _build_sheet_row

        # Kanav variants normalize to "Facilities Director"
        assert normalize_added_by("Kanav") == "Facilities Director"
        assert normalize_added_by("kanav") == "Facilities Director"
        assert normalize_added_by("kk") == "Facilities Director"
        assert normalize_added_by("KK") == "Facilities Director"
        assert normalize_added_by("Director") == "Facilities Director"
        assert normalize_added_by("Facilities Director") == "Facilities Director"
        assert normalize_added_by("Facility Director") == "Facilities Director"
        assert normalize_added_by("Kanav / 2026-08-31 09:40 UTC") == "Facilities Director / 2026-08-31 09:40 UTC"

        # Other names remain as clean name
        assert normalize_added_by("Abhijeet") == "Abhijeet"
        assert normalize_added_by("Facility Head") == "Facility Head"
        assert normalize_added_by("") == "GEI_BOT"
        assert normalize_added_by(None) == "GEI_BOT"

        # When Kanav adds a task, Column E (index 4) on Google Sheets is strictly "Facilities Director"
        kanav_task = {
            "ref_no": "GEBB1-008",
            "type": "Project",
            "issue_action": "Kanav created task",
            "latest_update": "",
            "added_by": "Kanav",
            "owner": "Facility Head",
            "created_date": "2026-08-27",
            "target_date": "2026-08-31",
            "status": "Open",
        }
        row = _build_sheet_row("GEBB1", kanav_task, row_idx=8)
        assert row[4] == "Facilities Director"

        # When last_modified_by_at has Kanav with timestamp, Column E is still "Facilities Director"
        kanav_task_ts = {
            "ref_no": "GEBB1-009",
            "type": "Project",
            "issue_action": "Another task by Kanav",
            "latest_update": "",
            "last_modified_by_at": "Kanav / 2026-08-27 10:00 UTC",
            "owner": "Facility Head",
            "created_date": "2026-08-27",
            "target_date": "2026-08-31",
            "status": "Open",
        }
        row_ts = _build_sheet_row("GEBB1", kanav_task_ts, row_idx=9)
        assert row_ts[4] == "Facilities Director"


class TestVoiceOpsMissingBuilding:
    """Tests for voice-note task creation when building is missing."""

    def _make_ops(self, buildings=None):
        """Helper to create 2 create_task operations, optionally with buildings."""
        ops = []
        for i, (action, bldg) in enumerate([
            ("centric leakage", buildings[0] if buildings else None),
            ("Manipal leakage", buildings[1] if buildings else None),
        ]):
            entities = {"issue_action": action, "type": "Project"}
            if bldg:
                entities["building"] = bldg
            ops.append({
                "intent": "create_task",
                "confidence": 0.9,
                "entities": entities,
            })
        return ops

    def test_confirm_all_missing_building_prompts_selection(self):
        """When create_task ops have no building, confirm_all should prompt instead of skip."""
        from facilities.flows.voice_handler import confirm_all_voice_ops

        sender = "917717754421"
        user = {
            "name": "Kanav",
            "role": "Director",
            "permitted_buildings": ["GEBB1", "GEBB2", "GETT", "Common"],
            "is_facilities_user": True,
        }

        ops = self._make_ops()
        session_store = {
            "current_flow_state": "voice_confirm",
            "context_json": {"operations": ops, "confidence": 0.85},
        }

        def mock_get_session(phone):
            return session_store

        set_session_calls = []
        def mock_set_session(phone, state, draft=None, context=None):
            set_session_calls.append({"state": state, "context": context})

        with patch("facilities.flows.voice_handler.get_session", side_effect=mock_get_session), \
             patch("facilities.flows.voice_handler.set_session", side_effect=mock_set_session), \
             patch("facilities.flows.voice_handler.send_interactive_buttons") as mock_btns, \
             patch("whatsapp.ux.send_list_message") as mock_list, \
             patch("facilities.flows.voice_handler.send_text"):
            confirm_all_voice_ops(sender, user)

            # Should have set session to voice_awaiting_building
            assert len(set_session_calls) == 1
            assert set_session_calls[0]["state"] == "voice_awaiting_building"
            assert set_session_calls[0]["context"]["operations"] == ops

            # Should have prompted for building selection (list message for 4 buildings)
            assert mock_btns.called or mock_list.called
            if mock_btns.called:
                msg = mock_btns.call_args[0][1]
            else:
                msg = mock_list.call_args[0][1]
            assert "Building Required" in msg

    def test_confirm_all_with_building_executes_immediately(self):
        """When all create_task ops have buildings, confirm_all executes without prompting."""
        from facilities.flows.voice_handler import confirm_all_voice_ops

        sender = "917717754421"
        user = {
            "name": "Kanav",
            "role": "Director",
            "permitted_buildings": ["GEBB1", "GEBB2", "GETT", "Common"],
            "is_facilities_user": True,
        }

        ops = self._make_ops(buildings=["GEBB1", "GEBB2"])
        session_store = {
            "current_flow_state": "voice_confirm",
            "context_json": {"operations": ops, "confidence": 0.85},
        }

        def mock_get_session(phone):
            return session_store

        mock_create = MagicMock(return_value={"ref_no": "GEBB1-099", "sheet_status": "synced"})

        with patch("facilities.flows.voice_handler.get_session", side_effect=mock_get_session), \
             patch("facilities.flows.voice_handler.clear_session"), \
             patch("facilities.flows.voice_handler.send_text") as mock_text, \
             patch("facilities.sheets_client.create_row", mock_create):
            confirm_all_voice_ops(sender, user)

            # Should have executed (not prompted for building)
            assert mock_create.call_count == 2
            # Should have sent results message
            result_msg = mock_text.call_args[0][1]
            assert "Voice Operations — Results" in result_msg

    def test_building_selection_fills_and_executes(self):
        """After building selection, missing buildings are filled and tasks are created."""
        from facilities.flows.voice_handler import handle_voice_building_selection

        sender = "917717754421"
        user = {
            "name": "Kanav",
            "role": "Director",
            "permitted_buildings": ["GEBB1", "GEBB2", "GETT", "Common"],
            "is_facilities_user": True,
        }

        ops = self._make_ops()  # no buildings
        session_store = {
            "current_flow_state": "voice_awaiting_building",
            "context_json": {"operations": ops, "confidence": 0.85},
        }

        def mock_get_session(phone):
            return session_store

        create_calls = []
        def mock_create(building, draft, actor=None):
            create_calls.append({"building": building, "draft": draft})
            return {"ref_no": f"{building}-099", "sheet_status": "synced"}

        with patch("facilities.flows.voice_handler.get_session", side_effect=mock_get_session), \
             patch("facilities.flows.voice_handler.clear_session"), \
             patch("facilities.flows.voice_handler.send_text") as mock_text, \
             patch("facilities.sheets_client.create_row", side_effect=mock_create):
            handle_voice_building_selection(sender, "GETT", user)

            # Both tasks should have been created with building=GETT
            assert len(create_calls) == 2
            assert create_calls[0]["building"] == "GETT"
            assert create_calls[1]["building"] == "GETT"
            assert create_calls[0]["draft"]["issue_action"] == "centric leakage"
            assert create_calls[1]["draft"]["issue_action"] == "Manipal leakage"

            # Should have reported results
            result_msg = mock_text.call_args[0][1]
            assert "Voice Operations — Results" in result_msg
            assert "2/2" in result_msg

    def test_voice_text_building_fuzzy_match(self):
        """User can type a building name during voice_awaiting_building state."""
        from facilities.flows.voice_handler import handle_voice_confirm_text

        sender = "917717754421"
        user = {
            "name": "Kanav",
            "role": "Director",
            "permitted_buildings": ["GEBB1", "GEBB2", "GETT", "Common"],
            "is_facilities_user": True,
        }

        ops = self._make_ops()
        session = {
            "current_flow_state": "voice_awaiting_building",
            "context_json": {"operations": ops, "confidence": 0.85},
        }

        with patch("facilities.flows.voice_handler.handle_voice_building_selection") as mock_bldg_sel, \
             patch("facilities.flows.voice_handler.send_text"):
            handle_voice_confirm_text(sender, "bay 1", user, session)
            assert mock_bldg_sel.called
            assert mock_bldg_sel.call_args[0][1] == "GEBB1"

    def test_voice_text_building_invalid_reprompts(self):
        """Invalid building name re-prompts building selection."""
        from facilities.flows.voice_handler import handle_voice_confirm_text

        sender = "917717754421"
        user = {
            "name": "Kanav",
            "role": "Director",
            "permitted_buildings": ["GEBB1", "GEBB2", "GETT", "Common"],
            "is_facilities_user": True,
        }

        session = {
            "current_flow_state": "voice_awaiting_building",
            "context_json": {"operations": self._make_ops(), "confidence": 0.85},
        }

        with patch("facilities.flows.voice_handler.handle_voice_building_selection") as mock_bldg_sel, \
             patch("facilities.flows.voice_handler.send_text") as mock_text, \
             patch("facilities.flows.voice_handler.send_interactive_buttons"):
            handle_voice_confirm_text(sender, "xyznonexistent", user, session)
            # Should NOT have called building selection
            assert not mock_bldg_sel.called
            # Should have sent error message
            assert mock_text.called
            assert "couldn't find a building" in mock_text.call_args[0][1]

    def test_router_building_button_routes_to_voice(self):
        """fac_bldg_ button in voice_awaiting_building state routes to voice handler."""
        from facilities.flows.router import _handle_building_selection

        sender = "917717754421"
        user = {
            "name": "Kanav",
            "role": "Director",
            "permitted_buildings": ["GEBB1", "GEBB2", "GETT", "Common"],
            "is_facilities_user": True,
        }

        session = {
            "current_flow_state": "voice_awaiting_building",
            "context_json": {"operations": self._make_ops(), "confidence": 0.85},
        }

        with patch("facilities.flows.voice_handler.handle_voice_building_selection") as mock_handler:
            _handle_building_selection(sender, "GEBB1", user, session)
            assert mock_handler.called
            assert mock_handler.call_args[0] == (sender, "GEBB1", user)
class TestFacilityHeadMyTasks:
    """Tests for Anoop / Facility Head My Tasks across all buildings (GEBB1, GEBB2, GETT, Common)."""

    def test_anoop_my_tasks_resolution_and_display(self):
        from facilities.flows.my_tasks import show_my_tasks
        from facilities.auth import get_permitted_buildings
        from facilities.owner_resolver import get_position_titles_for_user

        user = {
            "name": "Anoop",
            "role": "Employee",
            "department": "Facilities",
            "permitted_buildings": ["GEBB1", "GEBB2", "GETT", "Common"],
            "whatsapp_number": "919211501013",
            "is_facilities_user": True,
        }

        # Anoop should have all buildings permitted
        bldgs = get_permitted_buildings(user)
        assert "GEBB1" in bldgs
        assert "GEBB2" in bldgs
        assert "GETT" in bldgs
        assert "Common" in bldgs

        # Positions for Anoop
        positions = get_position_titles_for_user("Anoop")
        assert any("facility head" in p.lower() for p in positions)

        # Mock sample rows across all buildings
        sample_rows = {
            "GEBB1": [
                {"ref_no": "GEBB1-001", "building": "GEBB1", "type": "Project", "issue_action": "DG maintenance", "owner": "Facility Head", "status": "Open"},
                {"ref_no": "GEBB1-002", "building": "GEBB1", "type": "Project", "issue_action": "Paint work", "owner": "Facility Manager", "status": "WIP"},
            ],
            "GEBB2": [
                {"ref_no": "GEBB2-001", "building": "GEBB2", "type": "Project", "issue_action": "Stack parking", "owner": "Facility Head", "status": "WIP"},
            ],
            "GETT": [
                {"ref_no": "GETT-001", "building": "GETT", "type": "Major Concern", "issue_action": "Chiller alarm", "owner": "Facilities Head", "status": "Closed"},
            ],
            "Common": [
                {"ref_no": "COM-001", "building": "Common", "type": "Improvement / Initiative", "issue_action": "Compliance tracker", "owner": "Facility Head", "status": "Open"},
            ],
        }

        def mock_list_rows(building):
            return sample_rows.get(building, [])

        sent_messages = []
        sent_lists = []

        with patch("facilities.flows.my_tasks.list_rows_by_building", side_effect=mock_list_rows), \
             patch("facilities.flows.my_tasks.send_list_message", side_effect=lambda to, body, btn, sec: sent_lists.append((to, body, btn, sec))), \
             patch("facilities.flows.my_tasks.send_text", side_effect=lambda to, txt: sent_messages.append((to, txt))), \
             patch("facilities.sync_engine.poll_sheet_changes"):
            show_my_tasks("919211501013", user)

        assert len(sent_lists) == 1
        body = sent_lists[0][1]
        assert "GEBB1-001" in body
        assert "GEBB2-001" in body
        assert "GETT-001" in body
        assert "COM-001" in body
        assert "GEBB1-002" not in body  # assigned to Facility Manager, not Anoop


# ═══════════════════════════════════════════════════════════════════════════════
# ALIAS NORMALIZER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestAliasNormalizer:
    """Tests for facilities.alias_normalizer.normalize_building_aliases."""

    def test_trade_tower_to_gett(self):
        from facilities.alias_normalizer import normalize_building_aliases
        assert "GETT" in normalize_building_aliases("Check the water tank in Trade Tower")

    def test_trade_tower_building_to_gett(self):
        from facilities.alias_normalizer import normalize_building_aliases
        result = normalize_building_aliases("Trade Tower Building has an AC issue")
        assert "GETT" in result

    def test_gett_passthrough(self):
        from facilities.alias_normalizer import normalize_building_aliases
        assert "GETT" in normalize_building_aliases("Issue in GETT")

    def test_bay_one_to_gebb1(self):
        from facilities.alias_normalizer import normalize_building_aliases
        assert "GEBB1" in normalize_building_aliases("Bay One water leakage")

    def test_bay_1_to_gebb1(self):
        from facilities.alias_normalizer import normalize_building_aliases
        assert "GEBB1" in normalize_building_aliases("Bay 1 parking issue")

    def test_bay_two_to_gebb2(self):
        from facilities.alias_normalizer import normalize_building_aliases
        assert "GEBB2" in normalize_building_aliases("Bay Two elevator stuck")

    def test_bay_2_to_gebb2(self):
        from facilities.alias_normalizer import normalize_building_aliases
        assert "GEBB2" in normalize_building_aliases("Bay 2 fire alarm")

    def test_gebb_1_space_to_gebb1(self):
        from facilities.alias_normalizer import normalize_building_aliases
        assert "GEBB1" in normalize_building_aliases("Issue at GEBB 1 lobby")

    def test_gebb_2_space_to_gebb2(self):
        from facilities.alias_normalizer import normalize_building_aliases
        assert "GEBB2" in normalize_building_aliases("Issue at GEBB 2 lobby")

    def test_case_insensitivity(self):
        from facilities.alias_normalizer import normalize_building_aliases
        for variant in ["trade tower", "Trade Tower", "TRADE TOWER", "tRaDe ToWeR"]:
            assert "GETT" in normalize_building_aliases(f"Issue at {variant}"), \
                f"Failed for variant: {variant}"

    def test_getting_stt_misheard(self):
        """STT commonly mishears 'GETT' as 'getting'."""
        from facilities.alias_normalizer import normalize_building_aliases
        result = normalize_building_aliases("There is a leak in getting building")
        assert "GETT" in result

    def test_tech_tower_to_gett(self):
        from facilities.alias_normalizer import normalize_building_aliases
        assert "GETT" in normalize_building_aliases("tech tower roof needs repair")

    def test_common_area(self):
        from facilities.alias_normalizer import normalize_building_aliases
        result = normalize_building_aliases("common area lights not working")
        assert "Common" in result

    def test_no_alias_passthrough(self):
        from facilities.alias_normalizer import normalize_building_aliases
        original = "The meeting is at 3 PM"
        assert normalize_building_aliases(original) == original

    def test_empty_string(self):
        from facilities.alias_normalizer import normalize_building_aliases
        assert normalize_building_aliases("") == ""

    def test_none_passthrough(self):
        from facilities.alias_normalizer import normalize_building_aliases
        assert normalize_building_aliases(None) is None

    def test_multiple_aliases_in_one_sentence(self):
        from facilities.alias_normalizer import normalize_building_aliases
        result = normalize_building_aliases("Compare Bay One and Bay Two parking")
        assert "GEBB1" in result
        assert "GEBB2" in result

    def test_word_boundary_safety(self):
        """'Bay 1' inside 'Bay 100' should NOT match."""
        from facilities.alias_normalizer import normalize_building_aliases
        result = normalize_building_aliases("Room Bay 100 has an issue")
        # Should NOT replace "Bay 1" inside "Bay 100"
        assert "GEBB1" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# POST-VOICE FALLBACK TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestVoiceFallback:
    """Tests for voice fallback (no clear intent) behavior."""

    def test_trivial_transcript_detected(self):
        from facilities.flows.voice_handler import _is_trivial_transcript
        assert _is_trivial_transcript("hi")
        assert _is_trivial_transcript("hello there")
        assert _is_trivial_transcript("ok bye")
        assert _is_trivial_transcript("test")

    def test_substantial_transcript_not_trivial(self):
        from facilities.flows.voice_handler import _is_trivial_transcript
        assert not _is_trivial_transcript("Check the water tank in Bay 1")
        assert not _is_trivial_transcript("The elevator is stuck on floor 3 in GETT")
        assert not _is_trivial_transcript("Need to fix AC cooling issue")

    def test_short_but_meaningful_is_trivial(self):
        """Under 3 words is trivial regardless of content."""
        from facilities.flows.voice_handler import _is_trivial_transcript
        assert _is_trivial_transcript("fix AC")

    @patch("facilities.flows.voice_handler.send_text")
    @patch("facilities.flows.voice_handler.send_interactive_buttons")
    @patch("facilities.flows.voice_handler.extract_voice_operations")
    @patch("facilities.flows.voice_handler.set_session")
    def test_fallback_menu_shown_for_substantial(self, mock_set, mock_extract,
                                                  mock_buttons, mock_text):
        """When transcript is substantial but has no ops, the fallback menu appears."""
        mock_extract.return_value = {
            "operations": [],
            "transcription_confidence": 0.8,
            "raw_transcript": "Check water tank situation in GEBB1",
        }

        from facilities.flows.voice_handler import handle_voice_note
        handle_voice_note("919999999999", "Check water tank situation in GEBB1", {})

        # Should show interactive buttons (fallback menu), not just plain text
        assert mock_buttons.called
        call_args = mock_buttons.call_args
        buttons = call_args[0][2] if len(call_args[0]) > 2 else call_args[1].get("buttons", [])
        button_ids = [b["id"] for b in buttons]
        assert "fac_voice_create_task" in button_ids
        assert "fac_voice_update_task" in button_ids
        assert "fac_voice_discard" in button_ids

    @patch("facilities.flows.voice_handler.send_text")
    @patch("facilities.flows.voice_handler.send_interactive_buttons")
    @patch("facilities.flows.voice_handler.extract_voice_operations")
    def test_trivial_transcript_no_menu(self, mock_extract, mock_buttons, mock_text):
        """When transcript is trivial, show plain text, NOT the fallback menu."""
        mock_extract.return_value = {
            "operations": [],
            "transcription_confidence": 0.8,
            "raw_transcript": "ok bye",
        }

        from facilities.flows.voice_handler import handle_voice_note
        handle_voice_note("919999999999", "ok bye", {})

        # Should NOT show interactive buttons
        assert not mock_buttons.called


# ═══════════════════════════════════════════════════════════════════════════════
# VOICE NAVIGATION ROUTING TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestVoiceNavigationDetection:
    """Tests for _is_navigational_voice_command — ensures navigational
    voice commands are correctly identified so they route through _route_text."""

    def test_show_my_tasks_is_navigational(self):
        from facilities.flows.router import _is_navigational_voice_command
        assert _is_navigational_voice_command("Show my tasks")
        assert _is_navigational_voice_command("show my tasks")
        assert _is_navigational_voice_command("Show my tasks. Show my tasks.")
        assert _is_navigational_voice_command("my tasks")
        assert _is_navigational_voice_command("view my tasks")
        assert _is_navigational_voice_command("tasks assigned to me")

    def test_show_tasks_with_building_is_navigational(self):
        from facilities.flows.router import _is_navigational_voice_command
        assert _is_navigational_voice_command("Show tasks of GEBB1 or B1.")
        assert _is_navigational_voice_command("show tasks of GEBB1")
        assert _is_navigational_voice_command("show tasks of GETT")
        assert _is_navigational_voice_command("view tasks in GEBB2")
        assert _is_navigational_voice_command("list tasks for Common")
        assert _is_navigational_voice_command("get tasks of GEBB1")

    def test_show_team_tasks_is_navigational(self):
        from facilities.flows.router import _is_navigational_voice_command
        assert _is_navigational_voice_command("show team tasks")
        assert _is_navigational_voice_command("team tasks")
        assert _is_navigational_voice_command("view team tasks for GEBB1")

    def test_overdue_is_navigational(self):
        from facilities.flows.router import _is_navigational_voice_command
        assert _is_navigational_voice_command("show overdue tasks")
        assert _is_navigational_voice_command("overdue tasks in GEBB1")
        assert _is_navigational_voice_command("what tasks are overdue")
        assert _is_navigational_voice_command("past due tasks")

    def test_completed_is_navigational(self):
        from facilities.flows.router import _is_navigational_voice_command
        assert _is_navigational_voice_command("show completed tasks")
        assert _is_navigational_voice_command("completed tasks in GETT")
        assert _is_navigational_voice_command("show closed tasks")

    def test_create_task_command_is_navigational(self):
        from facilities.flows.router import _is_navigational_voice_command
        assert _is_navigational_voice_command("create task")
        assert _is_navigational_voice_command("create a task")
        assert _is_navigational_voice_command("new task")
        assert _is_navigational_voice_command("add task")
        assert _is_navigational_voice_command("raise task")

    def test_direct_update_is_navigational(self):
        from facilities.flows.router import _is_navigational_voice_command
        assert _is_navigational_voice_command("Mark GETT-013 as closed")
        assert _is_navigational_voice_command("close GETT-006")
        assert _is_navigational_voice_command("update GEBB1-042 status to WIP")

    def test_menu_greetings_are_navigational(self):
        from facilities.flows.router import _is_navigational_voice_command
        assert _is_navigational_voice_command("menu")
        assert _is_navigational_voice_command("hi")
        assert _is_navigational_voice_command("hello")
        assert _is_navigational_voice_command("help")
        assert _is_navigational_voice_command("home")
        assert _is_navigational_voice_command("cancel")

    def test_summary_is_navigational(self):
        from facilities.flows.router import _is_navigational_voice_command
        assert _is_navigational_voice_command("show summary")
        assert _is_navigational_voice_command("summary")

    def test_report_is_navigational(self):
        from facilities.flows.router import _is_navigational_voice_command
        assert _is_navigational_voice_command("report")
        assert _is_navigational_voice_command("eod report")
        assert _is_navigational_voice_command("facilities report")
        assert _is_navigational_voice_command("pdf report")

    def test_data_bearing_not_navigational(self):
        """Task data / progress updates should NOT be detected as navigational."""
        from facilities.flows.router import _is_navigational_voice_command
        assert not _is_navigational_voice_command("Waterproofing 60% done in top terrace")
        assert not _is_navigational_voice_command("The plumber came and fixed the water tank issue")
        assert not _is_navigational_voice_command("AC cooling is not working properly on 5th floor")
        assert not _is_navigational_voice_command("Bay 1 waterproofing 80% done")
        assert not _is_navigational_voice_command("Slope correction has a blocker, material not arrived")

    def test_random_notes_not_navigational(self):
        """Random/general notes should NOT be detected as navigational."""
        from facilities.flows.router import _is_navigational_voice_command
        assert not _is_navigational_voice_command("The meeting with the contractor went well today")
        assert not _is_navigational_voice_command("Please tell the security guard to check the gate")
        assert not _is_navigational_voice_command("We need more cement and sand for tomorrow")


class TestVoiceRouteIntegration:
    """Integration tests for _route_voice — ensures navigational transcripts
    are routed through _route_text and data-bearing ones go to voice_handler."""

    def test_show_my_tasks_routes_to_text(self):
        """'Show my tasks' voice note should trigger show_my_tasks, not fallback menu."""
        from facilities.flows.router import _route_voice

        sender = "917717754421"
        user = {
            "name": "Abhijeet",
            "role": "Developer",
            "permitted_buildings": ["GEBB1", "GEBB2", "GETT", "Common"],
            "is_facilities_user": True,
        }

        with patch("facilities.flows.router._route_text") as mock_route_text, \
             patch("facilities.flows.voice_handler.handle_voice_note") as mock_voice:
            _route_voice(sender, "Show my tasks. Show my tasks.", user, None)

            # Should route to _route_text, NOT to voice_handler
            assert mock_route_text.called
            assert not mock_voice.called

    def test_show_tasks_of_building_routes_to_text(self):
        """'Show tasks of GEBB1' voice note should route through text handler."""
        from facilities.flows.router import _route_voice

        sender = "917717754421"
        user = {
            "name": "Abhijeet",
            "role": "Developer",
            "permitted_buildings": ["GEBB1", "GEBB2", "GETT", "Common"],
            "is_facilities_user": True,
        }

        with patch("facilities.flows.router._route_text") as mock_route_text, \
             patch("facilities.flows.voice_handler.handle_voice_note") as mock_voice:
            _route_voice(sender, "Show tasks of GEBB1 or B1.", user, None)

            assert mock_route_text.called
            assert not mock_voice.called

    def test_data_voice_note_routes_to_voice_handler(self):
        """Data-bearing voice notes should go to voice operations extraction."""
        from facilities.flows.router import _route_voice

        sender = "917717754421"
        user = {
            "name": "Abhijeet",
            "role": "Developer",
            "permitted_buildings": ["GEBB1", "GEBB2", "GETT", "Common"],
            "is_facilities_user": True,
        }

        with patch("facilities.flows.router._route_text") as mock_route_text, \
             patch("facilities.flows.voice_handler.handle_voice_note") as mock_voice:
            _route_voice(sender, "Waterproofing 60% done in top terrace", user, None)

            # Should go to voice_handler, NOT _route_text
            assert not mock_route_text.called
            assert mock_voice.called

    def test_random_note_routes_to_voice_handler(self):
        """Random/general notes should go to voice handler (preserving existing behavior)."""
        from facilities.flows.router import _route_voice

        sender = "917717754421"
        user = {
            "name": "Abhijeet",
            "role": "Developer",
            "permitted_buildings": ["GEBB1", "GEBB2", "GETT", "Common"],
            "is_facilities_user": True,
        }

        with patch("facilities.flows.router._route_text") as mock_route_text, \
             patch("facilities.flows.voice_handler.handle_voice_note") as mock_voice:
            _route_voice(sender, "The meeting with the contractor went well today", user, None)

            assert not mock_route_text.called
            assert mock_voice.called

    def test_overdue_voice_routes_to_text(self):
        """'Show overdue tasks' voice note should route through text handler."""
        from facilities.flows.router import _route_voice

        sender = "917717754421"
        user = {"name": "Abhijeet", "role": "Developer",
                "permitted_buildings": ["GEBB1", "GEBB2", "GETT", "Common"],
                "is_facilities_user": True}

        with patch("facilities.flows.router._route_text") as mock_route_text, \
             patch("facilities.flows.voice_handler.handle_voice_note") as mock_voice:
            _route_voice(sender, "show overdue tasks", user, None)

            assert mock_route_text.called
            assert not mock_voice.called

    def test_alias_normalized_before_routing(self):
        """Building aliases should be normalized before navigational detection."""
        from facilities.flows.router import _route_voice

        sender = "917717754421"
        user = {"name": "Abhijeet", "role": "Developer",
                "permitted_buildings": ["GEBB1", "GEBB2", "GETT", "Common"],
                "is_facilities_user": True}

        with patch("facilities.flows.router._route_text") as mock_route_text, \
             patch("facilities.flows.voice_handler.handle_voice_note") as mock_voice:
            # "Trade Tower" → normalized to "GETT", then "show tasks of GETT" is navigational
            _route_voice(sender, "show tasks of Trade Tower", user, None)

            assert mock_route_text.called
            assert not mock_voice.called

    def test_mark_ref_no_voice_routes_to_text(self):
        """'Mark GETT-013 as closed' should route through text handler for direct update."""
        from facilities.flows.router import _route_voice

        sender = "917717754421"
        user = {"name": "Abhijeet", "role": "Developer",
                "permitted_buildings": ["GEBB1", "GEBB2", "GETT", "Common"],
                "is_facilities_user": True}

        with patch("facilities.flows.router._route_text") as mock_route_text, \
             patch("facilities.flows.voice_handler.handle_voice_note") as mock_voice:
            _route_voice(sender, "Mark GETT-013 as closed", user, None)

            assert mock_route_text.called
            assert not mock_voice.called
