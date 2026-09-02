from __future__ import annotations

"""
Facilities Module — Identity & Permissions
============================================
Resolves Facilities users from their WhatsApp number and enforces
building-level access control.

Every downstream query in the facilities module must call
resolve_facilities_user() first and scope to permitted_buildings.
"""

import logging
from rapidfuzz import fuzz, process as fuzz_process

from db import supabase
from facilities.config import BUILDING_TABS, BUILDING_ALIASES

logger = logging.getLogger(__name__)


def resolve_facilities_user(whatsapp_number: str) -> dict | None:
    """
    Resolve a WhatsApp number to a Facilities user with permissions.

    Returns:
        dict with: id, name, role, department, whatsapp_number,
                   permitted_buildings[], is_facilities_user (bool)
        None if the user doesn't exist at all
    """
    try:
        res = supabase.table("users").select(
            "id, name, role, department, whatsapp_number, permitted_buildings"
        ).eq("whatsapp_number", whatsapp_number).execute()

        if not res.data:
            return None

        user = res.data[0]
        role = user.get("role", "")
        department = user.get("department", "")
        user["is_facilities_user"] = (
            role in ("Director", "Developer")
            or (department == "Facilities" and bool(user.get("permitted_buildings")))
            or bool(user.get("permitted_buildings"))
        )
        return user

    except Exception as e:
        logger.error(f"resolve_facilities_user failed for {whatsapp_number}: {e}")
        return None


def is_all_buildings_user(user: dict) -> bool:
    """Check if the user has cross-building access (Director, Developer, Facility Head, Anoop)."""
    if not user:
        return False
    role = (user.get("role") or "").strip().lower()
    name = (user.get("name") or "").strip().lower()
    if role in ("director", "developer", "facility head", "facilities head"):
        return True
    if name in ("anoop", "facility head", "facilities head", "kanav", "abhijeet"):
        return True
    return False


def assert_building_access(user: dict, building: str) -> bool:
    """
    Check if the user has access to the given building.

    Args:
        user: User dict from resolve_facilities_user()
        building: Building code (e.g., 'GEBB1')

    Returns:
        True if access is granted

    Raises:
        PermissionError with Screen 14's exact denial message
    """
    if is_all_buildings_user(user):
        return True

    permitted = user.get("permitted_buildings", [])

    if building not in permitted:
        raise PermissionError(
            f"You don't have access to {building}. "
            f"Your permitted buildings: {', '.join(permitted) if permitted else 'None'}. "
            f"Contact your manager to request access."
        )

    return True


def get_permitted_buildings(user: dict) -> list:
    """
    Get the list of buildings the user is permitted to access.

    Directors/Developers/Facility Heads get all buildings.
    """
    if is_all_buildings_user(user):
        return BUILDING_TABS.copy()

    return user.get("permitted_buildings", [])


def fuzzy_match_building(text: str) -> str | None:
    """
    Fuzzy-match a user-typed building name to a valid building code.

    First checks exact aliases, then falls back to rapidfuzz matching.

    Args:
        text: Raw user input (e.g., 'bay 1', 'gett', 'business bay 2')

    Returns:
        Matched building code (e.g., 'GEBB1') or None if no match
    """
    clean = text.strip().lower()

    # 1. Exact alias match
    if clean in BUILDING_ALIASES:
        return BUILDING_ALIASES[clean]

    # 2. Check if it's already a valid building code (case-insensitive)
    for tab in BUILDING_TABS:
        if clean == tab.lower():
            return tab

    # 3. Fuzzy match against all aliases and building names
    all_options = list(BUILDING_ALIASES.keys()) + [t.lower() for t in BUILDING_TABS]
    match = fuzz_process.extractOne(clean, all_options, scorer=fuzz.WRatio)

    if match and match[1] >= 75:  # 75% confidence threshold
        matched_key = match[0]
        if matched_key in BUILDING_ALIASES:
            return BUILDING_ALIASES[matched_key]
        # It's a building tab name
        for tab in BUILDING_TABS:
            if matched_key == tab.lower():
                return tab

    return None


def get_fuzzy_building_suggestions(text: str) -> list:
    """
    Get a ranked list of building suggestions for a "did you mean" prompt.

    Returns a list of dicts: [{"building": "GEBB1", "score": 85}, ...]
    """
    clean = text.strip().lower()
    all_options = list(BUILDING_ALIASES.keys()) + [t.lower() for t in BUILDING_TABS]

    matches = fuzz_process.extract(clean, all_options, scorer=fuzz.WRatio, limit=4)

    suggestions = []
    seen = set()
    for match_text, score, _ in matches:
        if score < 50:
            continue

        if match_text in BUILDING_ALIASES:
            building = BUILDING_ALIASES[match_text]
        else:
            building = match_text.upper()
            if building not in BUILDING_TABS:
                continue

        if building not in seen:
            seen.add(building)
            suggestions.append({"building": building, "score": score})

    return suggestions


def get_facilities_team_members(building: str = None) -> list:
    """
    Get all Facilities department users, optionally filtered by building.

    Returns:
        list of user dicts with: id, name, whatsapp_number, role, permitted_buildings
    """
    try:
        query = supabase.table("users").select(
            "id, name, whatsapp_number, role, permitted_buildings"
        ).eq("department", "Facilities")

        result = query.execute()
        users = result.data or []

        if building:
            users = [
                u for u in users
                if building in (u.get("permitted_buildings") or [])
            ]

        return users

    except Exception as e:
        logger.error(f"get_facilities_team_members failed: {e}")
        return []
