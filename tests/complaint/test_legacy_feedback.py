#!/usr/bin/env python3
"""
Local Feedback Test Script
===========================
Tests the feedback module WITHOUT deploying to Render.
Run from project root: python test_feedback_local.py

Tests:
  1. Session creation & retrieval
  2. Phone normalization
  3. Flow response processing (with mocked WhatsApp send)
  4. Score calculation, sentiment, escalation logic
  5. Google Sheets connectivity (optional — set TEST_SHEETS=1)

Usage:
  python test_feedback_local.py              # Core logic tests (no network)
  TEST_SHEETS=1 python test_feedback_local.py  # Also test Sheets connectivity
"""

import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
load_dotenv()

# Track all test results
RESULTS = []
WA_MESSAGES_SENT = []  # Capture sent messages


def _mock_send_text(phone, text):
    """Mock WhatsApp send — captures messages instead of sending."""
    WA_MESSAGES_SENT.append({"phone": phone, "text": text})
    print(f"  [MOCK WA] → {phone}: {text[:80]}...")
    return True


def mark_pass(name):
    RESULTS.append(("✅", name))
    print(f"  ✅ {name}")


def mark_fail(name, reason):
    RESULTS.append(("❌", f"{name}: {reason}"))
    print(f"  ❌ {name}: {reason}")


