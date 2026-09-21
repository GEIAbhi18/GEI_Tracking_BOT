"""
Unit and Integration Tests for Facilities Module (v3.0)
=========================================================
Tests:
  - Ref No parsing & format validation
  - Building alias & fuzzy matching
  - Conflict window logic
  - Sync queue status reporting
"""

# pyrefly: ignore [missing-import]
import pytest
from facilities.ref_no import parse_ref_no, get_building_from_ref_no
from facilities.auth import fuzzy_match_building, get_fuzzy_building_suggestions
from facilities.config import BUILDING_TABS, COLUMN_MAP, WRITABLE_FIELDS


def test_parse_ref_no():
    """Test Ref No parsing."""
    parsed = parse_ref_no("GEBB1-001")
    assert parsed["building"] == "GEBB1"
    assert parsed["number"] == 1

    parsed2 = parse_ref_no("GETT-042")
    assert parsed2["building"] == "GETT"
    assert parsed2["number"] == 42


def test_invalid_ref_no_format():
    """Test error handling for bad Ref No formats."""
    with pytest.raises(ValueError):
        parse_ref_no("INVALID")

    with pytest.raises(ValueError):
        parse_ref_no("GEBB1-001-EXTRA")


def test_get_building_from_ref_no():
    """Test extracting building code from Ref No."""
    assert get_building_from_ref_no("GEBB1-001") == "GEBB1"
    assert get_building_from_ref_no("GETT-100") == "GETT"
    assert get_building_from_ref_no("Common-005") == "Common"


def test_fuzzy_match_building_exact_and_aliases():
    """Test exact building tab names and known aliases."""
    assert fuzzy_match_building("GEBB1") == "GEBB1"
    assert fuzzy_match_building("gebb1") == "GEBB1"
    assert fuzzy_match_building("bay 1") == "GEBB1"
    assert fuzzy_match_building("tech tower") == "GETT"
    assert fuzzy_match_building("common area") == "Common"


def test_fuzzy_match_building_imperfect_text():
    """Test fuzzy matching with minor typos or spaces."""
    assert fuzzy_match_building("gebb 1") == "GEBB1"
    assert fuzzy_match_building("good earth tech tower") == "GETT"
    assert fuzzy_match_building("bay 2") == "GEBB2"


def test_fuzzy_building_suggestions():
    """Test suggestions when input is ambiguous."""
    suggestions = get_fuzzy_building_suggestions("bay")
    assert len(suggestions) > 0
    buildings = [s["building"] for s in suggestions]
    assert "GEBB1" in buildings or "GEBB2" in buildings


def test_column_map_integrity():
    """Test that all writable fields exist in column mapping."""
    for field in WRITABLE_FIELDS:
        assert field in COLUMN_MAP.values()


def test_handle_deleted_external_row(mocker):
    """Test that _handle_deleted_external_row cleans cache and cancels sync_queue items."""
    from facilities.sync_engine import _handle_deleted_external_row

    mock_supabase = mocker.patch("facilities.sync_engine.supabase")
    mock_audit = mocker.patch("facilities.sync_engine._log_audit_entry")

    _handle_deleted_external_row("GEBB1-009", "GEBB1")

    # Verify deleted from row_cache
    mock_supabase.table.assert_any_call("row_cache")
    # Verify sync_queue updated to cancelled
    mock_supabase.table.assert_any_call("sync_queue")
    # Verify audit log entry
    mock_audit.assert_called_once_with(
        "GEBB1-009", "google_sheets", None,
        "Task deleted externally on Google Sheets"
    )


