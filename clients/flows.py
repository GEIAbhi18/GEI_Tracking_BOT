from __future__ import annotations
import logging
from datetime import datetime
from db import supabase
from whatsapp.ux import send_text, send_interactive_buttons, send_list_message
from clients.service import (
    lookup_clients_by_phone,
    get_active_client_context,
    set_active_client_context,
    clear_client_context,
)
from clients.factech_client import create_complaint, get_complaints, update_complaint
from clients.config import COMPLAINT_NATURES, SUB_NATURES_ALL, NATURE_TO_SUB_NATURES

logger = logging.getLogger(__name__)


def is_registered_client(sender_phone: str) -> bool:
    """Checks if a given phone number belongs to any registered client."""
    clients = lookup_clients_by_phone(sender_phone)
    return len(clients) > 0


def handle_client_hi(sender_phone: str):
    """
    Handles greeting ('HI', 'hello', etc.) from a registered client.
    Renders personalized greeting and interactive options.
    If multiple units exist for the sender, shows a selection menu.
    """
    clients = lookup_clients_by_phone(sender_phone)
    if not clients:
        send_unregistered_client_message(sender_phone)
        return

    # If multiple units associated with this number
    if len(clients) > 1:
        admin_name = clients[0].get("admin_name") or "there"
        body = (
            f"Hi {admin_name} 👋\n\n"
            f"We found multiple accounts linked to this WhatsApp number.\n\n"
            f"Please select your company/unit to continue:"
        )

        if len(clients) <= 3:
            buttons = []
            for idx, c in enumerate(clients):
                comp = c.get("company_name", "Company")[:12]
                unit = c.get("unit_number", "")
                btn_title = f"{comp} ({unit})"[:20]
                buttons.append({"id": f"client_sel_{idx}", "title": btn_title})
            send_interactive_buttons(sender_phone, body, buttons)
        else:
            rows = []
            for idx, c in enumerate(clients[:10]):
                comp = c.get("company_name", "Company")[:24]
                unit = c.get("unit_number", "")
                bldg = c.get("building", "")
                rows.append({
                    "id": f"client_sel_{idx}",
                    "title": comp,
                    "description": f"Building {bldg} | Unit {unit}",
                })
            sections = [{"title": "Select Account", "rows": rows}]
            send_list_message(sender_phone, body, "Select Company", sections)
        return

    # Single client account
    client = clients[0]
    set_active_client_context(sender_phone, client)
    send_client_welcome_menu(sender_phone, client)


def send_client_welcome_menu(sender_phone: str, client: dict):
    """Sends the 3 primary interactive options to the client with plain text fallback."""
    admin_name = client.get("admin_name") or "there"
    company = client.get("company_name", "N/A")
    building = client.get("building", "N/A")
    unit = client.get("unit_number", "N/A")

    body = (
        f"Hi {admin_name} 👋\n\n"
        f"Welcome to GEI Support.\n\n"
        f"🏢 *Company:* {company}\n"
        f"📍 *Building:* {building}\n"
        f"🚪 *Unit:* {unit}\n\n"
        f"How can I help you today?"
    )

    # 3 Interactive WhatsApp Buttons (Meta strictly enforces max 3 buttons, <= 20 chars each)
    buttons = [
        {"id": "log_new_complaint", "title": "Log New Complaint"},
        {"id": "check_complaint_status", "title": "Check Status"},
        {"id": "complaint_history", "title": "Complaint History"},
    ]

    ok = send_interactive_buttons(sender_phone, body, buttons)
    if not ok:
        text_menu = (
            f"{body}\n\n"
            f"1️⃣ *Log New Complaint*\n"
            f"2️⃣ *Check Status*\n"
            f"3️⃣ *Complaint History*\n"
            f"4️⃣ *Update Complaint*\n\n"
            f"_Reply with 1, 2, 3, or 4, or type your complaint description directly._"
        )
        send_text(sender_phone, text_menu)


