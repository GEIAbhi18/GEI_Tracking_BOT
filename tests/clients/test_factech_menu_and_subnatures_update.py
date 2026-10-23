"""
Tests for Factech Automation updates:
1. Rename Others to Miscellaneous
2. HouseKeeping -> Housekeeping
3. Select Complaints menu option and complaint details flow
4. Category-wise complaint nature & subnature additions from Image 3
"""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch

from clients.config import (
    COMPLAINT_NATURES,
    SUB_NATURES_ALL,
    NATURE_TO_SUB_NATURES,
    DEVELOPER_PHONE,
)
from clients.flows import (
    send_client_welcome_menu,
    handle_client_button_reply,
    handle_client_text,
    handle_select_complaints_initiation,
    handle_selected_complaint_details,
)


@pytest.fixture(autouse=True)
def clean_task_states(mocker):
    state_store = {}
    def mock_table(table_name):
        mock_t = MagicMock()
        def mock_upsert(data, **kwargs):
            state_store[data["whatsapp_number"]] = data
            res = MagicMock()
            res.execute.return_value = MagicMock(data=[data])
            return res
        def mock_select(*args):
            sel = MagicMock()
            def mock_eq(col, val):
                exec_mock = MagicMock()
                stored = state_store.get(val)
                exec_mock.execute.return_value = MagicMock(data=[stored] if stored else [])
                return exec_mock
            sel.eq = mock_eq
            return sel
        def mock_delete():
            del_mock = MagicMock()
            def mock_eq(col, val):
                state_store.pop(val, None)
                exec_mock = MagicMock()
                exec_mock.execute.return_value = MagicMock(data=[])
                return exec_mock
            del_mock.eq = mock_eq
            return del_mock

        mock_t.upsert = mock_upsert
        mock_t.select = mock_select
        mock_t.delete = mock_delete
        return mock_t

    mocker.patch("clients.flows.supabase.table", side_effect=mock_table)
    mocker.patch("db.supabase.table", side_effect=mock_table)
    yield


# ── Test 1: Configuration Requirements ────────────────────────────────────────

def test_housekeeping_spelling():
    """Requirement 2: Make HouseKeeping -> Housekeeping."""
    assert "Housekeeping" in COMPLAINT_NATURES
    assert "HouseKeeping" not in COMPLAINT_NATURES
    assert "Housekeeping" in NATURE_TO_SUB_NATURES
    # Ensure legacy HouseKeeping key also works for backward compatibility
    assert "HouseKeeping" in NATURE_TO_SUB_NATURES


def test_rename_others_to_miscellaneous():
    """Requirement: General removed from categories; Miscellaneous and Others removed from sub-categories, Other kept."""
    assert "Miscellaneous" in COMPLAINT_NATURES
    assert "General" not in COMPLAINT_NATURES
    assert "Other" in SUB_NATURES_ALL
    assert "Miscellaneous" not in SUB_NATURES_ALL
    assert "Others" not in SUB_NATURES_ALL
    for nature, sub_list in NATURE_TO_SUB_NATURES.items():
        assert "Other" in sub_list, f"{nature} sub_list missing Other"
        assert "Miscellaneous" not in sub_list, f"{nature} sub_list should not have Miscellaneous"
        assert "Others" not in sub_list, f"{nature} sub_list should not have Others"
        # Each list must stay within WhatsApp 10-row limit
        assert len(sub_list) <= 10, f"{nature} sub_list exceeds 10 items ({len(sub_list)})"


def test_civil_subnatures_match_image_3():
    """Requirement 5: Verify all 7 Civil subnatures from Image 3 are present."""
    civil_subs = NATURE_TO_SUB_NATURES["Civil"]
    expected_7_civil = [
        "Fire Door / Door Closer",
        "Lock & Key",
        "False Ceiling Access",
        "Floor Tiles/Marble Broken/Damaged",
        "Façade Glass Damage",
        "Wall Crack / Require Paint",
        "Water Seepage / Dampness Spot",
    ]
    for sub in expected_7_civil:
        assert sub in civil_subs, f"Missing Civil subnature: {sub}"

    # Including Other (without Miscellaneous), civil list has 8 items (<= 10 limit)
    assert len(civil_subs) == 8
    assert len(civil_subs) <= 10