def test_poll_building_tab_deletion_detection(mocker):
    """Test that _poll_building_tab detects deleted rows not in Sheet."""
    from facilities.sync_engine import _poll_building_tab

    # Mock worksheet with only GEBB1-001
    mock_ws = mocker.MagicMock()
    mock_ws.get_all_values.return_value = [
        ["Ref. No.", "Type", "Key Issue / Action", "Latest Update", "Added by", "Owner", "Date Raised", "Target Date", "Delay", "Last Modified"],
        ["GEBB1-001", "Client Escalation", "Issue 1", "", "FH", "FM", "05-Aug-2026", "30-Sep-2026", "", ""],
    ]
    mocker.patch("facilities.sheets_client._get_worksheet", return_value=mock_ws)
    mocker.patch("facilities.sheets_client._retry_on_429", side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs))

    # Mock row_cache having GEBB1-001 AND GEBB1-009 (which is missing in Sheet)
    mock_table = mocker.MagicMock()
    # For cache lookup of GEBB1-001: returns existing row
    mock_select_res = mocker.MagicMock()
    mock_select_res.data = [{"ref_no": "GEBB1-001", "building": "GEBB1", "type": "Client Escalation", "issue_action": "Issue 1"}]

    # For cache lookup of all rows in GEBB1: returns both GEBB1-001 and GEBB1-009
    mock_all_res = mocker.MagicMock()
    mock_all_res.data = [{"ref_no": "GEBB1-001"}, {"ref_no": "GEBB1-009"}]

    def mock_table_handler(table_name):
        tbl = mocker.MagicMock()
        if table_name == "row_cache":
            def mock_select(*args, **kwargs):
                sel = mocker.MagicMock()
                def mock_eq(col, val):
                    eq_mock = mocker.MagicMock()
                    if col == "ref_no" and val == "GEBB1-001":
                        eq_mock.execute.return_value = mock_select_res
                    elif col == "building":
                        eq_mock.execute.return_value = mock_all_res
                    else:
                        empty = mocker.MagicMock()
                        empty.data = []
                        eq_mock.execute.return_value = empty
                    return eq_mock
                sel.eq = mock_eq
                return sel
            tbl.select = mock_select
        elif table_name == "sync_queue":
            sel = mocker.MagicMock()
            sel.eq.return_value.eq.return_value.eq.return_value.execute.return_value = mocker.MagicMock(data=[])
            tbl.select = mocker.MagicMock(return_value=sel)
        return tbl

    mocker.patch("facilities.sync_engine.supabase.table", side_effect=mock_table_handler)
    mocker.patch("facilities.sync_engine._was_recently_synced_by_bot", return_value=False)
    mock_handle_deleted = mocker.patch("facilities.sync_engine._handle_deleted_external_row")

    changes = _poll_building_tab("GEBB1")

    # GEBB1-009 should have been detected as deleted and handled
    mock_handle_deleted.assert_called_once_with("GEBB1-009", "GEBB1")
    assert changes >= 1


def test_facilities_new_columns_config():
    """Verify 12-column layout, Planned Date, and completion date protection."""
    from facilities.config import COLUMN_MAP, COLUMN_INDEX, WRITABLE_FIELDS

    assert len(COLUMN_MAP) == 12
    assert COLUMN_MAP["H"] == "planned_date"
    assert COLUMN_MAP["K"] == "estimated_completion_date"
    assert COLUMN_MAP["L"] == "actual_completion_date"

    assert COLUMN_INDEX["planned_date"] == 8
    assert COLUMN_INDEX["estimated_completion_date"] == 11
    assert COLUMN_INDEX["actual_completion_date"] == 12

    # Bot must write estimated_completion_date but NEVER actual_completion_date
    assert "estimated_completion_date" in WRITABLE_FIELDS
    assert "actual_completion_date" not in WRITABLE_FIELDS


def test_parse_facilities_date_nlp():
    """Test NLP / human language date parsing for Estimated Completion Date."""
    from facilities.config import parse_facilities_date

    # Specific date with ordinals
    res1 = parse_facilities_date("10th September")
    assert res1 is not None and "10-Sep-" in res1

    # Standard formats
    res2 = parse_facilities_date("15 Sep 2026")
    assert res2 == "15-Sep-2026"

    # Conversational phrasing
    res3 = parse_facilities_date("completion expected on 20th September")
    assert res3 is not None and "20-Sep-" in res3

    # Weekdays ("by Friday", "next Monday")
    res4 = parse_facilities_date("by Friday")
    assert res4 is not None

    res5 = parse_facilities_date("next Monday")
    assert res5 is not None

    # Skip keywords
    assert parse_facilities_date("skip") is None
    assert parse_facilities_date("none") is None
    assert parse_facilities_date("") is None