def send_post_complaint_options(sender_phone: str, client: dict, complaint_id: str | None = None):
    """
    Shows appropriate next options after complaint actions (create, update)
    without triggering the main greeting / welcome menu again.
    """
    body = "What would you like to do next?"
    buttons = [
        {"id": "check_complaint_status", "title": "Check Status"},
        {"id": "update_complaint", "title": "Update Complaint"},
        {"id": "log_new_complaint", "title": "Log New Complaint"},
    ]

    ok = send_interactive_buttons(sender_phone, body, buttons)
    if not ok:
        fallback = (
            f"{body}\n\n"
            f"1️⃣ *Check Status* (Reply 'status' or '2')\n"
            f"2️⃣ *Update Complaint* (Reply 'update' or '4')\n"
            f"3️⃣ *Log New Complaint* (Reply 'log' or '1')\n"
            f"4️⃣ *Main Menu* (Reply 'menu')\n"
        )
        send_text(sender_phone, fallback)


def send_unregistered_client_message(sender_phone: str):
    """Message sent to unregistered numbers."""
    text = (
        "Hi 👋\n\n"
        "We couldn't find your details in our client records.\n\n"
        "Please contact the concerned admin/support team to register your WhatsApp number."
    )
    send_text(sender_phone, text)


def handle_update_complaint_initiation(sender_phone: str, client: dict, target_cid: str | None = None):
    """
    Initiates the update complaint flow:
    - Fetches client's active complaints.
    - If none, informs user.
    - If single complaint or target_cid provided, prompts for update note.
    - If multiple complaints, prompts user to select which complaint to update.
    """
    company = client.get("company_name", "")
    unit = client.get("unit_number", "")
    complaints = get_complaints(client, days_back=60, active_only=True)

    if not complaints:
        msg = f"ℹ️ You currently have no active complaints to update for *{company}* (Unit {unit}).\n\nWould you like to log a new complaint?"
        buttons = [
            {"id": "log_new_complaint", "title": "Log New Complaint"},
            {"id": "complaint_history", "title": "Complaint History"},
            {"id": "client_main_menu", "title": "Main Menu"},
        ]
        if not send_interactive_buttons(sender_phone, msg, buttons):
            send_text(sender_phone, f"{msg}\n\n1️⃣ Log New Complaint\n2️⃣ Complaint History\n3️⃣ Main Menu")
        return

    selected = None
    if target_cid:
        # pyrefly: ignore [unnecessary-type-conversion]
        clean_target = str(target_cid).lstrip("#").strip().lower()
        for c in complaints:
            cid = str(c.get("com_no") or c.get("complaintId") or c.get("id") or "").lstrip("#").strip().lower()
            if clean_target == cid:
                selected = c
                break

    if not selected:
        if len(complaints) == 1:
            selected = complaints[0]
        else:
            # Multiple active complaints — ask client to choose
            body = f"📋 *Select Complaint to Update* ({company} - Unit {unit})\n\nPlease choose which active complaint you want to update:"
            buttons = []
            for c in complaints[:3]:
                cid = str(c.get("com_no") or c.get("complaintId") or c.get("id") or "")
                cat = c.get("complaint_category") or {}
                nature = (cat.get("name") if isinstance(cat, dict) else None) or c.get("sub_category") or c.get("nature") or "Issue"
                title = f"#{cid} ({nature})"[:20]
                buttons.append({"id": f"upd_cid_{cid}", "title": title})

            options_text = ""
            for idx, c in enumerate(complaints[:5], start=1):
                cid = str(c.get("com_no") or c.get("complaintId") or c.get("id") or "")
                cat = c.get("complaint_category") or {}
                nature = (cat.get("name") if isinstance(cat, dict) else None) or c.get("sub_category") or c.get("nature") or "Maintenance"
                options_text += f"{idx}️⃣ *#{cid}* — {nature}\n"

            payload = {
                "whatsapp_number": sender_phone,
                "action": "AWAITING_CLIENT_COMPLAINT_SELECT",
                "metadata": {
                    "client_context": client,
                    "active_complaints": complaints[:5],
                },
            }
            try:
                supabase.table("wa_task_states").upsert(payload, on_conflict="whatsapp_number").execute()
            except Exception as e:
                logger.error(f"Error setting WA state: {e}")

            buttons_sent = False
            if len(complaints) <= 3:
                buttons_sent = send_interactive_buttons(sender_phone, body, buttons)

            if not buttons_sent:
                send_text(
                    sender_phone,
                    f"{body}\n\n{options_text}\n_Reply with the number (e.g. 1) or Complaint ID._",
                )
            return

    # Single or selected complaint
    cid = str(selected.get("com_no") or selected.get("complaintId") or selected.get("id") or "")
    cat = selected.get("complaint_category") or {}
    nature = (cat.get("name") if isinstance(cat, dict) else None) or selected.get("sub_category") or selected.get("nature") or "Maintenance"
    desc = selected.get("description") or selected.get("details") or ""

    payload = {
        "whatsapp_number": sender_phone,
        "action": "AWAITING_CLIENT_COMPLAINT_UPDATE",
        "metadata": {
            "client_context": client,
            "target_complaint_id": cid,
            "complaint": selected,
        },
    }
    try:
        supabase.table("wa_task_states").upsert(payload, on_conflict="whatsapp_number").execute()
    except Exception as e:
        logger.error(f"Error setting WA state: {e}")

    prompt_msg = (
        f"📝 *Update Complaint #{cid}*\n\n"
        f"🏢 *{company}* (Unit {unit})\n"
        f"Issue: *{nature}*\n"
        f"Current Details: _{desc[:120]}_\n\n"
        f"Please enter the updated details or additional note for this complaint:\n"
        f"_(Reply with 'cancel' to exit)_"
    )
    send_text(sender_phone, prompt_msg)





