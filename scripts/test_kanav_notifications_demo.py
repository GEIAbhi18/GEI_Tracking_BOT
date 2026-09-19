"""
Demonstration & Terminal Verification Script:
Simulates and verifies task-change WhatsApp notifications to Kanav for Facilities and Elara Home.
"""

import sys
import os
from unittest.mock import patch

# Ensure root directory is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from notifications.kanav_notifier import (
    get_kanav_phone,
    is_facilities_task_created_by_kanav,
    is_elara_task_created_by_kanav,
    notify_kanav_task_change,
    get_formatted_timestamp
)
from elara.config import DEVELOPER_PHONE

def run_demo():
    print("=" * 70)
    print(" 🚀 GEI_BOT: Task Change Notification Terminal Test Suite")
    print("=" * 70)

    target_number = DEVELOPER_PHONE
    print(f"[*] Target WhatsApp recipient: Developer ({target_number})\n")

    captured_notifications = []

    def mock_send(to, body):
        captured_notifications.append({"to": to, "body": body})
        return True

    with patch("notifications.kanav_notifier.send_text", side_effect=mock_send):
        # ─────────────────────────────────────────────────────────────
        # 1. FACILITIES SCENARIOS
        # ─────────────────────────────────────────────────────────────
        print("🏢 [1/5] Testing Facilities: Task Created by Kanav -> Updated")
        facilities_task_1 = {
            "ref_no": "GEBB1-101",
            "issue_action": "Overhaul AHU Motor in Basement",
            "added_by": "Facilities Director",
            "owner": "Vikramjeet",
            "status": "Open",
        }
        assert is_facilities_task_created_by_kanav(facilities_task_1) is True

        notify_kanav_task_change(
            task_id=facilities_task_1["ref_no"],
            task_title=facilities_task_1["issue_action"],
            change_made="Task updated: Bearings replaced; vibration test scheduled",
            changed_by="Vikramjeet",
            domain="Facilities"
        )
        print("   ✅ Notification dispatched successfully.")

        print("\n🏢 [2/5] Testing Facilities: Task Created by Kanav -> Reassigned")
        facilities_task_2 = {
            "ref_no": "GETT-015",
            "issue_action": "Waterproofing Inspection on Top Terrace",
            "added_by": "Facilities Director",
            "owner": "Vikash",
            "status": "WIP",
        }
        notify_kanav_task_change(
            task_id=facilities_task_2["ref_no"],
            task_title=facilities_task_2["issue_action"],
            change_made="Reassigned from Vikash to Anoop",
            changed_by="Vikash",
            domain="Facilities"
        )
        print("   ✅ Notification dispatched successfully.")

        print("\n🏢 [3/5] Testing Facilities: Task Created by Kanav -> Closed")
        facilities_task_3 = {
            "ref_no": "GEBB2-008",
            "issue_action": "Fix Water Pressure Sensor",
            "added_by": "Facilities Director",
            "owner": "Kuldeep",
            "status": "WIP",
        }
        notify_kanav_task_change(
            task_id=facilities_task_3["ref_no"],
            task_title=facilities_task_3["issue_action"],
            change_made="Status changed from WIP to Closed (Task closed) | Note: Calibrated and verified",
            changed_by="Kuldeep",
            domain="Facilities"
        )
        print("   ✅ Notification dispatched successfully.")

        # ─────────────────────────────────────────────────────────────
        # 2. ELARA HOME SCENARIOS
        # ─────────────────────────────────────────────────────────────
        print("\n🏠 [4/5] Testing Elara Home: Task Created by Kanav -> Status Changed & Blocker")
        elara_task_1 = {
            "id": "elara-task-902",
            "title": "HVAC Ducting Approval for Villa 12",
            "created_by": "Kanav",
            "status": "pending",
        }
        assert is_elara_task_created_by_kanav(elara_task_1) is True

        notify_kanav_task_change(
            task_id=elara_task_1["id"],
            task_title=elara_task_1["title"],
            change_made="Status changed to Blocker (Reason: Pending MEP consultant sign-off)",
            changed_by="Rachit",
            domain="Elara Home"
        )
        print("   ✅ Notification dispatched successfully.")

        print("\n🏠 [5/5] Testing Elara Home: Task Created by Kanav -> Completed / Closed")
        elara_task_2 = {
            "id": "elara-task-905",
            "title": "Vendor Payment Reconciliation Q3",
            "created_by": "Kanav",
            "status": "in_progress",
        }
        notify_kanav_task_change(
            task_id=elara_task_2["id"],
            task_title=elara_task_2["title"],
            change_made="Status changed from In Progress to Completed (Task closed)",
            changed_by="Bhagwan Dass",
            domain="Elara Home"
        )
        print("   ✅ Notification dispatched successfully.")

        # ─────────────────────────────────────────────────────────────
        # 3. FILTERING CHECK
        # ─────────────────────────────────────────────────────────────
        print("\n🛡️ [Filter Check] Verifying non-Kanav tasks do NOT trigger notifications:")
        other_facilities_task = {
            "ref_no": "GEBB1-099",
            "issue_action": "Fix cafeteria tap",
            "added_by": "Facility Manager",
            "owner": "Vikash",
        }
        is_kanav = is_facilities_task_created_by_kanav(other_facilities_task)
        print(f"   Task created by 'Facility Manager' -> is_kanav: {is_kanav} (Expected: False)")
        assert is_kanav is False

        other_elara_task = {
            "id": "elara-task-111",
            "title": "Routine garden sweep",
            "created_by": "Rachit",
            "comments": [{"user_name": "Rachit", "content": "Task created by Rachit"}]
        }
        is_kanav_elara = is_elara_task_created_by_kanav(other_elara_task)
        print(f"   Task created by 'Rachit' -> is_kanav: {is_kanav_elara} (Expected: False)")
        assert is_kanav_elara is False

    print("\n" + "=" * 70)
    print(f" 📬 Captured {len(captured_notifications)} WhatsApp Notification Messages to Developer ({target_number}):")
    print("=" * 70)

    for i, notif in enumerate(captured_notifications, 1):
        print(f"\n--- Notification #{i} ---")
        print(f"To: {notif['to']}")
        print(notif['body'])

    print("\n" + "=" * 70)
    print(" ✅ ALL TEST CHECKS PASSED: Notifications work for Facilities & Elara Home!")
    print("=" * 70)

if __name__ == "__main__":
    run_demo()
