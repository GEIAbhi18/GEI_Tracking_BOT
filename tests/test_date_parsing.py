from unittest.mock import MagicMock
import pytest
from core.utils import parse_human_date
from datetime import datetime, timedelta

def test_parse_human_date_tomorrow_typos():
    today = datetime.now()
    expected = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    # Standard
    assert parse_human_date("tomorrow") == expected
    assert parse_human_date("Tomorrow") == expected
    
    # Common user misspellings
    assert parse_human_date("Tommorow") == expected
    assert parse_human_date("tommorow") == expected
    assert parse_human_date("tomorow") == expected
    assert parse_human_date("tomrow") == expected
    assert parse_human_date("tomm") == expected

def test_parse_human_date_today_and_day_after():
    today = datetime.now()
    assert parse_human_date("today") == today.strftime("%Y-%m-%d")
    assert parse_human_date("tday") == today.strftime("%Y-%m-%d")

    expected_day_after = (today + timedelta(days=2)).strftime("%Y-%m-%d")
    assert parse_human_date("day after tomorrow") == expected_day_after
    assert parse_human_date("day after tommorow") == expected_day_after

def test_parse_human_date_unparseable_returns_none():
    assert parse_human_date("invalid_random_string_123") is None

def test_add_task_deadline_sanitization(mocker):
    from db import add_task
    mock_supabase = mocker.patch("db.supabase")
    mock_execute = MagicMock()
    today = datetime.now()
    expected_dl = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    mock_execute.data = [{"id": "t-1", "title": "Test Task", "deadline": expected_dl}]
    mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_execute

    # Call add_task with misspelled deadline "Tommorow"
    res = add_task("proj-1", "Test Task", deadline="Tommorow", created_by="user-1")

    # Verify deadline inserted into payload is sanitized to YYYY-MM-DD
    inserted_payload = mock_supabase.table.return_value.insert.call_args[0][0]
    assert inserted_payload["deadline"] == expected_dl