def prompt_complaint_nature_selection(sender_phone: str, client: dict):
    """
    Step 1: Prompts the client to select Complaint Nature via a WhatsApp list message
    (with plain text numbered fallback).
    """
    company = client.get("company_name", "")
    unit = client.get("unit_number", "")
    bldg = client.get("building", "")

    # Set state
    payload = {
        "whatsapp_number": sender_phone,
        "action": "AWAITING_CLIENT_COMPLAINT_NATURE",
        "metadata": {"client_context": client},
    }
    try:
        supabase.table("wa_task_states").upsert(
            payload, on_conflict="whatsapp_number"
        ).execute()
    except Exception as err:
        logger.error(f"Error setting WA state: {err}")

    body = (
        f"📝 *Log New Complaint*\n\n"
        f"🏢 *{company}* (Unit {unit})\n"
        f"📍 *Building:* {bldg}\n\n"
        f"Please select the *Complaint Nature* from the list below:"
    )

    rows = []
    for idx, nat in enumerate(COMPLAINT_NATURES):
        rows.append({
            "id": f"c_nat_{idx}",
            "title": nat[:24],
        })
    sections = [{"title": "Complaint Nature", "rows": rows}]

    sent = send_list_message(sender_phone, body, "Select Nature", sections)
    if not sent:
        options_text = "\n".join(
            f"{i+1}️⃣ *{nat}*" for i, nat in enumerate(COMPLAINT_NATURES)
        )
        fallback = (
            f"{body}\n\n"
            f"{options_text}\n\n"
            f"_Reply with the number (1-{len(COMPLAINT_NATURES)}) or option name._\n"
            f"_(Reply 'cancel' to exit)_"
        )
        send_text(sender_phone, fallback)


