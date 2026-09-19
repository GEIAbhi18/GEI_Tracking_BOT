from __future__ import annotations
import logging
from db import supabase
from clients.normalizer import normalize_mobile_number
from clients.sync_engine import get_cached_clients

from clients.config import (
    TREAT_CHAITANYA_AS_TENANT_ONLY,
    CHAITANYA_TENANT_RECORD,
    is_chaitanya,
)

logger = logging.getLogger(__name__)

# Temporary in-memory state for selected client context when one number has multiple units
_SELECTED_CLIENT_CONTEXT = {}  # type: dict[str, dict]


def lookup_clients_by_phone(phone: str) -> list:
    """
    Looks up active client records by phone number.
    Normalizes the phone number first to ensure consistent matching.
    Tries Supabase first; falls back to in-memory sync cache if table is absent.
    """
    # 0. Chaitanya Tenant Override (strictly treated as Tenant only)
    if TREAT_CHAITANYA_AS_TENANT_ONLY and is_chaitanya(phone):
        return [dict(CHAITANYA_TENANT_RECORD)]

    clean_num = normalize_mobile_number(phone)
    if not clean_num:
        return []

    if TREAT_CHAITANYA_AS_TENANT_ONLY and is_chaitanya(clean_num):
        return [dict(CHAITANYA_TENANT_RECORD)]

    # 1. Query Supabase
    try:
        res = (
            supabase.table("clients")
            .select("*")
            .eq("mobile_number", clean_num)
            .eq("is_active", True)
            .execute()
        )
        if res.data:
            return res.data
    except Exception as e:
        logger.debug(f"Supabase client lookup error (using fallback): {e}")

    # 2. Fallback to in-memory cache
    cached = get_cached_clients()
    if not cached:
        try:
            from clients.sync_engine import run_client_master_sync
            run_client_master_sync()
            cached = get_cached_clients()
        except Exception as sync_err:
            logger.debug(f"Auto-sync on empty client cache failed: {sync_err}")

    matches = [
        c
        for c in cached
        if c.get("mobile_number") == clean_num and c.get("is_active", True)
    ]
    return matches



def get_client_by_id(client_id: str, phone: str = "") -> dict | None:
    """Retrieves a specific client record by its ID or sync_key."""
    if not client_id:
        return None

    try:
        res = supabase.table("clients").select("*").eq("id", client_id).execute()
        if res.data:
            return res.data[0]
    except Exception:
        pass

    # Fallback search by sync_key or ID in cache
    for c in get_cached_clients():
        if c.get("id") == client_id or c.get("sync_key") == client_id:
            return c

    # Fallback search by phone
    if phone:
        clients = lookup_clients_by_phone(phone)
        for c in clients:
            # pyrefly: ignore [unnecessary-type-conversion]
            if str(c.get("id")) == str(client_id) or c.get("sync_key") == client_id:
                return c

    return None


def get_active_client_context(phone: str) -> dict | None:
    """
    Gets the current active client context for the sender phone.
    If the user previously selected a unit in a multi-unit scenario, returns that.
    If only one unit exists, returns that.
    If multiple exist and none selected, returns None (triggering selection prompt).
    """
    # 0. Chaitanya Tenant Override (strictly treated as Tenant only)
    if TREAT_CHAITANYA_AS_TENANT_ONLY and is_chaitanya(phone):
        return dict(CHAITANYA_TENANT_RECORD)

    clean_num = normalize_mobile_number(phone)
    if not clean_num:
        return None

    if TREAT_CHAITANYA_AS_TENANT_ONLY and is_chaitanya(clean_num):
        return dict(CHAITANYA_TENANT_RECORD)

    # 1. Check in-memory selected context
    if clean_num in _SELECTED_CLIENT_CONTEXT:
        return _SELECTED_CLIENT_CONTEXT[clean_num]

    # 2. Check wa_task_states metadata
    try:
        state_res = (
            supabase.table("wa_task_states")
            .select("metadata")
            .eq("whatsapp_number", clean_num)
            .execute()
        )
        if state_res.data:
            meta = state_res.data[0].get("metadata") or {}
            client_ctx = meta.get("client_context")
            if client_ctx and isinstance(client_ctx, dict):
                _SELECTED_CLIENT_CONTEXT[clean_num] = client_ctx
                return client_ctx
    except Exception:
        pass

    # 3. Lookup all records for this phone
    clients = lookup_clients_by_phone(clean_num)
    if len(clients) == 1:
        _SELECTED_CLIENT_CONTEXT[clean_num] = clients[0]
        return clients[0]

    return None


def set_active_client_context(phone: str, client: dict):
    """Stores the active client context for the sender phone."""
    clean_num = normalize_mobile_number(phone)
    _SELECTED_CLIENT_CONTEXT[clean_num] = client

    if TREAT_CHAITANYA_AS_TENANT_ONLY and (is_chaitanya(phone) or is_chaitanya(clean_num)):
        return

    try:
        payload = {
            "whatsapp_number": clean_num,
            "action": "CLIENT_SESSION",
            "metadata": {"client_context": client},
        }
        supabase.table("wa_task_states").upsert(
            payload, on_conflict="whatsapp_number"
        ).execute()
    except Exception as e:
        logger.warning(f"Could not persist client context to wa_task_states: {e}")


def clear_client_context(phone: str):
    """Clears the active client context for the sender."""
    clean_num = normalize_mobile_number(phone)
    if clean_num in _SELECTED_CLIENT_CONTEXT:
        del _SELECTED_CLIENT_CONTEXT[clean_num]
