from __future__ import annotations

"""
Facilities Module — Owner Position Resolver
=============================================
Central module for resolving Google Sheet Owner Position titles to
actual application users and vice versa.

The Google Sheet "Owner" column contains POSITION TITLES (e.g.,
"Facility Manager GEBB1"), not employee names. This module bridges
that gap using the `facilities_owner_positions` database table.

ALL position↔user resolution in the application MUST go through this
module. Do NOT hardcode position→user mappings elsewhere.
"""

import logging
from functools import lru_cache
from typing import Optional

from db import supabase

logger = logging.getLogger(__name__)

# ── In-memory cache (refreshed on demand) ────────────────────────────────────
_position_cache: list[dict] | None = None
_cache_loaded = False


def _load_cache(force: bool = False) -> list[dict]:
    """Load all position mappings from the database into memory."""
    global _position_cache, _cache_loaded
    if _position_cache is not None and _cache_loaded and not force:
        return _position_cache

    try:
        res = supabase.table("facilities_owner_positions").select("*").execute()
        _position_cache = res.data or []
        _cache_loaded = True
        logger.info(f"Owner position cache loaded: {len(_position_cache)} mappings")
        return _position_cache
    except Exception as e:
        logger.error(f"Failed to load owner position cache: {e}")
        if _position_cache is not None:
            return _position_cache
        return []


def refresh_cache():
    """Force-refresh the in-memory position cache."""
    _load_cache(force=True)


# ── Core Resolution Functions ────────────────────────────────────────────────

def normalize_position_title(pos: str) -> str:
    """Normalize a position title for consistent comparison and lookup."""
    if not pos:
        return ""
    clean = " ".join(pos.strip().lower().split())
    # Handle singular/plural variations: 'facilities' vs 'facility'
    clean = clean.replace("facilities ", "facility ")
    # Handle aliases
    if clean in ("head", "facility head", "facilities head"):
        return "facility head"
    if clean in ("director", "facility director", "facilities director"):
        return "facility director"
    return clean


def resolve_position_to_user(position_title: str, building: str = None) -> dict | None:
    """
    Resolve a Google Sheet Owner position title to a user.

    Args:
        position_title: The exact position title from the Sheet's Owner column
                        (e.g., "Facility Manager GEBB1" or "Facility Manager")
        building: Optional building context (e.g. "GEBB1")

    Returns:
        dict with: position_title, user_name, building
        None if position not found in mapping
    """
    if not position_title:
        return None

    clean = position_title.strip()
    norm_input = normalize_position_title(clean)
    mappings = _load_cache()

    # 1. If building is provided, try matching both title and building
    if building:
        for m in mappings:
            norm_m = normalize_position_title(m.get("position_title", ""))
            if (norm_m == norm_input and
                (m.get("building") or "").upper() == building.upper()):
                return {
                    "position_title": m["position_title"],
                    "user_name": m["user_name"],
                    "building": m.get("building"),
                }

    # 2. Try matching cross-building positions (building is None)
    for m in mappings:
        norm_m = normalize_position_title(m.get("position_title", ""))
        if norm_m == norm_input and m.get("building") is None:
            return {
                "position_title": m["position_title"],
                "user_name": m["user_name"],
                "building": m.get("building"),
            }

    # 3. Try any normalized title match
    for m in mappings:
        norm_m = normalize_position_title(m.get("position_title", ""))
        if norm_m == norm_input:
            return {
                "position_title": m["position_title"],
                "user_name": m["user_name"],
                "building": m.get("building"),
            }

    # 4. Standard position fallbacks
    if norm_input in ("facility head", "facilities head"):
        return {"position_title": "Facility Head", "user_name": "Anoop", "building": None}
    if norm_input in ("facility director", "facilities director"):
        return {"position_title": "Facilities Director", "user_name": "Kanav", "building": None}

    logger.warning(
        f"No user mapping found for Owner Position: '{position_title}'"
        + (f" in building {building}" if building else "")
        + ". This position exists in the Google Sheet but has no mapped user."
    )
    return None


def resolve_user_to_positions(user_name: str, building: str = None) -> list[dict]:
    """
    Resolve a user name to all their Owner Position titles.

    Handles aliases: "Vikram" and "Vikramjeet" are treated as the same person.

    Args:
        user_name: Employee name (e.g., "Vikramjeet", "Vikash", "Anoop")
        building: Optional building to filter positions for

    Returns:
        list of dicts: [{"position_title": "...", "user_name": "...", "building": "..."}, ...]
    """
    if not user_name:
        return []

    # Normalize known aliases
    canonical = _normalize_user_name(user_name)
    mappings = _load_cache()

    results = []
    for m in mappings:
        mapped_canonical = _normalize_user_name(m.get("user_name", ""))
        if mapped_canonical == canonical:
            if building and m.get("building") and m["building"] != building:
                continue
            results.append({
                "position_title": m["position_title"],
                "user_name": m["user_name"],
                "building": m.get("building"),
            })

    # For cross-building positions (building=NULL), include them when no building filter
    # or always include them
    if building:
        # Also include cross-building positions (building IS NULL)
        for m in mappings:
            mapped_canonical = _normalize_user_name(m.get("user_name", ""))
            if mapped_canonical == canonical and m.get("building") is None:
                if not any(r["position_title"] == m["position_title"] for r in results):
                    results.append({
                        "position_title": m["position_title"],
                        "user_name": m["user_name"],
                        "building": m.get("building"),
                    })

    # Fallback for standard known roles if not in DB cache
    if not results:
        if canonical == "anoop":
            results.append({"position_title": "Facility Head", "user_name": "Anoop", "building": None})
        elif canonical == "kanav":
            results.append({"position_title": "Facilities Director", "user_name": "Kanav", "building": None})

    return results


