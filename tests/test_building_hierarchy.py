"""
Unit tests for Building Hierarchy, Access Control, and Serial Number Mapping.
"""

import pytest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db import check_building_access, get_tasks_by_buildings
from core.intent_handlers import build_building_grouped_tasks


def test_build_building_grouped_tasks_formatting_and_continuous_numbering():
    building_data = [
        {
            "building_name": "GETT",
            "building_id": "b1",
            "projects": [
                {
                    "project_name": "Project Alpha",
                    "project_id": "p1",
                    "tasks": [
                        {"id": "t1", "title": "Check chiller panel", "progress": 20, "status": "Pending"},
                        {"id": "t2", "title": "Inspect wiring", "progress": 50, "status": "Pending"}
                    ]
                }
            ]
        },
        {
            "building_name": "GEBB1",
            "building_id": "b2",
            "projects": [
                {
                    "project_name": "Project Beta",
                    "project_id": "p2",
                    "tasks": [
                        {"id": "t3", "title": "Waterproofing test", "progress": 0, "status": "Pending"}
                    ]
                }
            ]
        },
        {
            "building_name": "GEBB2",
            "building_id": "b3",
            "projects": [
                {
                    "project_name": "Project Gamma",
                    "project_id": "p3",
                    "tasks": [
                        {"id": "t4", "title": "Tile removal", "progress": 80, "status": "Pending"}
                    ]
                }
            ]
        }
    ]

    personal_tasks = [
        {"id": "t5", "title": "Buy safety gear", "progress": 100, "status": "Completed"}
    ]

    formatted_text, stored_task_ids = build_building_grouped_tasks(building_data, personal_tasks=personal_tasks)

    # 1. Verify building headings exist
    assert "*GETT*" in formatted_text
    assert "*GEBB1*" in formatted_text
    assert "*GEBB2*" in formatted_text
    assert "👤 *My Personal Tasks*" in formatted_text

    # 2. Verify continuous serial numbering
    assert "1. Check chiller panel" in formatted_text
    assert "2. Inspect wiring" in formatted_text
    assert "3. Waterproofing test" in formatted_text
    assert "4. Tile removal" in formatted_text
    assert "5. Buy safety gear" in formatted_text

    # 3. Verify task ID mapping order matches continuous serial numbers
    assert stored_task_ids == ["t1", "t2", "t3", "t4", "t5"]


@patch("db.supabase")
@patch("db.get_user_by_id")
def test_check_building_access(mock_get_user_by_id, mock_supabase):
    # Test 1: Personal task -> always allowed
    mock_task_res = MagicMock()
    mock_task_res.data = [{"project_id": "p1", "task_type": "PERSONAL", "projects": {"building_id": "b1"}}]
    mock_supabase.table().select().eq().execute.return_value = mock_task_res

    assert check_building_access("user1", "t_personal") is True

    # Test 2: Building task with user having access
    mock_task_res.data = [{"project_id": "p1", "task_type": "TEAM", "projects": {"building_id": "b1"}}]
    mock_bu_res = MagicMock()
    mock_bu_res.data = [{"id": "bu1"}]
    mock_supabase.table().select().eq().eq().execute.return_value = mock_bu_res

    assert check_building_access("user1", "t_team") is True

    # Test 3: Building task with user NOT having access
    mock_get_user_by_id.return_value = {"role": "Employee"}
    mock_bu_res.data = []
    mock_supabase.table().select().eq().eq().execute.return_value = mock_bu_res

    assert check_building_access("ritesh_id", "t_gebb2") is False