def prompt_complaint_sub_nature_selection(sender_phone: str, client: dict, nature: str):
    """
    Step 2: Prompts the client to select Sub Nature based on selected Complaint Nature.
    """
    company = client.get("company_name", "")
    unit = client.get("unit_number", "")

    # Set state
    payload = {
        "whatsapp_number": sender_phone,
        "action": "AWAITING_CLIENT_COMPLAINT_SUB_NATURE",
        "metadata": {
            "client_context": client,
            "nature": nature,
        },
    }
    try:
        supabase.table("wa_task_states").upsert(
            payload, on_conflict="whatsapp_number"
        ).execute()
    except Exception as err:
        logger.error(f"Error setting WA state: {err}")

    body = (
        f"📝 *Log New Complaint*\n\n"
        f"🏢 *{company}* (Unit {unit})\n"
        f"🏷️ Nature: *{nature}*\n\n"
        f"Please select the *Sub Nature* from the list below:"
    )

    options = NATURE_TO_SUB_NATURES.get(nature) or [
        "Other",
        "Others",
    ]

    rows = []
    for opt in options:
        opt_idx = SUB_NATURES_ALL.index(opt) if opt in SUB_NATURES_ALL else 0
        rows.append({
            "id": f"c_sub_{opt_idx}",
            "title": opt[:24],
        })

    sections = [{"title": f"{nature} Issues"[:24], "rows": rows[:10]}]

    sent = send_list_message(sender_phone, body, "Select Issue", sections)
    if not sent:
        options_text = "\n".join(
            f"{i+1}️⃣ *{opt}*" for i, opt in enumerate(options)
        )
        fallback = (
            f"{body}\n\n"
            f"{options_text}\n\n"
            f"_Reply with the number or type your specific issue directly._\n"
            f"_(Reply 'cancel' to exit)_"
        )
        send_text(sender_phone, fallback)


def prompt_complaint_description(sender_phone: str, client: dict, nature: str, sub_nature: str):
    """
    Step 3: Prompts the client for complaint details / description after Nature and Sub Nature are chosen.
    """
    company = client.get("company_name", "")
    unit = client.get("unit_number", "")

    payload = {
        "whatsapp_number": sender_phone,
        "action": "AWAITING_CLIENT_COMPLAINT_DESC",
        "metadata": {
            "client_context": client,
            "nature": nature,
            "sub_nature": sub_nature,
        },
    }
    try:
        supabase.table("wa_task_states").upsert(
            payload, on_conflict="whatsapp_number"
        ).execute()
    except Exception as err:
        logger.error(f"Error setting WA state: {err}")

    prompt_msg = (
        f"📝 *Log New Complaint*\n\n"
        f"🏢 *{company}* (Unit {unit})\n"
        f"🏷️ Nature: *{nature}*\n"
        f"🔖 Sub Nature: *{sub_nature}*\n\n"
        f"Please describe the issue or complaint in detail:\n"
        f"_(Reply with details, or reply 'skip' to submit with selected issue)_\n"
        f"_(Reply 'cancel' to exit)_"
    )
    send_text(sender_phone, prompt_msg)