def get_position_titles_for_user(user_name: str, building: str = None) -> list[str]:
    """
    Get a list of Owner Position titles for a user, including standard variations.

    Args:
        user_name: Employee name
        building: Optional building filter

    Returns:
        List of position title strings
    """
    positions = resolve_user_to_positions(user_name, building)
    titles = [p["position_title"] for p in positions]
    canonical = _normalize_user_name(user_name)

    # Include synonyms for robustness
    if canonical == "anoop" or any(normalize_position_title(t) == "facility head" for t in titles):
        for syn in ["Facility Head", "Facilities Head"]:
            if syn not in titles:
                titles.append(syn)
    elif canonical == "kanav" or any(normalize_position_title(t) == "facility director" for t in titles):
        for syn in ["Facilities Director", "Facility Director"]:
            if syn not in titles:
                titles.append(syn)

    return titles


def get_responsible_user_whatsapp(position_title: str, building: str = None) -> dict | None:
    """
    Resolve a position title to user + WhatsApp number.

    Args:
        position_title: Owner position from the Sheet
        building: Optional building context

    Returns:
        dict with: user_name, whatsapp_number
        None if position not mapped or user has no WhatsApp number
    """
    mapping = resolve_position_to_user(position_title, building=building)
    if not mapping:
        return None

    user_name = mapping["user_name"]

    try:
        res = supabase.table("users").select(
            "name, whatsapp_number"
        ).eq("name", user_name).execute()

        if res.data and res.data[0].get("whatsapp_number"):
            return {
                "user_name": res.data[0]["name"],
                "whatsapp_number": res.data[0]["whatsapp_number"],
            }

        logger.warning(
            f"User '{user_name}' (mapped from position '{position_title}') "
            f"has no WhatsApp number configured."
        )
        return None

    except Exception as e:
        logger.error(f"Failed to look up WhatsApp number for '{user_name}': {e}")
        return None


def get_all_position_mappings() -> list[dict]:
    """
    Get all position → user mappings.

    Returns:
        list of dicts from the facilities_owner_positions table
    """
    return _load_cache()


def get_all_known_employee_names() -> list[str]:
    """
    Get a deduplicated list of all employee names that have position mappings.
    Useful for matching user input against known employees.

    Returns:
        List of unique employee names
    """
    mappings = _load_cache()
    names = set()
    for m in mappings:
        names.add(m.get("user_name", ""))
    return sorted(n for n in names if n)


def match_employee_name(text: str) -> str | None:
    """
    Fuzzy-match a user-typed employee name against known mapped employees.

    Args:
        text: Raw user input (e.g., "vikram", "vikramjeet", "anoop")

    Returns:
        Matched canonical employee name, or None
    """
    if not text:
        return None

    clean = text.strip().lower()
    known_names = get_all_known_employee_names()

    # 1. Exact match (case-insensitive)
    for name in known_names:
        if clean == name.lower():
            return name

    # 2. Alias match
    normalized = _normalize_user_name(clean)
    for name in known_names:
        if _normalize_user_name(name) == normalized:
            return name

    # 3. Fuzzy match
    try:
        from rapidfuzz import fuzz, process as fuzz_process
        match = fuzz_process.extractOne(clean, [n.lower() for n in known_names], scorer=fuzz.WRatio)
        if match and match[1] >= 75:
            # Return the original-cased name
            matched_lower = match[0]
            for name in known_names:
                if name.lower() == matched_lower:
                    return name
    except ImportError:
        pass

    return None


def is_employee_name(text: str) -> bool:
    """Check if a given text matches a known employee name."""
    return match_employee_name(text) is not None


# ── Internal Helpers ─────────────────────────────────────────────────────────

# Known aliases: maps variant → canonical name
_NAME_ALIASES = {
    "vikram": "vikramjeet",
    "vikramjeet": "vikramjeet",
    "anoop": "anoop",
    "anup": "anoop",
    "facility head": "anoop",
    "facilities head": "anoop",
    "head": "anoop",
    "kanav": "kanav",
    "kk": "kanav",
    "director": "kanav",
    "facility director": "kanav",
    "facilities director": "kanav",
    "vikash": "vikash",
    "vikkas": "vikash",
    "abhijeet": "abhijeet",
}


def _normalize_user_name(name: str) -> str:
    """Normalize a user name to its canonical lowercase form, resolving aliases."""
    clean = " ".join(name.strip().lower().split())
    return _NAME_ALIASES.get(clean, clean)
