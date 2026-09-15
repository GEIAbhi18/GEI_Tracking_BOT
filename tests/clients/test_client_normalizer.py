from __future__ import annotations
import pytest
from clients.normalizer import (
    normalize_mobile_number,
    normalize_building,
    generate_sync_key,
    normalize_client_row,
)


def test_normalize_mobile_number():
    cases = [
        ("9876543210", "919876543210"),
        ("+91 9876543210", "919876543210"),
        ("91 9876543210", "919876543210"),
        ("+91-9876543210", "919876543210"),
        ("09876543210", "919876543210"),
        (" +91 (987) 654-3210 ", "919876543210"),
        ("8826896085", "918826896085"),
        ("", ""),
        (None, ""),
    ]
    for inp, expected in cases:
        # pyrefly: ignore [bad-argument-type]
        assert normalize_mobile_number(inp) == expected, f"Failed for '{inp}'"


def test_normalize_building():
    assert normalize_building("GEBB I") == "GEBB1"
    assert normalize_building("GEBB-1") == "GEBB1"
    assert normalize_building("GEBB 1") == "GEBB1"
    assert normalize_building("BAY 1") == "GEBB1"
    assert normalize_building("GEBB II") == "GEBB2"
    assert normalize_building("GEBB-2") == "GEBB2"
    assert normalize_building("Buisness Bay 2") == "GEBB2"
    assert normalize_building("BAY 2") == "GEBB2"
    assert normalize_building("GETT") == "GETT"


def test_generate_sync_key():
    k1 = generate_sync_key("MASTER", "GEBB1", "HDFC Bank", "Ground Floor", "R1/R2", "918826896085")
    k2 = generate_sync_key("MASTER", "GEBB1", "HDFC Bank", "Ground Floor", "R1/R2", "918826896085")
    assert k1 == k2  # Deterministic

    # Different unit produces different sync_key (multi-unit support)
    k3 = generate_sync_key("MASTER", "GEBB2", "Indus", "2nd Floor", "201", "919958995715")
    k4 = generate_sync_key("MASTER", "GEBB2", "Indus", "10th Floor", "1001", "919958995715")
    assert k3 != k4


def test_normalize_client_row_valid():
    row = {
        "Tenant Company Name": "HDFC Bank ",
        "Building Name": "GEBB I",
        "Floor": "GROUND FLOOR",
        "Unit Number": "R1/R2",
        "Admin Contact Name": "Rakesh Kumar ",
        "Designation": "Admin",
        "Primary Mobile Number": "8826896085",
        "Primary Contact Email ID": "rakesh@hdfcbank.in",
    }
    rec, is_valid, errors = normalize_client_row(row, "MASTER")
    assert is_valid is True
    assert len(errors) == 0
    assert rec["company_name"] == "HDFC Bank"
    assert rec["building"] == "GEBB1"
    assert rec["mobile_number"] == "918826896085"
    assert rec["admin_name"] == "Rakesh Kumar"
    assert rec["sync_key"] is not None


def test_normalize_client_row_missing_mobile():
    row = {
        "Tenant Company Name": "NEXUS",
        "Building Name": "GEBB I",
        "Floor": "4th FLOOR",
        "Unit Number": "412",
        "Admin Contact Name": "",
        "Primary Mobile Number": "",
    }
    rec, is_valid, errors = normalize_client_row(row, "MASTER")
    assert is_valid is False
    assert any("mobile" in e.lower() for e in errors)