def test_format_overdue_tasks_displays_planned_and_estimated():
    """Verify format_overdue_tasks displays Planned Date and Estimated Completion Date."""
    from facilities.task_filter import format_overdue_tasks

    sample_tasks = [
        {
            "ref_no": "GEBB1-005",
            "type": "Client Escalation",
            "issue_action": "Recurring water leakage complaint",
            "owner": "Facility Manager",
            "responsible_user": "Vikramjeet",
            "planned_date": "31-Aug-2026",
            "estimated_completion_date": "10-Sep-2026",
            "delay_days": "8",
            "status": "Open",
        },
        {
            "ref_no": "GEBB1-010",
            "type": "HVAC",
            "issue_action": "AC cooling low in bay 3",
            "owner": "Facility Head",
            "responsible_user": "Anoop",
            "planned_date": "01-Sep-2026",
            "estimated_completion_date": "",  # Empty
            "delay_days": "7",
            "status": "WIP",
        },
    ]

    output = format_overdue_tasks(sample_tasks, "GEBB1")

    # Verify header
    assert "🔴 *Overdue Tasks — GEBB1*" in output

    # Task 1 checks
    assert "*Ref:* GEBB1-005" in output
    assert "*Planned Date:* 31-Aug-2026" in output
    assert "*Estimated Completion Date:* 10-Sep-2026" in output
    assert "*Delay:* 8 days" in output

    # Task 2 checks (empty estimated date displays '—')
    assert "*Ref:* GEBB1-010" in output
    assert "*Planned Date:* 01-Sep-2026" in output
    assert "*Estimated Completion Date:* —" in output

    assert "_Total overdue: 2_" in output
    assert "Target Date" not in output


def test_actual_completion_date_write_rejected():
    """Verify that write_field rejects writing to actual_completion_date."""
    from facilities.sheets_client import write_field

    with pytest.raises(ValueError, match="not writable"):
        write_field("GEBB1-001", "actual_completion_date", "10-Sep-2026")


def test_notify_external_change_exclusive_to_anoop_for_update(mocker):
    """Verify that external sheet field update notifications are dispatched exclusively to Anoop."""
    from facilities.sync_engine import _notify_external_change

    mock_send = mocker.patch("whatsapp.ux.send_text")
    mocker.patch("facilities.config.resolve_anoop_phone_number", return_value="919211501013")
    mock_supabase = mocker.patch("facilities.sync_engine.supabase")
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mocker.MagicMock(
        data=[{"issue_action": "Fix basement lighting", "owner": "Facility Manager", "status": "Open", "planned_date": "15-Sep-2026"}]
    )

    _notify_external_change(
        ref_no="GEBB1-005",
        building="GEBB1",
        change_type="updated",
        details={"field": "status", "old_value": "Open", "new_value": "WIP"},
    )

    mock_send.assert_called_once()
    to_phone, msg = mock_send.call_args[0]
    assert to_phone == "919211501013"
    assert "GEBB1-005" in msg
    assert "Bay 1" in msg
    assert "Fix basement lighting" in msg
    assert "Status" in msg
    assert "Previous:* Open" in msg
    assert "Updated to:* WIP" in msg


def test_notify_external_change_exclusive_to_anoop_common_sheet(mocker):
    """Verify that external changes in Common sheet are dispatched exclusively to Anoop."""
    from facilities.sync_engine import _notify_external_change

    mock_send = mocker.patch("whatsapp.ux.send_text")
    mocker.patch("facilities.config.resolve_anoop_phone_number", return_value="919211501013")
    mock_supabase = mocker.patch("facilities.sync_engine.supabase")
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mocker.MagicMock(data=[])

    _notify_external_change(
        ref_no="Common-012",
        building="Common",
        change_type="created",
        details={
            "issue_action": "Clubhouse deep cleaning",
            "owner": "Facility Manager",
            "status": "Open",
            "planned_date": "25-Sep-2026",
        },
    )

    mock_send.assert_called_once()
    to_phone, msg = mock_send.call_args[0]
    assert to_phone == "919211501013"
    assert "Common-012" in msg
    assert "Common" in msg
    assert "Clubhouse deep cleaning" in msg
    assert "New Task Added" in msg


