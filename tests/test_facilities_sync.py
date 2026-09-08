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

