from __future__ import annotations
import pytest
from unittest.mock import patch, MagicMock
from clients.sync_engine import run_client_master_sync, get_cached_clients


def test_sync_engine_with_mocked_sheets(mocker):
    # Mock Google Sheets fetch
    mock_rows = [
        {
            "Tenant Company Name": "HDFC Bank",
            "Building Name": "GEBB I",
            "Floor": "GROUND FLOOR",
            "Unit Number": "R1/R2",
            "Admin Contact Name": "Rakesh Kumar",
            "Designation": "Admin",
            "Primary Mobile Number": "8826896085",
            "Primary Contact Email ID": "rakesh@hdfcbank.in",
            "_row_number": 2,
        },
        {
            "Tenant Company Name": "Indus Insights",
            "Building Name": "GEBB II",
            "Floor": "2nd Floor",
            "Unit Number": "201",
            "Admin Contact Name": "Mahesh",
            "Designation": "Admin",
            "Primary Mobile Number": "9958995715",
            "Primary Contact Email ID": "mahesh@indus.com",
            "_row_number": 3,
        },
        {
            "Tenant Company Name": "Invalid Tenant",
            "Building Name": "GETT",
            "Floor": "1st Floor",
            "Unit Number": "101",
            "Admin Contact Name": "Nobody",
            "Primary Mobile Number": "",  # Missing phone
            "_row_number": 4,
        },
    ]

    mocker.patch(
        "clients.sync_engine.fetch_master_tenant_records",
        return_value=mock_rows,
    )
    mock_supabase_table = MagicMock()
    mock_supabase_table.select.return_value.limit.return_value.execute.return_value = MagicMock(data=[{"id": 1}])
    mock_supabase_table.upsert.return_value.execute.return_value = MagicMock(data=[])
    mock_supabase_table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    mocker.patch("clients.sync_engine.supabase.table", return_value=mock_supabase_table)

    # Run sync
    stats = run_client_master_sync()

    assert stats["total_rows_read"] == 3
    assert stats["valid_records"] == 2
    assert stats["invalid_records"] == 1

    # Check that in-memory cache has valid clients
    cached = get_cached_clients()
    assert len(cached) == 2
    company_names = [c["company_name"] for c in cached]
    assert "HDFC Bank" in company_names
    assert "Indus Insights" in company_names