def handle_client_button_reply(sender_phone: str, button_id: str, user: dict | None = None):
    """
    Handles interactive button / list actions for clients:
      - client_sel_{idx}
      - log_new_complaint
      - c_nat_{idx}
      - c_sub_{idx}
      - check_complaint_status
      - complaint_history
      - update_complaint
      - upd_cid_{cid}
      - client_main_menu
    """
    logger.info(f"Client button handler: {button_id} from {sender_phone}")

    # 1. Multi-unit selection
    if button_id.startswith("client_sel_"):
        try:
            idx = int(button_id.split("client_sel_")[1])
            clients = lookup_clients_by_phone(sender_phone)
            if 0 <= idx < len(clients):
                selected = clients[idx]
                set_active_client_context(sender_phone, selected)
                send_client_welcome_menu(sender_phone, selected)
                return
        except Exception as e:
            logger.error(f"Error selecting client account: {e}")

    client = get_active_client_context(sender_phone)
    if not client:
        clients = lookup_clients_by_phone(sender_phone)
        if clients:
            client = clients[0]
            set_active_client_context(sender_phone, client)
        else:
            send_unregistered_client_message(sender_phone)
            return

    # 2. Main menu return
    if button_id == "client_main_menu":
        send_client_welcome_menu(sender_phone, client)
        return

    # 3. Log New Complaint -> Step 1: Prompt Complaint Nature
    if button_id == "log_new_complaint":
        prompt_complaint_nature_selection(sender_phone, client)
        return

    # Complaint Nature List Reply
    elif button_id.startswith("c_nat_"):
        try:
            idx = int(button_id.replace("c_nat_", ""))
            if 0 <= idx < len(COMPLAINT_NATURES):
                selected_nature = COMPLAINT_NATURES[idx]
                prompt_complaint_sub_nature_selection(sender_phone, client, selected_nature)
                return
        except Exception as e:
            logger.error(f"Error handling nature button reply: {e}")

    # Complaint Sub Nature List Reply
    elif button_id.startswith("c_sub_"):
        try:
            idx = int(button_id.replace("c_sub_", ""))
            if 0 <= idx < len(SUB_NATURES_ALL):
                selected_sub_nature = SUB_NATURES_ALL[idx]
                nature = "General"
                try:
                    res = (
                        supabase.table("wa_task_states")
                        .select("metadata")
                        .eq("whatsapp_number", sender_phone)
                        .execute()
                    )
                    if res.data:
                        meta = res.data[0].get("metadata") or {}
                        nature = meta.get("nature") or "General"
                except Exception:
                    pass
                prompt_complaint_description(sender_phone, client, nature, selected_sub_nature)
                return
        except Exception as e:
            logger.error(f"Error handling sub-nature button reply: {e}")

    # 4. Check Complaint Status
    elif button_id == "check_complaint_status":
        company = client.get("company_name", "")
        unit = client.get("unit_number", "")
        send_text(sender_phone, f"🔍 Checking active complaints for *{company}* (Unit {unit})...")

        complaints = get_complaints(client, days_back=60, active_only=True)

        if not complaints:
            send_text(
                sender_phone,
                f"✅ You currently have no active complaints for *{company}* (Unit {unit}). Everything is in good order!",
            )
            buttons = [
                {"id": "log_new_complaint", "title": "Log New Complaint"},
                {"id": "complaint_history", "title": "Complaint History"},
                {"id": "client_main_menu", "title": "Main Menu"},
            ]
            send_interactive_buttons(sender_phone, "Options:", buttons)
            return

        msg = f"📋 *Your Active Complaints:*\n\n"
        for idx, c in enumerate(complaints[:5], start=1):
            c_id = c.get("com_no") or c.get("complaintId") or c.get("complaintNumber") or c.get("id") or f"FT-{idx}"
            cat = c.get("complaint_category") or {}
            nature = (cat.get("name") if isinstance(cat, dict) else None) or c.get("sub_category") or c.get("nature") or "Maintenance"
            desc = c.get("description") or c.get("details") or ""
            status = c.get("status") or "In Progress"
            updated = c.get("updated_at") or c.get("created_at") or c.get("updatedAt") or datetime.now().strftime("%d %b %Y")

            msg += f"• *Complaint #{c_id}*\n"
            msg += f"  Issue: {nature}\n"
            if desc and desc != nature:
                msg += f"  Details: {desc[:60]}\n"
            msg += f"  Status: *{status}*\n"
            msg += f"  Updated: {updated}\n\n"

        send_text(sender_phone, msg.strip())

        # Next actions buttons
        buttons = [
            {"id": "update_complaint", "title": "Update Complaint"},
            {"id": "log_new_complaint", "title": "Log New Complaint"},
            {"id": "complaint_history", "title": "Complaint History"},
        ]
        send_interactive_buttons(sender_phone, "What would you like to do next?", buttons)
        return

    # 5. Complaint History
    elif button_id == "complaint_history":
        company = client.get("company_name", "")
        unit = client.get("unit_number", "")
        send_text(sender_phone, f"📜 Fetching complaint history for *{company}* (Unit {unit})...")

        complaints = get_complaints(client, days_back=365, active_only=False)

        if not complaints:
            send_text(sender_phone, "No previous complaints were found for your account.")
            buttons = [
                {"id": "log_new_complaint", "title": "Log New Complaint"},
                {"id": "check_complaint_status", "title": "Check Status"},
                {"id": "client_main_menu", "title": "Main Menu"},
            ]
            send_interactive_buttons(sender_phone, "Options:", buttons)
            return

        msg = f"📜 *Your Complaint History:*\n\n"
        for idx, c in enumerate(complaints[:5], start=1):
            c_id = c.get("com_no") or c.get("complaintId") or c.get("complaintNumber") or c.get("id") or f"FT-{idx}"
            cat = c.get("complaint_category") or {}
            nature = (cat.get("name") if isinstance(cat, dict) else None) or c.get("sub_category") or c.get("nature") or "Maintenance"
            status = c.get("status") or "Closed"
            date = c.get("created_at") or c.get("closed_at") or c.get("createdAt") or "Recent"

            msg += f"{idx}. *#{c_id}*\n"
            msg += f"   Issue: {nature}\n"
            msg += f"   Status: {status}\n"
            msg += f"   Date: {date}\n\n"

        send_text(sender_phone, msg.strip())

        buttons = [
            {"id": "check_complaint_status", "title": "Check Status"},
            {"id": "log_new_complaint", "title": "Log New Complaint"},
            {"id": "client_main_menu", "title": "Main Menu"},
        ]
        send_interactive_buttons(sender_phone, "Options:", buttons)
        return

    # 6. Update Complaint
    elif button_id == "update_complaint":
        handle_update_complaint_initiation(sender_phone, client)
        return

    elif button_id.startswith("upd_cid_"):
        target_cid = button_id.replace("upd_cid_", "").strip()
        handle_update_complaint_initiation(sender_phone, client, target_cid=target_cid)
        return


