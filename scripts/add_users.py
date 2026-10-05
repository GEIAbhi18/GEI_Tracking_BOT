"""
Script to add or update team members in the GEI Bot database.
Supports adding members to:
  1. Facilities Team (stored in `users` table and `building_users` mapping table)
  2. Elara Home Team (stored in `elara_users` table)

Usage:
  # Add default pending members (Chandan & Rizwan):
  python scripts/add_users.py

  # Add a custom member to Facilities:
  python scripts/add_users.py --name "Chandan" --phone "+918699197231" --team facilities --buildings GEBB1,GEBB2,GETT,Common

  # Add a custom member to Elara Home:
  python scripts/add_users.py --name "Rizwan" --phone "+919717856493" --team elara --dept "Construction & Design"

  # Dry run (preview without modifying database):
  python scripts/add_users.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from datetime import datetime

# Ensure project root is in sys.path
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db import supabase
from whatsapp.ux import clean_phone_number
from facilities.config import BUILDING_TABS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("add_users")


def add_facilities_user(
    name: str,
    phone: str,
    role: str = "Employee",
    department: str = "Facilities",
    buildings: list[str] | None = None,
    dry_run: bool = False,
) -> dict | None:
    """
    Add or update a user in the Facilities team (`users` and `building_users` tables).
    """
    clean_num = clean_phone_number(phone)
    if not clean_num:
        logger.error(f"Invalid phone number: {phone}")
        return None

    if buildings is None:
        buildings = BUILDING_TABS.copy()

    logger.info(f"Processing Facilities user: {name} ({clean_num}), Buildings: {buildings}")

    # Check if user already exists in `users`
    res = supabase.table("users").select("*").or_(
        f"whatsapp_number.eq.{clean_num},whatsapp_number.eq.+{clean_num}"
    ).execute()

    existing_users = res.data or []
    if not existing_users:
        # Also check by name
        res_name = supabase.table("users").select("*").ilike("name", name).execute()
        existing_users = res_name.data or []

    user_data = {
        "name": name,
        "role": role,
        "department": department,
        "whatsapp_number": clean_num,
        "permitted_buildings": buildings,
        "last_activity_at": datetime.utcnow().isoformat(),
    }

    if dry_run:
        logger.info(f"[DRY RUN] Would {'update' if existing_users else 'insert'} into `users`: {user_data}")
        return user_data

    user_record = None
    if existing_users:
        user_id = existing_users[0]["id"]
        logger.info(f"User exists in `users` (id: {user_id}). Updating record...")
        upd_res = supabase.table("users").update(user_data).eq("id", user_id).execute()
        user_record = upd_res.data[0] if upd_res.data else existing_users[0]
    else:
        logger.info(f"Creating new user in `users`...")
        ins_res = supabase.table("users").insert(user_data).execute()
        if not ins_res.data:
            logger.error("Failed to insert user into `users` table.")
            return None
        user_record = ins_res.data[0]
        user_id = user_record["id"]

    # Also sync building_users table for GEBB1, GEBB2, GETT
    try:
        buildings_res = supabase.table("buildings").select("id, name").execute()
        b_map = {b["name"]: b["id"] for b in (buildings_res.data or [])}

        for b_name in buildings:
            if b_name in b_map:
                b_id = b_map[b_name]
                # Check if mapping already exists
                bu_check = supabase.table("building_users").select("id").eq("building_id", b_id).eq("user_id", user_id).execute()
                if not bu_check.data:
                    supabase.table("building_users").insert({
                        "building_id": b_id,
                        "user_id": user_id,
                    }).execute()
                    logger.info(f"Mapped {name} to building {b_name} in `building_users`.")
    except Exception as e:
        logger.warning(f"Could not update `building_users` mapping: {e}")

    logger.info(f"Successfully processed Facilities user: {name} (ID: {user_record.get('id')})")
    return user_record


def add_elara_user(
    name: str,
    phone: str,
    role: str = "Team Member",
    department: str = "Construction & Design",
    team: str = "Elara Home",
    email: str | None = None,
    dry_run: bool = False,
) -> dict | None:
    """
    Add or update a user in the Elara Home team (`elara_users` table).
    """
    clean_num = clean_phone_number(phone)
    if not clean_num:
        logger.error(f"Invalid phone number: {phone}")
        return None

    if not email:
        clean_email_name = name.lower().replace(" ", "")
        email = f"{clean_email_name}@goodearthinfra.com"

    logger.info(f"Processing Elara user: {name} ({clean_num}), Department: {department}")

    # Check if user already exists in `elara_users`
    res = supabase.table("elara_users").select("*").or_(
        f"phone.eq.{clean_num},phone.eq.+{clean_num}"
    ).execute()

    existing_users = res.data or []
    if not existing_users:
        # Also check by name
        res_name = supabase.table("elara_users").select("*").ilike("name", name).execute()
        existing_users = res_name.data or []

    user_data = {
        "name": name,
        "phone": clean_num,
        "role": role,
        "department": department,
        "team": team,
        "email": email,
    }

    if dry_run:
        logger.info(f"[DRY RUN] Would {'update' if existing_users else 'insert'} into `elara_users`: {user_data}")
        return user_data

    user_record = None
    if existing_users:
        user_id = existing_users[0]["id"]
        logger.info(f"User exists in `elara_users` (id: {user_id}). Updating record...")
        upd_res = supabase.table("elara_users").update(user_data).eq("id", user_id).execute()
        user_record = upd_res.data[0] if upd_res.data else existing_users[0]
    else:
        logger.info("Creating new user in `elara_users`...")
        user_data["id"] = str(uuid.uuid4())
        ins_res = supabase.table("elara_users").insert(user_data).execute()
        if not ins_res.data:
            logger.error("Failed to insert user into `elara_users` table.")
            return None
        user_record = ins_res.data[0]

    logger.info(f"Successfully processed Elara user: {name} (ID: {user_record.get('id')})")
    return user_record


def main():
    parser = argparse.ArgumentParser(description="Add team members to Facilities or Elara Home database")
    parser.add_argument("--name", type=str, help="Full name of person")
    parser.add_argument("--phone", type=str, help="WhatsApp phone number (e.g. +918699197231)")
    parser.add_argument("--team", type=str, choices=["facilities", "elara"], help="Target team")
    parser.add_argument("--role", type=str, help="Role (Employee, Team Member, etc.)")
    parser.add_argument("--department", "--dept", type=str, help="Department name")
    parser.add_argument("--buildings", type=str, help="Comma-separated building codes (e.g. GEBB1,GEBB2,GETT,Common)")
    parser.add_argument("--email", type=str, help="Email address")
    parser.add_argument("--dry-run", action="store_true", help="Preview operations without modifying DB")

    args = parser.parse_args()

    if args.name and args.phone and args.team:
        # CLI single-user mode
        if args.team.lower() == "facilities":
            buildings = [b.strip() for b in args.buildings.split(",")] if args.buildings else None
            role = args.role or "Employee"
            dept = args.department or "Facilities"
            res = add_facilities_user(args.name, args.phone, role=role, department=dept, buildings=buildings, dry_run=args.dry_run)
        else:
            role = args.role or "Team Member"
            dept = args.department or "Construction & Design"
            res = add_elara_user(args.name, args.phone, role=role, department=dept, email=args.email, dry_run=args.dry_run)
        print("\nResult:", res)
    else:
        # Default batch mode for requested additions:
        print("=" * 60)
        print("Adding requested members to Database:")
        print("1. Chandan        -> Facilities (+918699197231)")
        print("2. Rizwan         -> Elara Home  (+919717856493)")
        print("3. Raja Nadeem    -> Elara Home  (+917006116371)")
        print("4. Sayangdeep Das -> Elara Home  (+916290721639)")
        print("=" * 60)

        # 1. Chandan to Facilities
        c_res = add_facilities_user(
            name="Chandan",
            phone="+918699197231",
            role="Employee",
            department="Facilities",
            buildings=["GEBB1", "GEBB2", "GETT", "Common"],
            dry_run=args.dry_run,
        )

        print("-" * 60)

        # 2. Rizwan to Elara Home
        r_res = add_elara_user(
            name="Rizwan",
            phone="+919717856493",
            role="Team Member",
            department="Construction & Design",
            team="Elara Home",
            email="rizwan@goodearthinfra.com",
            dry_run=args.dry_run,
        )

        print("-" * 60)

        # 3. Raja Nadeem to Elara Home
        rn_res = add_elara_user(
            name="Raja Nadeem",
            phone="+917006116371",
            role="Team Member",
            department="Construction & Design",
            team="Elara Home",
            email="rajanadeem@goodearthinfra.com",
            dry_run=args.dry_run,
        )

        print("-" * 60)

        # 4. Sayangdeep Das to Elara Home
        sd_res = add_elara_user(
            name="Sayangdeep Das",
            phone="+916290721639",
            role="Team Member",
            department="Construction & Design",
            team="Elara Home",
            email="sayangdeepdas@goodearthinfra.com",
            dry_run=args.dry_run,
        )

        print("=" * 60)
        print("Summary of actions:")
        print(f"Facilities (Chandan):       {'SUCCESS' if c_res else 'FAILED'}")
        print(f"Elara Home (Rizwan):        {'SUCCESS' if r_res else 'FAILED'}")
        print(f"Elara Home (Raja Nadeem):   {'SUCCESS' if rn_res else 'FAILED'}")
        print(f"Elara Home (Sayangdeep Das): {'SUCCESS' if sd_res else 'FAILED'}")
        print("=" * 60)


if __name__ == "__main__":
    main()
