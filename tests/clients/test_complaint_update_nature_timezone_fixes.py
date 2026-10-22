from __future__ import annotations
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from clients.factech_client import (
    update_complaint,
    get_complaints,
    format_to_ist,
    get_now_ist_str,
    IST_TZ,
    _LOGGED_COMPLAINTS_CACHE,
    _save_local_complaint_record,
)
from clients.config import (
    CHAITANYA_PHONE,
    CHAITANYA_ALT_PHONE,
    CHAITANYA_TENANT_RECORD,
    is_chaitanya,
)


class TestNatureAndStatusPreservation:
    """Verifies Complaint Nature (e.g. Electrical) and Status (e.g. Closed)

    are strictly preserved during complaint updates and never overwritten with generic defaults.
    """

    def test_update_complaint_preserves_nature_and_status(self, mocker):
        mocker.patch("requests.put", return_value=MagicMock(
            status_code=200,
            json=lambda: {"status": "success", "data": [{"status": "success"}]},
        ))
        mocker.patch("db.supabase.table")

        client_ctx = {
            "company_name": "Good Earth Infra",
            "building": "Business Bay-II",
            "unit_number": "GEEBTWOTest",
            "admin_name": "Chaitanya",
            "mobile_number": CHAITANYA_PHONE,
        }

        existing_record = {
            "complaint_id": "B2-00455",
            "com_no": "B2-00455",
            "company": "Good Earth Infra",
            "building": "Business Bay-II",
            "unit": "GEEBTWOTest",
            "unitNo": "GEEBTWOTest",
            "admin_name": "Chaitanya",
            "mobile": CHAITANYA_PHONE,
            "nature": "Electrical",
            "category": "Electrical",
            "complaint_category": {"name": "Electrical"},
            "sub_nature": "Others",
            "description": "Initial complaint",
            "status": "Closed",
            "created_at": "2026-07-22 15:30:00",
            "closed_at": "2026-10-06 16:40:57",
        }

        result = update_complaint(
            client_ctx,
            "B2-00455",
            {"description": "testing update mechanism"},
            existing_complaint=existing_record,
        )

        assert result["success"] is True
        assert result["complaint_id"] == "B2-00455"

        # Verify cached / persisted complaint retains Electrical nature and Closed status
        cached = next(
            (c for c in _LOGGED_COMPLAINTS_CACHE if (c.get("complaint_id") or c.get("com_no")) == "B2-00455"),
            None,
        )
        assert cached is not None
        assert cached["nature"] == "Electrical"
        assert cached["complaint_category"]["name"] == "Electrical"
        assert cached["status"] == "Closed"
        assert "testing update mechanism" in cached["description"]

    def test_save_local_record_prevents_downgrade(self):
        """Ensures _save_local_complaint_record prevents downgrading Closed -> In Progress

        or Electrical -> General Maintenance.
        """
        initial_record = {
            "complaint_id": "TEST-REG-01",
            "com_no": "TEST-REG-01",
            "nature": "Electrical",
            "complaint_category": {"name": "Electrical"},
            "status": "Closed",
            "created_at": "2026-07-22 15:30:00",
        }
        _save_local_complaint_record(initial_record)

        # Attempt to save record with default General Maintenance and In Progress
        attempted_downgrade = {
            "complaint_id": "TEST-REG-01",
            "com_no": "TEST-REG-01",
            "nature": "General Maintenance",
            "complaint_category": {"name": "General Maintenance"},
            "status": "In Progress",
            "created_at": "2026-07-22 15:30:00",
        }
        _save_local_complaint_record(attempted_downgrade)

        cached = next(
            (c for c in _LOGGED_COMPLAINTS_CACHE if (c.get("complaint_id") or c.get("com_no")) == "TEST-REG-01"),
            None,
        )
        assert cached is not None
        # Must retain original specific nature and closed status
        assert cached["nature"] == "Electrical"
        assert cached["status"] == "Closed"


