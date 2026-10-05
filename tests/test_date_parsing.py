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

def test_parse_human_date_weekdays_and_voice_transcripts():
    today = datetime.now()
    # Wednesday
    cur_weekday = today.weekday()
    wed_ahead = 2 - cur_weekday
    if wed_ahead <= 0:
        wed_ahead += 7
    expected_wed = (today + timedelta(days=wed_ahead)).strftime("%Y-%m-%d")

    assert parse_human_date("Wednesday") == expected_wed
    assert parse_human_date("wednesday") == expected_wed
    assert parse_human_date("Wednesday.") == expected_wed
    assert parse_human_date("due date Wednesday") == expected_wed
    assert parse_human_date("due date Wednesday.") == expected_wed
    assert parse_human_date("due date is Wednesday") == expected_wed
    assert parse_human_date("due on Wednesday") == expected_wed
    assert parse_human_date("by Wednesday") == expected_wed

    # Friday
    fri_ahead = 4 - cur_weekday
    if fri_ahead <= 0:
        fri_ahead += 7
    expected_fri = (today + timedelta(days=fri_ahead)).strftime("%Y-%m-%d")

    assert parse_human_date("Friday") == expected_fri
    assert parse_human_date("Friday.") == expected_fri
    assert parse_human_date("by Friday") == expected_fri

def test_parse_human_date_relative_weeks_and_days():
    today = datetime.now()
    assert parse_human_date("next week") == (today + timedelta(days=7)).strftime("%Y-%m-%d")
    assert parse_human_date("in next week") == (today + timedelta(days=7)).strftime("%Y-%m-%d")
    assert parse_human_date("in a week") == (today + timedelta(days=7)).strftime("%Y-%m-%d")
    assert parse_human_date("in 1 week") == (today + timedelta(days=7)).strftime("%Y-%m-%d")
    assert parse_human_date("in 2 weeks") == (today + timedelta(days=14)).strftime("%Y-%m-%d")
    assert parse_human_date("in 3 days") == (today + timedelta(days=3)).strftime("%Y-%m-%d")
    assert parse_human_date("in 3 days.") == (today + timedelta(days=3)).strftime("%Y-%m-%d")
    assert parse_human_date("today.") == today.strftime("%Y-%m-%d")
    assert parse_human_date("due today") == today.strftime("%Y-%m-%d")
    assert parse_human_date("due tomorrow") == (today + timedelta(days=1)).strftime("%Y-%m-%d")

def test_parse_human_date_specific_dates():
    today = datetime.now()
    assert parse_human_date("15th Oct") == f"{today.year}-10-15"
    assert parse_human_date("15th October") == f"{today.year}-10-15"
    assert parse_human_date("15th of October") == f"{today.year}-10-15"
    assert parse_human_date("Oct 15") == f"{today.year}-10-15"
    assert parse_human_date("October 15") == f"{today.year}-10-15"
    assert parse_human_date("2026-10-15") == "2026-10-15"
    assert parse_human_date("15-10-2026") == "2026-10-15"
    assert parse_human_date("15/10/2026") == "2026-10-15"
    assert parse_human_date("15 Oct 2026") == "2026-10-15"

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
