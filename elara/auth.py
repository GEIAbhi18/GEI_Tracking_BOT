from __future__ import annotations
import logging
from db import supabase
from whatsapp.ux import clean_phone_number
from elara.config import DEVELOPER_PHONE, KANAV_PHONE

logger = logging.getLogger(__name__)


def resolve_elara_user(whatsapp_number: str) -> dict | None:
    """
    Resolve a WhatsApp number to an Elara Home user.
    Queries ONLY the `elara_users` table in Supabase.
    """
    clean_num = clean_phone_number(whatsapp_number)
    if not clean_num:
        return None

    try:
        # Check by clean phone
        res = supabase.table("elara_users").select("*").eq("phone", clean_num).execute()
        if res.data:
            user = res.data[0]
            user["is_elara_user"] = True
            return user

        # Also check without country code prefix (e.g. 10 digits) if applicable
        if len(clean_num) > 10 and clean_num.startswith("91"):
            short_num = clean_num[2:]
            res = supabase.table("elara_users").select("*").eq("phone", short_num).execute()
            if res.data:
                user = res.data[0]
                user["is_elara_user"] = True
                return user

        # Special check for Developer number or Kanav number
        if clean_num == DEVELOPER_PHONE:
            res = supabase.table("elara_users").select("*").eq("role", "Developer").execute()
            if res.data and isinstance(res.data, list) and isinstance(res.data[0], dict):
                user = dict(res.data[0])
                user["is_elara_user"] = True
                return user
            return {"id": "elara-dev-01", "name": "Developer", "role": "Developer", "phone": clean_num, "department": "Project Administration", "is_elara_user": True}

        elif clean_num == KANAV_PHONE:
            res = supabase.table("elara_users").select("*").eq("name", "Kanav").execute()
            if res.data and isinstance(res.data, list) and isinstance(res.data[0], dict):
                user = dict(res.data[0])
                user["is_elara_user"] = True
                return user
            return {"id": "elara-kanav-01", "name": "Kanav", "role": "Director", "phone": clean_num, "department": "Project Administration", "is_elara_user": True}

        return None
    except Exception as e:
        logger.error(f"resolve_elara_user failed for {whatsapp_number}: {e}")
        return None


def is_elara_user(user_or_phone: str | dict | None) -> bool:
    """Check if user dict or WhatsApp number belongs to Elara Home team."""
    if not user_or_phone:
        return False
    if isinstance(user_or_phone, dict):
        if user_or_phone.get("team") == "Elara Home" or user_or_phone.get("is_elara_user"):
            return True
        phone = user_or_phone.get("phone") or user_or_phone.get("whatsapp_number")
        if not phone:
            return False
        user = resolve_elara_user(str(phone))
        return user is not None and user.get("is_elara_user", False)
    # pyrefly: ignore [unnecessary-type-conversion]
    user = resolve_elara_user(str(user_or_phone))
    return user is not None and user.get("is_elara_user", False)



def is_elara_admin(user: dict | None) -> bool:
    """Director (Kanav) and Developer have full cross-department access."""
    if not user:
        return False
    role = (user.get("role") or "").strip().lower()
    name = (user.get("name") or "").strip().lower()
    phone = clean_phone_number(user.get("phone") or user.get("whatsapp_number"))

    if role in ("director", "developer"):
        return True
    if name in ("kanav", "developer", "abhijeet"):
        return True
    if phone in (DEVELOPER_PHONE, KANAV_PHONE):
        return True
    return False


def can_access_department(user: dict | None, department: str) -> bool:
    """Check if user is permitted to access the given department."""
    if not user:
        return False
    if is_elara_admin(user):
        return True
    user_dept = (user.get("department") or "").strip()
    if not user_dept or user_dept.lower() == department.strip().lower():
        return True
    return False


def get_elara_team_members(department: str | None = None) -> list:
    """Get all Elara team members, optionally filtered by department."""
    try:
        query = supabase.table("elara_users").select("*")
        if department:
            query = query.eq("department", department)
        res = query.execute()
        return res.data or []
    except Exception as e:
        logger.error(f"get_elara_team_members failed: {e}")
        return []
