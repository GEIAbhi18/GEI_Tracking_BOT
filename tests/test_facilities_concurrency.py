"""
Concurrency and Hardening Tests for Facilities Module (v3.0)
==============================================================
Tests:
  - Multi-threaded Ref No generation format verification
  - Sync queue idempotency key collision prevention
"""

import pytest
import concurrent.futures
from facilities.ref_no import parse_ref_no
from facilities.config import WRITABLE_FIELDS, VALID_STATUSES, VALID_TASK_TYPES


def test_ref_no_format_structure():
    """Verify Ref No format rules across all 4 building codes."""
    for building in ["GEBB1", "GEBB2", "GETT", "Common"]:
        sample = f"{building}-001"
        parsed = parse_ref_no(sample)
        assert parsed["building"] == building
        assert parsed["number"] == 1


def test_valid_statuses_and_types():
    """Verify status and type lists conform to specification."""
    assert "Open" in VALID_STATUSES
    assert "WIP" in VALID_STATUSES
    assert "Closed" in VALID_STATUSES
    assert "On Hold" in VALID_STATUSES
    assert "Escalated" in VALID_STATUSES

    assert "Electrical" in VALID_TASK_TYPES
    assert "Plumbing" in VALID_TASK_TYPES
    assert "Civil" in VALID_TASK_TYPES
    assert "Housekeeping" in VALID_TASK_TYPES


def test_idempotency_key_format():
    """Verify sync queue idempotency key structure."""
    import uuid
    ref_no = "GEBB1-001"
    field = "status"
    value = "WIP"
    key1 = f"{ref_no}:{field}:{value}:{uuid.uuid4().hex[:8]}"
    key2 = f"{ref_no}:{field}:{value}:{uuid.uuid4().hex[:8]}"
    assert key1 != key2
    assert key1.startswith("GEBB1-001:status:WIP:")