class TestLiveFactechStatusReconciliation:
    """Verifies get_complaints reconciles live Factech status with local caches,

    preventing closed complaints from showing as In Progress in active complaints list.
    """

    def test_live_factech_closed_overrides_stale_local_in_progress(self, mocker):
        # Stale local cache entry has status 'In Progress'
        stale_local = {
            "complaint_id": "B2-00455",
            "com_no": "B2-00455",
            "company": "Good Earth Infra",
            "unit": "GEEBTWOTest",
            "unitNo": "GEEBTWOTest",
            "mobile": CHAITANYA_PHONE,
            "nature": "Electrical",
            "complaint_category": {"name": "Electrical"},
            "status": "In Progress",  # Stale!
        }
        _LOGGED_COMPLAINTS_CACHE.insert(0, stale_local)

        # Factech API returns live status 'Closed'
        mock_factech_response = {
            "objects": [
                {
                    "com_no": "B2-00455",
                    "status": "Closed",
                    "unit": "GEEBTWOTest",
                    "complaint_category": {"name": "Electrical"},
                    "created_at": "2026-07-22 15:30:00",
                    "updated_at": "2026-10-21 12:47:08",
                }
            ],
            "count": 1,
        }

        mocker.patch("requests.get", return_value=MagicMock(
            status_code=200,
            json=lambda: mock_factech_response,
        ))

        client_ctx = {
            "company_name": "Good Earth Infra",
            "building": "Business Bay-II",
            "unit_number": "GEEBTWOTest",
            "admin_name": "Chaitanya",
            "mobile_number": CHAITANYA_PHONE,
        }

        # 1. Fetching active complaints only must EXCLUDE B2-00455 because live status is Closed
        active_list = get_complaints(client_ctx, days_back=180, active_only=True)
        active_ids = [c.get("com_no") for c in active_list]
        assert "B2-00455" not in active_ids

        # 2. Fetching all complaints must reflect reconciled Closed status
        all_list = get_complaints(client_ctx, days_back=180, active_only=False)
        reconciled = next((c for c in all_list if c.get("com_no") == "B2-00455"), None)
        assert reconciled is not None
        assert reconciled["status"] == "Closed"
        cat = reconciled.get("complaint_category") or {}
        nat = (cat.get("name") if isinstance(cat, dict) else None) or reconciled.get("nature")
        assert nat == "Electrical"


class TestTimezoneConversionToIST:
    """Verifies that UTC timestamps from server / Supabase / audit log

    are formatted into Indian Standard Time (IST, UTC+5:30) matching Factech sheets.
    """

    def test_utc_iso_string_to_ist(self):
        # 07:17:08 UTC corresponds to 12:47:08 IST
        utc_iso = "2026-10-21T07:17:08.424965+00:00"
        ist_str = format_to_ist(utc_iso)
        assert ist_str == "2026-10-21 12:47:08"

    def test_utc_z_string_to_ist(self):
        utc_z = "2026-10-21T07:17:08Z"
        ist_str = format_to_ist(utc_z)
        assert ist_str == "2026-10-21 12:47:08"

    def test_naive_datetime_to_ist(self):
        dt_naive = datetime(2026, 10, 21, 7, 17, 8)
        ist_str = format_to_ist(dt_naive)
        assert ist_str == "2026-10-21 12:47:08"

    def test_already_ist_formatted_string_preserved(self):
        ist_orig = "2026-10-21 12:47:08"
        ist_result = format_to_ist(ist_orig)
        assert ist_result == "2026-10-21 12:47:08"

    def test_get_now_ist_str_format(self):
        ist_now = get_now_ist_str()
        assert len(ist_now) == 19
        assert ist_now[4] == "-" and ist_now[7] == "-" and ist_now[10] == " "


class TestChaitanyaPhoneNumberCorrectness:
    """Verifies Chaitanya's phone number is correctly configured as +919713957666."""

    def test_chaitanya_phone_constants(self):
        assert CHAITANYA_PHONE == "919713957666"
        assert CHAITANYA_ALT_PHONE == "9713957666"
        assert CHAITANYA_TENANT_RECORD["mobile_number"] == "919713957666"

    def test_is_chaitanya_matches_phone_formats(self):
        assert is_chaitanya("+919713957666") is True
        assert is_chaitanya("919713957666") is True
        assert is_chaitanya("9713957666") is True
        assert is_chaitanya("+91 97139 57666") is True
        assert is_chaitanya("09713957666") is True
        # Negative check: old/wrong number must not match Chaitanya
        assert is_chaitanya("+918952899000") is False
        assert is_chaitanya("918952899000") is False
