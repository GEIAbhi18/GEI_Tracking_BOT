"""
Comprehensive unit tests for the Facilities workflow overhaul:
- Central Owner Position Resolver
- Task Filtering Engine & NL parsing
- Overdue logic & Delay Days
- Overdue tasks building-first flow
- Position-based notifications
"""

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