def test_notify_external_change_exclusive_to_anoop_for_deletion(mocker):
    """Verify that external deletions in building/common sheets notify Anoop exclusively."""
    from facilities.sync_engine import _notify_external_change

    mock_send = mocker.patch("whatsapp.ux.send_text")
    mocker.patch("facilities.config.resolve_anoop_phone_number", return_value="919211501013")
    mock_supabase = mocker.patch("facilities.sync_engine.supabase")
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mocker.MagicMock(
        data=[{"issue_action": "Old HVAC repair"}]
    )

    _notify_external_change(
        ref_no="GETT-033",
        building="GETT",
        change_type="deleted",
        details={},
    )

    mock_send.assert_called_once()
    to_phone, msg = mock_send.call_args[0]
    assert to_phone == "919211501013"
    assert "GETT-033" in msg
    assert "Trade Tower" in msg
    assert "Task Removed from Google Sheets" in msg


def test_resolve_anoop_phone_number(mocker):
    """Verify resolve_anoop_phone_number resolution priority."""
    from facilities.config import resolve_anoop_phone_number

    # 1. Configured ANOOP_WHATSAPP_NUMBER
    mocker.patch("facilities.config.ANOOP_WHATSAPP_NUMBER", "+91 98765 43210")
    assert resolve_anoop_phone_number() == "919876543210"

    # 2. Supabase DB lookup
    mocker.patch("facilities.config.ANOOP_WHATSAPP_NUMBER", "")
    mock_supabase = mocker.patch("db.supabase")
    mock_supabase.table.return_value.select.return_value.ilike.return_value.execute.return_value = mocker.MagicMock(
        data=[{"whatsapp_number": "+91 92115 01013", "name": "Anoop"}]
    )
    assert resolve_anoop_phone_number() == "919211501013"

    # 3. Fallback
    mock_supabase.table.return_value.select.return_value.ilike.return_value.execute.return_value = mocker.MagicMock(data=[])
    assert resolve_anoop_phone_number() == "919211501013"


def test_duplicate_ref_no_in_sheet_skipped(mocker):
    """Verify that duplicate ref_no rows in the same sheet tab are skipped and do not cause oscillation."""
    from facilities.sync_engine import _poll_building_tab, _reset_notification_tracker

    _reset_notification_tracker()
    mock_ws = mocker.MagicMock()
    # Header + 2 data rows with identical Ref No GEBB2-019
    mock_ws.get_all_values.return_value = [
        ["Ref. No.", "Type", "Key Issue / Action", "Latest Update", "Added By", "Owner", "Date Raised", "Planned Date", "Delay Days", "Status", "Estimated Completion Date", "Actual Completion Date"],
        ["GEBB2-019", "Other", "Substation cable", "sl_1", "Dir", "Head", "15-Sep-2026", "16-Sep-2026", "0", "Closed", "", ""],
        ["GEBB2-019", "Improvement", "Neptune EV", "sl_2", "Dir", "Head", "17-Sep-2026", "30-Sep-2026", "0", "WIP", "", ""],
    ]
    mocker.patch("facilities.sheets_client._get_worksheet", return_value=mock_ws)
    mocker.patch("facilities.sheets_client._retry_on_429", side_effect=lambda fn: fn())

    mock_supabase = mocker.patch("facilities.sync_engine.supabase")
    # Return cache matching row 1
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mocker.MagicMock(
        data=[{
            "ref_no": "GEBB2-019",
            "building": "GEBB2",
            "type": "Other",
            "issue_action": "Substation cable",
            "latest_update": "sl_1",
            "last_modified_by_at": "Dir",
            "owner": "Head",
            "created_date": "15-Sep-2026",
            "planned_date": "16-Sep-2026",
            "status": "Closed",
            "estimated_completion_date": "",
            "actual_completion_date": "",
        }]
    )

    mock_field_change = mocker.patch("facilities.sync_engine._handle_field_change")
    mock_multi_change = mocker.patch("facilities.sync_engine._handle_multi_field_change")
    mock_new_row = mocker.patch("facilities.sync_engine._handle_new_external_row")

    changes = _poll_building_tab("GEBB2")

    # Row 1 matched cache -> 0 changes. Row 2 was duplicate -> skipped! Total changes should be 0.
    assert changes == 0
    mock_field_change.assert_not_called()
    mock_multi_change.assert_not_called()
    mock_new_row.assert_not_called()