def has_active_client_flow(sender_phone: str) -> bool:
    """Checks if sender is currently in an active complaint creation, selection, or update flow."""
    try:
        res = (
            supabase.table("wa_task_states")
            .select("action")
            .eq("whatsapp_number", sender_phone)
            .execute()
        )
        if res.data:
            action = res.data[0].get("action")
            return action in (
                "AWAITING_CLIENT_COMPLAINT_NATURE",
                "AWAITING_CLIENT_COMPLAINT_SUB_NATURE",
                "AWAITING_CLIENT_COMPLAINT_DESC",
                "AWAITING_CLIENT_COMPLAINT_UPDATE",
                "AWAITING_CLIENT_COMPLAINT_SELECT",
            )
    except Exception:
        pass
    return False


def handle_client_text(sender_phone: str, text: str) -> bool:
    """
    Processes plain text when the client is in a complaint creation or update flow.
    Returns True if handled, False otherwise.
    """
    try:
        res = (
            supabase.table("wa_task_states")
            .select("*")
            .eq("whatsapp_number", sender_phone)
            .execute()
        )
        if not res.data:
            return False

        action = res.data[0].get("action")
        if action not in (
            "AWAITING_CLIENT_COMPLAINT_NATURE",
            "AWAITING_CLIENT_COMPLAINT_SUB_NATURE",
            "AWAITING_CLIENT_COMPLAINT_DESC",
            "AWAITING_CLIENT_COMPLAINT_UPDATE",
            "AWAITING_CLIENT_COMPLAINT_SELECT",
        ):
            return False

        meta = res.data[0].get("metadata") or {}
        client = meta.get("client_context") or get_active_client_context(sender_phone)

        if not client:
            clients = lookup_clients_by_phone(sender_phone)
            client = clients[0] if clients else {}

        clean_text = text.strip()

        # Cancellation check
        if clean_text.lower() in ("cancel", "exit", "menu"):
            try:
                supabase.table("wa_task_states").delete().eq(
                    "whatsapp_number", sender_phone
                ).execute()
            except Exception:
                pass
            send_text(sender_phone, "Action cancelled.")
            send_post_complaint_options(sender_phone, client)
            return True

        # Flow 0a: Complaint Nature Selection
        if action == "AWAITING_CLIENT_COMPLAINT_NATURE":
            selected_nature = None
            if clean_text.isdigit():
                idx = int(clean_text) - 1
                if 0 <= idx < len(COMPLAINT_NATURES):
                    selected_nature = COMPLAINT_NATURES[idx]

            if not selected_nature:
                for nat in COMPLAINT_NATURES:
                    if clean_text.lower() == nat.lower() or nat.lower() in clean_text.lower():
                        selected_nature = nat
                        break

            if not selected_nature:
                options_text = "\n".join(f"{i+1}️⃣ {nat}" for i, nat in enumerate(COMPLAINT_NATURES))
                send_text(
                    sender_phone,
                    f"⚠️ Please choose a valid Complaint Nature:\n\n{options_text}\n\n_Reply with the number (1-{len(COMPLAINT_NATURES)}) or option name (or 'cancel')._",
                )
                return True

            prompt_complaint_sub_nature_selection(sender_phone, client, selected_nature)
            return True

        # Flow 0b: Complaint Sub Nature Selection
        if action == "AWAITING_CLIENT_COMPLAINT_SUB_NATURE":
            nature = meta.get("nature") or "General"
            options = NATURE_TO_SUB_NATURES.get(nature) or SUB_NATURES_ALL[:10]
            selected_sub_nature = None

            if clean_text.isdigit():
                idx = int(clean_text) - 1
                if 0 <= idx < len(options):
                    selected_sub_nature = options[idx]
                elif 0 <= idx < len(SUB_NATURES_ALL):
                    selected_sub_nature = SUB_NATURES_ALL[idx]

            if not selected_sub_nature:
                for opt in options:
                    if clean_text.lower() == opt.lower():
                        selected_sub_nature = opt
                        break

            if not selected_sub_nature:
                for opt in SUB_NATURES_ALL:
                    if clean_text.lower() == opt.lower():
                        selected_sub_nature = opt
                        break

            if not selected_sub_nature:
                for opt in SUB_NATURES_ALL:
                    if opt.lower() in clean_text.lower() or clean_text.lower() in opt.lower():
                        selected_sub_nature = opt
                        break

            if not selected_sub_nature:
                if "other" in clean_text.lower():
                    selected_sub_nature = "Others" if "others" in clean_text.lower() else "Other"
                else:
                    selected_sub_nature = "Others"

            prompt_complaint_description(sender_phone, client, nature, selected_sub_nature)
            return True

        # Flow 1: New Complaint Creation (Description entered)
        if action == "AWAITING_CLIENT_COMPLAINT_DESC":
            nature = meta.get("nature") or "General Maintenance"
            sub_nature = meta.get("sub_nature") or "Other"

            try:
                supabase.table("wa_task_states").delete().eq(
                    "whatsapp_number", sender_phone
                ).execute()
            except Exception:
                pass

            desc = clean_text
            if desc.lower() in ("skip", "same", "none", "-"):
                desc = f"{nature} - {sub_nature}"

            send_text(sender_phone, "⏳ Registering your complaint with Factech...")
            result = create_complaint(client, {
                "nature": nature,
                "sub_nature": sub_nature,
                "description": desc,
            })

            if result.get("success"):
                cid = result.get("complaint_id", "FT-Recorded")
                company = client.get("company_name", "")
                from clients.config import is_chaitanya, is_developer_phone
                phone = str(client.get("mobile_number") or sender_phone).strip()
                admin_name = str(client.get("admin_name") or "").strip()
                if is_chaitanya(phone) or is_chaitanya(admin_name) or is_developer_phone(phone) or is_developer_phone(admin_name):
                    unit = "GEEBTWOTest"
                    building = "Business Bay-II"
                else:
                    unit = client.get("unit_number", "")
                    building = client.get("building", "")

                confirmation = (
                    f"✅ *Complaint Logged Successfully!*\n\n"
                    f"🎫 *Complaint ID:* #{cid}\n"
                    f"🏢 *Company:* {company}\n"
                    f"📍 *Building:* {building} | *Unit:* {unit}\n"
                    f"🏷️ *Nature:* {nature}\n"
                    f"🔖 *Sub Nature:* {sub_nature}\n"
                    f"📝 *Description:* {desc}\n\n"
                    f"Our facility team has received your ticket and is working on it."
                )
                send_text(sender_phone, confirmation)
                send_post_complaint_options(sender_phone, client, complaint_id=cid)
            else:
                api_msg = result.get("message", "Unknown error")
                logger.error(f"Factech complaint creation FAILED for {sender_phone}: {api_msg}")
                logger.error(f"Factech raw response: {result.get('raw', {})}")
                send_text(
                    sender_phone,
                    (
                        "❌ *Unable to register your complaint at this time.*\n\n"
                        "Our system could not confirm the complaint with our facility management platform.\n\n"
                        f"📝 Your complaint details have been noted:\n_{clean_text[:200]}_\n\n"
                        "Please try again in a few minutes, or contact the facility team directly.\n"
                        f"⚠️ _Technical details: {api_msg[:150]}_"
                    ),
                )
                send_post_complaint_options(sender_phone, client)
            return True

        # Flow 2: Multiple Complaints Selection for Update
        if action == "AWAITING_CLIENT_COMPLAINT_SELECT":
            active_list = meta.get("active_complaints") or []
            selected_cid = None

            if clean_text.isdigit():
                sel_idx = int(clean_text) - 1
                if 0 <= sel_idx < len(active_list):
                    selected_cid = active_list[sel_idx].get("com_no") or active_list[sel_idx].get("complaintId") or active_list[sel_idx].get("id")

            if not selected_cid:
                target_str = clean_text.lstrip("#").lower()
                for c in active_list:
                    cid_str = str(c.get("com_no") or c.get("complaintId") or c.get("id") or "").lstrip("#").lower()
                    if target_str == cid_str or target_str in cid_str:
                        selected_cid = c.get("com_no") or c.get("complaintId") or c.get("id")
                        break

            if selected_cid:
                try:
                    supabase.table("wa_task_states").delete().eq(
                        "whatsapp_number", sender_phone
                    ).execute()
                except Exception:
                    pass
                handle_update_complaint_initiation(sender_phone, client, target_cid=str(selected_cid))
                return True
            else:
                send_text(
                    sender_phone,
                    "⚠️ Could not find that complaint.\nPlease reply with the number (e.g. 1) or Complaint ID (or reply 'cancel'):",
                )
                return True

        # Flow 3: Update Complaint Details Input
        if action == "AWAITING_CLIENT_COMPLAINT_UPDATE":
            target_cid = meta.get("target_complaint_id", "")
            try:
                supabase.table("wa_task_states").delete().eq(
                    "whatsapp_number", sender_phone
                ).execute()
            except Exception:
                pass

            send_text(sender_phone, f"⏳ Updating complaint #{target_cid}...")
            update_complaint(client, target_cid, {"description": clean_text})

            company = client.get("company_name", "")
            unit = client.get("unit_number", "")
            building = client.get("building", "")

            confirmation = (
                f"✅ *Complaint Updated Successfully!*\n\n"
                f"🎫 *Complaint ID:* #{target_cid}\n"
                f"🏢 *Company:* {company}\n"
                f"📍 *Building:* {building} | *Unit:* {unit}\n"
                f"📝 *Updated Details:* {clean_text}\n\n"
                f"Our facility team has received your update."
            )
            send_text(sender_phone, confirmation)
            send_post_complaint_options(sender_phone, client, complaint_id=target_cid)
            return True

    except Exception as e:
        logger.error(f"Error handling client text input: {e}", exc_info=True)
        return False