def test_all_categories_subnatures_match_image_3():
    """Requirement 5: Verify all 6 categories from Image 3 have their required subnatures."""
    # Electrical (7 items)
    electrical_subs = NATURE_TO_SUB_NATURES["Electrical"]
    for sub in [
        "Power Failure",
        "Lighting Not Working",
        "Switch/Socket Fault",
        "MCB Tripping",
        "UPS Power Issue",
        "Loose Wiring / Burning Smell",
        "Emergency Lighting",
    ]:
        assert sub in electrical_subs, f"Missing Electrical subnature: {sub}"
    assert len(electrical_subs) <= 10

    # Plumbing (7 items)
    plumbing_subs = NATURE_TO_SUB_NATURES["Plumbing"]
    for sub in [
        "Water Leakage",
        "Choked Basin/Bottle Trap/Drainage",
        "Toilet / Urinal Choked",
        "Flush Not Working",
        "Water Supply Issue",
        "Tap Not Working",
        "Bad Odour",
    ]:
        assert sub in plumbing_subs, f"Missing Plumbing subnature: {sub}"
    assert len(plumbing_subs) <= 10

    # HVAC (6 items)
    hvac_subs = NATURE_TO_SUB_NATURES["HVAC"]
    for sub in [
        "AC Not Working",
        "Low Cooling",
        "Airflow Issue",
        "Water Leakage from AC",
        "Thermostat Issue",
        "Noise from AC",
    ]:
        assert sub in hvac_subs, f"Missing HVAC subnature: {sub}"
    assert len(hvac_subs) <= 10

    # Housekeeping (6 items)
    hk_subs = NATURE_TO_SUB_NATURES["Housekeeping"]
    for sub in [
        "Cleaning Request",
        "Spill Cleaning",
        "Washroom Cleaning",
        "Garbage Removal",
        "Pest Control",
        "Carpet Cleaning (Internal)",
    ]:
        assert sub in hk_subs, f"Missing Housekeeping subnature: {sub}"
    assert len(hk_subs) <= 10

    # Fire & Life Safety (6 items)
    fire_subs = NATURE_TO_SUB_NATURES["Fire & Life Safety"]
    for sub in [
        "Fire Alarm Issue",
        "Smoke Detector Fault",
        "MCP Glass Broken",
        "Fire Extinguisher",
        "Sprinkler Leakage",
        "Emergency Exit Light",
    ]:
        assert sub in fire_subs, f"Missing Fire & Life Safety subnature: {sub}"
    assert len(fire_subs) <= 10


# ── Test 2: Select Complaints Menu & Selection Flow ──────────────────────────

def test_main_menu_includes_select_complaints(mocker):
    """Requirement 4: Main menu contains 'Select Complaints' option."""
    mock_list = mocker.patch("clients.flows.send_list_message", return_value=True)
    client = {
        "admin_name": "Test Tenant",
        "company_name": "Acme Tech",
        "building": "Business Bay-II",
        "unit_number": "202",
    }
    send_client_welcome_menu(DEVELOPER_PHONE, client)

    mock_list.assert_called_once()
    rows = mock_list.call_args[0][3][0]["rows"]
    row_ids = [r["id"] for r in rows]
    assert "select_complaints" in row_ids
    select_row = next(r for r in rows if r["id"] == "select_complaints")
    assert select_row["title"] == "Select Complaints"


def test_select_complaints_flow_displays_list(mocker):
    """Requirement 4: Clicking 'Select Complaints' gives a list of complaints for that tenant."""
    mock_complaints = [
        {
            "com_no": "B2-00455",
            "complaintId": "B2-00455",
            "nature": "Electrical",
            "sub_nature": "Power Failure",
            "description": "Total power failure on floor",
            "status": "In Progress",
            "created_at": "2026-10-21 10:00:00",
        },
        {
            "com_no": "B2-00412",
            "complaintId": "B2-00412",
            "nature": "Civil",
            "sub_nature": "Floor Tiles/Marble Broken/Damaged",
            "description": "Broken tiles near entry door",
            "status": "Closed",
            "created_at": "2026-10-15 14:00:00",
        },
    ]
    mocker.patch("clients.flows.get_complaints", return_value=mock_complaints)
    mock_send_text = mocker.patch("clients.flows.send_text", return_value=True)
    mock_send_btn = mocker.patch("clients.flows.send_interactive_buttons", return_value=True)

    client = {
        "admin_name": "Chaitanya",
        "company_name": "Good Earth Infra",
        "building": "Business Bay-II",
        "unit_number": "GEEBTWOTest",
    }
    from elara.team_router import set_active_team
    set_active_team(DEVELOPER_PHONE, "factech")
    from clients.service import set_active_client_context
    set_active_client_context(DEVELOPER_PHONE, client)

    # User clicks 'select_complaints'
    handle_client_button_reply(DEVELOPER_PHONE, "select_complaints")

    # Verifies fetching notification sent
    assert any("Fetching complaints" in str(c) for c in mock_send_text.call_args_list)

    # Verifies interactive buttons with complaints sent
    mock_send_btn.assert_called_once()
    prompt_text = mock_send_btn.call_args[0][1]
    assert "B2-00455" in prompt_text
    assert "Power Failure" in prompt_text or "Electrical" in prompt_text
    assert "B2-00412" in prompt_text

    buttons = mock_send_btn.call_args[0][2]
    btn_ids = [b["id"] for b in buttons]
    assert "sel_cid_B2-00455" in btn_ids
    assert "sel_cid_B2-00412" in btn_ids


