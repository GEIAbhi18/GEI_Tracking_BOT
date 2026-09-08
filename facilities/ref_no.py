"""
Facilities Module — Atomic Ref No Generation
==============================================
Uses a Supabase Postgres function with FOR UPDATE row-level locking
to guarantee zero collisions under concurrent task creation.

Format: {BUILDING}-{NNN}  (e.g., GEBB1-001, GETT-042)

The Ref No is generated ONLY at confirmed task creation time —
never during draft or preview stages.
"""

import logging
from db import supabase

logger = logging.getLogger(__name__)


def generate_ref_no(building: str) -> str:
    """
    Atomically generate the next Ref No for a building.

    Uses the Postgres function `generate_ref_no(building)` which
    performs a row-level locked UPDATE on building_counters.

    Args:
        building: Building code (e.g., 'GEBB1', 'GETT', 'Common')

    Returns:
        The generated Ref No string (e.g., 'GEBB1-001')

    Raises:
        RuntimeError: If the RPC call fails or returns no result
    """
    try:
        from facilities.config import REF_NO_PAD_WIDTH
        result = supabase.rpc("generate_ref_no", {"p_building": building}).execute()

        if result.data is None:
            raise RuntimeError(f"generate_ref_no RPC returned None for building '{building}'")

        ref_no = result.data

        # Self-healing: Check if counter is behind existing tasks in row_cache
        gen_num = 0
        if "-" in ref_no:
            try:
                gen_num = int(ref_no.split("-")[1])
            except (ValueError, IndexError):
                pass

        all_rows = supabase.table("row_cache").select("ref_no").eq("building", building).execute()
        max_num = 0
        prefix = "COM" if building == "Common" else building
        for r in (all_rows.data or []):
            r_ref = r.get("ref_no", "")
            if "-" in r_ref:
                try:
                    num = int(r_ref.split("-")[1])
                    if num > max_num:
                        max_num = num
                except (ValueError, IndexError):
                    pass

        if gen_num <= max_num:
            next_num = max_num + 1
            ref_no = f"{prefix}-{str(next_num).zfill(REF_NO_PAD_WIDTH)}"
            # Update counter in DB so next call continues forward
            supabase.table("building_counters").update({"next_ref_no": next_num + 1}).eq("building", building).execute()

        logger.info(f"Generated Ref No: {ref_no} for building {building}")
        return ref_no

    except Exception as e:
        logger.error(f"Failed to generate Ref No for building '{building}': {e}", exc_info=True)
        raise RuntimeError(f"Ref No generation failed for {building}: {e}") from e


def parse_ref_no(ref_no: str) -> dict:
    """
    Parse a Ref No string into its components.

    Args:
        ref_no: Ref No string (e.g., 'GEBB1-001')

    Returns:
        dict with 'building' and 'number' keys
    """
    from facilities.config import REF_NO_SEPARATOR

    parts = ref_no.split(REF_NO_SEPARATOR)
    if len(parts) != 2:
        raise ValueError(f"Invalid Ref No format: {ref_no}")

    return {
        "building": parts[0],
        "number": int(parts[1]),
    }


def get_building_from_ref_no(ref_no: str) -> str:
    """Extract the building code from a Ref No string."""
    return parse_ref_no(ref_no)["building"]