def run_tests():
    print("\n" + "=" * 70)
    print("  GEI FEEDBACK MODULE — LOCAL TEST SUITE")
    print("=" * 70)

    # ── Test 1: Phone Normalization ──────────────────────────────────────
    print("\n── Test 1: Phone Normalization ──")
    from feedback.session_store import normalize_phone

    cases = [
        ("+917717754421", "917717754421"),
        ("917717754421", "917717754421"),
        ("7717754421", "917717754421"),
        (" +91 7717 754 421 ", "917717754421"),
        ("", ""),
    ]
    all_pass = True
    for inp, expected in cases:
        result = normalize_phone(inp)
        if result == expected:
            print(f"  ✓ normalize_phone('{inp}') = '{result}'")
        else:
            print(f"  ✗ normalize_phone('{inp}') = '{result}' (expected '{expected}')")
            all_pass = False

    if all_pass:
        mark_pass("Phone normalization")
    else:
        mark_fail("Phone normalization", "Some cases failed")

    # ── Test 2: Session Creation ─────────────────────────────────────────
    print("\n── Test 2: Session Creation ──")
    from feedback.session_store import (
        create_session, set_session, get_session, remove_session,
        has_active_session, normalize_phone, _sessions, _lock,
    )
    from feedback.config import STAGE_FLOW_SENT, STAGE_DONE

    test_data = {
        "complaintId": "TEST-001",
        "clientPhone": "+917717754421",
        "clientName": "Test User",
        "unitNo": "101",
        "complaintNature": "HVAC",
        "complaintDetails": "AC not working",
        "building": "GEBB1",
        "closedAt": "2026-06-08 10:00:00",
    }

    session = create_session(test_data)
    if session["complaintId"] == "TEST-001":
        mark_pass("Session created with correct complaint ID")
    else:
        mark_fail("Session creation", f"Got {session['complaintId']}")

    if session["stage"] == STAGE_FLOW_SENT:
        mark_pass("Session stage is 'flow_sent'")
    else:
        mark_fail("Session stage", f"Got {session['stage']}")

    if session["clientPhone"] == "917717754421":
        mark_pass("Session phone normalized correctly")
    else:
        mark_fail("Session phone", f"Got {session['clientPhone']}")

    # ── Test 3: Session Store (in-memory) ────────────────────────────────
    print("\n── Test 3: Session Store (in-memory) ──")

    # Monkey-patch to avoid async sheet backup during test
    import feedback.session_store as ss
    original_backup = ss._backup_session_async
    ss._backup_session_async = lambda s: None  # no-op

    phone = "917717754421"
    set_session(phone, session)

    retrieved = get_session(phone)
    if retrieved and retrieved["complaintId"] == "TEST-001":
        mark_pass("Session stored and retrieved correctly")
    else:
        mark_fail("Session retrieval", f"Got {retrieved}")

    if has_active_session(phone):
        mark_pass("has_active_session returns True")
    else:
        mark_fail("has_active_session", "Returned False")

    # ── Test 4: Flow Response Processing ─────────────────────────────────
    print("\n── Test 4: Flow Response Processing ──")

    # Monkey-patch WhatsApp send to use mock
    import feedback.engine as engine
    engine._send_wa = _mock_send_text

    # Also monkey-patch remove_session to skip sheet operations
    original_remove = ss._remove_from_sheet_sync
    ss._remove_from_sheet_sync = lambda cid: None  # no-op

    WA_MESSAGES_SENT.clear()

    flow_response = {
        "resolution_rating": "4",
        "facility_team_rating": "5",
        "overall_rating": "4",
        "comments": "Good service, very prompt",
    }

    # Process the flow response (without sheet writes)
    from feedback.engine import handle_flow_response

    # Monkey-patch sheet writes to no-op for this test
    import feedback.sheets as sheets_mod
    original_update_building = getattr(sheets_mod, 'update_building_sheet_feedback', None)
    original_update_master = getattr(sheets_mod, 'update_master_feedback', None)
    original_append_esc = getattr(sheets_mod, 'append_escalation', None)

    sheets_mod.update_building_sheet_feedback = lambda *a, **kw: True
    sheets_mod.update_master_feedback = lambda *a, **kw: True
    sheets_mod.append_escalation = lambda *a, **kw: True

    handled = handle_flow_response(phone, flow_response)

    if handled:
        mark_pass("handle_flow_response returned True")
    else:
        mark_fail("handle_flow_response", "Returned False — session not found!")

    # Check thank-you message was sent
    thank_you_msgs = [m for m in WA_MESSAGES_SENT if "Thank you" in m["text"] or "thank you" in m["text"].lower()]
    if thank_you_msgs:
        mark_pass(f"Thank-you message sent to {thank_you_msgs[0]['phone']}")
    else:
        mark_fail("Thank-you message", f"Not sent! Messages captured: {WA_MESSAGES_SENT}")

    # Check session was cleaned up
    if not has_active_session(phone):
        mark_pass("Session cleaned up after completion")
    else:
        mark_fail("Session cleanup", "Session still active!")

    # ── Test 5: Score Calculation & Sentiment ────────────────────────────
    print("\n── Test 5: Score Calculation & Sentiment ──")

    test_scores = [
        ((5, 5, 5), 5.0, "Happy"),
        ((4, 4, 4), 4.0, "Happy"),
        ((3, 3, 3), 3.0, "Neutral"),
        ((2, 2, 2), 2.0, "Unhappy"),
        ((1, 1, 1), 1.0, "Unhappy"),
        ((4, 5, 3), 4.0, "Happy"),
        ((1, 2, 3), 2.0, "Unhappy"),
    ]

    all_pass = True
    for (q1, q2, q3), expected_score, expected_sentiment in test_scores:
        score = round(((q1 + q2 + q3) / 3) * 10) / 10
        if score >= 4:
            sentiment = "Happy"
        elif score >= 3:
            sentiment = "Neutral"
        else:
            sentiment = "Unhappy"

        if score == expected_score and sentiment == expected_sentiment:
            print(f"  ✓ ({q1},{q2},{q3}) → score={score} sentiment={sentiment}")
        else:
            print(f"  ✗ ({q1},{q2},{q3}) → score={score} (expected {expected_score}) sentiment={sentiment} (expected {expected_sentiment})")
            all_pass = False

    if all_pass:
        mark_pass("Score calculation & sentiment logic")
    else:
        mark_fail("Score calculation", "Some cases failed")

    # ── Test 6: Escalation Logic ─────────────────────────────────────────
    print("\n── Test 6: Escalation Logic ──")
    from feedback.config import NEGATIVE_KEYWORDS

    esc_cases = [
        (1.0, "poor service", True, "Low Score + Negative Comment"),
        (1.5, "all good", True, "Low Feedback Score"),
        (4.0, "terrible experience", True, "Negative Comment"),
        (4.0, "all good", False, ""),
        (3.0, "satisfactory", False, ""),
    ]

    all_pass = True
    for score, comment, expected_escalate, expected_reason in esc_cases:
        low_score = score <= 2
        negative_comment = any(k in comment.lower() for k in NEGATIVE_KEYWORDS)
        should_escalate = low_score or negative_comment

        if low_score and negative_comment:
            reason = "Low Score + Negative Comment"
        elif low_score:
            reason = "Low Feedback Score"
        elif negative_comment:
            reason = "Negative Comment"
        else:
            reason = ""

        if should_escalate == expected_escalate and reason == expected_reason:
            print(f"  ✓ score={score} comment='{comment}' → escalate={should_escalate}")
        else:
            print(f"  ✗ score={score} comment='{comment}' → escalate={should_escalate} (expected {expected_escalate})")
            all_pass = False

    if all_pass:
        mark_pass("Escalation logic")
    else:
        mark_fail("Escalation logic", "Some cases failed")

    # ── Test 7: Config / Env Vars ────────────────────────────────────────
    print("\n── Test 7: Environment Variables ──")
    from feedback.config import (
        GOOGLE_SERVICE_ACCOUNT_EMAIL, GOOGLE_PRIVATE_KEY,
        FEEDBACK_SHEET_ID, FEEDBACK_API_KEY,
        META_ACCESS_TOKEN, PHONE_NUMBER_ID,
        WHATSAPP_FLOW_ID, WHATSAPP_FLOW_TEMPLATE_NAME,
    )

    env_checks = [
        ("GOOGLE_SERVICE_ACCOUNT_EMAIL", GOOGLE_SERVICE_ACCOUNT_EMAIL),
        ("GOOGLE_PRIVATE_KEY", GOOGLE_PRIVATE_KEY),
        ("FEEDBACK_SHEET_ID", FEEDBACK_SHEET_ID),
        ("FEEDBACK_API_KEY", FEEDBACK_API_KEY),
        ("META_ACCESS_TOKEN", META_ACCESS_TOKEN),
        ("PHONE_NUMBER_ID", PHONE_NUMBER_ID),
        ("WHATSAPP_FLOW_ID", WHATSAPP_FLOW_ID),
        ("WHATSAPP_FLOW_TEMPLATE_NAME", WHATSAPP_FLOW_TEMPLATE_NAME),
    ]

    all_set = True
    for name, val in env_checks:
        if val:
            print(f"  ✓ {name} = {val[:20]}...")
        else:
            print(f"  ✗ {name} = MISSING!")
            all_set = False

    if all_set:
        mark_pass("All required env vars set")
    else:
        mark_fail("Environment variables", "Some vars missing")

    # ── Test 8: Google Sheets Connectivity (optional) ────────────────────
    if os.getenv("TEST_SHEETS") == "1":
        print("\n── Test 8: Google Sheets Connectivity ──")
        try:
            from feedback.sheets import _get_client, _get_spreadsheet, _get_worksheet
            client = _get_client()
            mark_pass(f"Google Sheets client created for {GOOGLE_SERVICE_ACCOUNT_EMAIL[:30]}...")

            ss = _get_spreadsheet()
            mark_pass(f"Spreadsheet opened: {ss.title}")

            ws = _get_worksheet("MASTER")
            headers = ws.row_values(1)
            mark_pass(f"MASTER sheet headers ({len(headers)} columns): {headers[:5]}...")

            # Check required columns exist
            required_cols = ["Complaint ID", "Feedback Status"]
            for col in required_cols:
                found = any(col.lower() in h.lower() for h in headers)
                if found:
                    print(f"  ✓ Column '{col}' found")
                else:
                    mark_fail(f"Column check", f"'{col}' NOT FOUND in MASTER headers: {headers}")

        except Exception as e:
            mark_fail("Google Sheets connectivity", str(e))
    else:
        print("\n── Test 8: Google Sheets (SKIPPED — set TEST_SHEETS=1 to enable) ──")

    # ── Restore monkey-patches ───────────────────────────────────────────
    ss._backup_session_async = original_backup
    ss._remove_from_sheet_sync = original_remove
    if original_update_building:
        sheets_mod.update_building_sheet_feedback = original_update_building
    if original_update_master:
        sheets_mod.update_master_feedback = original_update_master
    if original_append_esc:
        sheets_mod.append_escalation = original_append_esc

    # Clear any leftover test sessions
    with _lock:
        _sessions.pop("917717754421", None)

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    passed = sum(1 for r in RESULTS if r[0] == "✅")
    failed = sum(1 for r in RESULTS if r[0] == "❌")
    print(f"  RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    if failed > 0:
        print("\n  FAILURES:")
        for status, name in RESULTS:
            if status == "❌":
                print(f"    {status} {name}")

    print()
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