def test_notification_deduplication_suppresses_identical(mocker):
    """Verify that identical notifications within cooldown window are suppressed."""
    from facilities.sync_engine import _notify_external_change, _reset_notification_tracker

    _reset_notification_tracker()
    mock_send = mocker.patch("whatsapp.ux.send_text")
    mocker.patch("facilities.config.resolve_anoop_phone_number", return_value="919211501013")
    mock_supabase = mocker.patch("facilities.sync_engine.supabase")
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mocker.MagicMock(
        data=[{"issue_action": "Fix pump"}]
    )

    details = {"field": "status", "old_value": "Open", "new_value": "WIP"}

    # First call: should send
    _notify_external_change("GEBB1-010", "GEBB1", "updated", details)
    assert mock_send.call_count == 1

    # Second call with identical payload: should be suppressed
    _notify_external_change("GEBB1-010", "GEBB1", "updated", details)
    assert mock_send.call_count == 1


def test_flap_suppression_silences_rapid_changes(mocker):
    """Verify that rapid state changes (> 3 in 5 min) for the same task trigger flap suppression."""
    from facilities.sync_engine import _notify_external_change, _reset_notification_tracker

    _reset_notification_tracker()
    mock_send = mocker.patch("whatsapp.ux.send_text")
    mocker.patch("facilities.config.resolve_anoop_phone_number", return_value="919211501013")
    mock_supabase = mocker.patch("facilities.sync_engine.supabase")
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mocker.MagicMock(
        data=[{"issue_action": "Flapping task"}]
    )

    # 1st change (allowed)
    _notify_external_change("GEBB1-099", "GEBB1", "updated", {"field": "status", "old_value": "A", "new_value": "B"})
    # 2nd change (allowed)
    _notify_external_change("GEBB1-099", "GEBB1", "updated", {"field": "status", "old_value": "B", "new_value": "C"})
    # 3rd change (allowed - limit is 3)
    _notify_external_change("GEBB1-099", "GEBB1", "updated", {"field": "status", "old_value": "C", "new_value": "D"})
    assert mock_send.call_count == 3

    # 4th rapid change on the same task -> suppressed by flap damping!
    _notify_external_change("GEBB1-099", "GEBB1", "updated", {"field": "status", "old_value": "D", "new_value": "E"})
    assert mock_send.call_count == 3


def test_multi_field_update_batched_notification(mocker):
    """Verify that multiple field changes on a row generate a single consolidated WhatsApp message."""
    from facilities.sync_engine import _notify_external_change, _reset_notification_tracker

    _reset_notification_tracker()
    mock_send = mocker.patch("whatsapp.ux.send_text")
    mocker.patch("facilities.config.resolve_anoop_phone_number", return_value="919211501013")
    mock_supabase = mocker.patch("facilities.sync_engine.supabase")
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mocker.MagicMock(
        data=[{"issue_action": "Basement waterproofing", "owner": "Facility Head", "status": "WIP", "planned_date": "20-Sep-2026"}]
    )

    details = {
        "fields": [
            {"field": "status", "old_value": "Open", "new_value": "WIP"},
            {"field": "planned_date", "old_value": "15-Sep-2026", "new_value": "20-Sep-2026"},
        ]
    }

    _notify_external_change("GEBB1-008", "GEBB1", "updated", details)

    mock_send.assert_called_once()
    to_phone, msg = mock_send.call_args[0]
    assert to_phone == "919211501013"
    assert "GEBB1-008" in msg
    assert "Updates Made:" in msg
    assert "Status:* Open → WIP" in msg
    assert "Planned Date:* 15-Sep-2026 → 20-Sep-2026" in msg



