"""
Unit and Integration Tests for Facilities Module (v3.0)
=========================================================
Tests:
  - Ref No parsing & format validation
  - Building alias & fuzzy matching
  - Conflict window logic
  - Sync queue status reporting
"""

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