def test_select_specific_complaint_shows_details(mocker):
    """Clicking a complaint from Select Complaints shows full details and actions."""
    mock_complaints = [
        {
            "com_no": "B2-00455",
            "complaintId": "B2-00455",
            "nature": "Electrical",
            "sub_nature": "Power Failure",
            "description": "Total power outage",
            "status": "In Progress",
            "created_at": "2026-10-21 10:00:00",
        }
    ]
    mocker.patch("clients.flows.get_complaint_by_id", return_value=mock_complaints[0])
    mocker.patch("clients.flows.get_complaints", return_value=mock_complaints)
    mock_send_text = mocker.patch("clients.flows.send_text", return_value=True)
    mock_send_btn = mocker.patch("clients.flows.send_interactive_buttons", return_value=True)

    client = {
        "admin_name": "Developer",
        "company_name": "Good Earth Infra (Dev Test)",
        "building": "Business Bay-II",
        "unit_number": "GEEBTWOTest",
    }

    handle_selected_complaint_details(DEVELOPER_PHONE, client, "B2-00455")

    # Details message verification
    details_call = mock_send_text.call_args_list[0][0][1]
    assert "Complaint ID: B2-00455" in details_call
    assert "Status: In Progress" in details_call
    assert "Available status options" not in details_call
    assert "Progress:" not in details_call
    assert "Electrical" in details_call
    assert "Total power outage" in details_call

    # Next action buttons for active complaint
    mock_send_btn.assert_called_once()
    btn_ids = [b["id"] for b in mock_send_btn.call_args[0][2]]
    assert "upd_cid_B2-00455" in btn_ids
    assert "client_main_menu" in btn_ids


def test_select_complaints_text_selection(mocker):
    """User can select complaint by replying with the number (e.g. '1')."""
    mock_complaints = [
        {
            "com_no": "B2-00455",
            "complaintId": "B2-00455",
            "nature": "Electrical",
            "sub_nature": "Power Failure",
            "description": "Total power outage",
            "status": "In Progress",
            "created_at": "2026-10-21 10:00:00",
        }
    ]
    mocker.patch("clients.flows.get_complaints", return_value=mock_complaints)
    mock_details = mocker.patch("clients.flows.handle_selected_complaint_details")

    client = {
        "admin_name": "Developer",
        "company_name": "Good Earth Infra (Dev Test)",
        "building": "Business Bay-II",
        "unit_number": "GEEBTWOTest",
    }

    # Initiate Select Complaints
    handle_select_complaints_initiation(DEVELOPER_PHONE, client)

    # Reply with "1"
    handled = handle_client_text(DEVELOPER_PHONE, "1")
    assert handled is True
    mock_details.assert_called_once()
    assert mock_details.call_args[1]["target_cid"] == "B2-00455"


def test_select_complaints_tenth_complaint_emoji_formatting(mocker):
    """Verify 10th complaint uses proper keycap 🔟 emoji and not split '1 0️⃣'."""
    from clients.flows import handle_select_complaints_initiation
    mock_complaints = [
        {
            "com_no": f"B2-00{i:03d}",
            "complaintId": f"B2-00{i:03d}",
            "nature": "Plumbing",
            "status": "Closed",
            "created_at": "2026-05-04 06:26:19",
        }
        for i in range(1, 11)
    ]
    mocker.patch("clients.flows.get_complaints", return_value=mock_complaints)
    mock_send_list = mocker.patch("clients.flows.send_list_message", return_value=True)

    client = {
        "admin_name": "Developer",
        "company_name": "Good Earth Infra",
        "building": "Business Bay-II",
        "unit_number": "GEEBTWOTest",
    }

    handle_select_complaints_initiation(DEVELOPER_PHONE, client)

    mock_send_list.assert_called_once()
    body_text = mock_send_list.call_args[0][1]
    # Check 10th complaint formatting
    assert "🔟 *#B2-00010* — Plumbing" in body_text
    assert "1 0️⃣" not in body_text
    assert "10️⃣" not in body_text

