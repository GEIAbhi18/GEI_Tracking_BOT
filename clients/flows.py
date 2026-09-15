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
from clients.factech_client import create_complaint, get_complaints

logger = logging.getLogger(__name__)


def is_registered_client(sender_phone: str) -> bool:
    """Checks if a given phone number belongs to any registered client."""
    clients = lookup_clients_by_phone(sender_phone)
    return len(clients) > 0


def handle_client_hi(sender_phone: str):
    """
    Handles greeting ('HI', 'hello', etc.) from a registered client.
    Renders personalized greeting and 3 interactive buttons.
    If multiple units exist for the sender, shows a selection menu.
    """
    clients = lookup_clients_by_phone(sender_phone)
    if not clients:
        # Unknown number message
        send_unregistered_client_message(sender_phone)
        return

    # If multiple units associated with this number
    if len(clients) > 1:
        current_ctx = get_active_client_context(sender_phone)
        # If user already selected a context recently, we can use it, but also offer choice
        admin_name = clients[0].get("admin_name") or "there"
        body = (
            f"Hi {admin_name} 👋\n\n"
            f"We found multiple accounts linked to this WhatsApp number.\n\n"
            f"Please select your company/unit to continue:"
        )

        # Max 3 buttons or list message
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
    """Sends the 3 interactive options to the client."""
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

    # 3 Interactive WhatsApp Buttons
    # Note: "Check Status" is 12 chars, strictly within Meta's 20-char limit
    buttons = [
        {"id": "log_new_complaint", "title": "Log New Complaint"},
        {"id": "check_complaint_status", "title": "Check Status"},
        {"id": "complaint_history", "title": "Complaint History"},
    ]

    send_interactive_buttons(sender_phone, body, buttons)


def send_unregistered_client_message(sender_phone: str):
    """Message sent to unregistered numbers."""
    text = (
        "Hi 👋\n\n"
        "We couldn't find your details in our client records.\n\n"
        "Please contact the concerned admin/support team to register your WhatsApp number."
    )
    send_text(sender_phone, text)


def handle_client_button_reply(sender_phone: str, button_id: str, user: dict | None = None):
    """
    Handles interactive button / list actions for clients:
      - client_sel_{idx}
      - log_new_complaint
      - check_complaint_status
      - complaint_history
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

    # 2. Log New Complaint
    if button_id == "log_new_complaint":
        company = client.get("company_name", "")
        unit = client.get("unit_number", "")
        # Set state to wait for complaint description
        try:
            payload = {
                "whatsapp_number": sender_phone,
                "action": "AWAITING_CLIENT_COMPLAINT_DESC",
                "metadata": {"client_context": client},
            }
            supabase.table("wa_task_states").upsert(
                payload, on_conflict="whatsapp_number"
            ).execute()
        except Exception as err:
            logger.error(f"Error setting WA state: {err}")

        prompt_msg = (
            f"📝 *Log New Complaint*\n\n"
            f"Logging for: *{company}* (Unit {unit})\n\n"
            f"Please describe the issue or complaint in detail:\n"
            f"_(e.g., AC not cooling on 3rd floor, water leakage near washroom, power outage)_"
        )
        send_text(sender_phone, prompt_msg)
        return

    # 3. Check Complaint Status
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
            return

        msg = f"📋 *Your Active Complaints:*\n\n"
        for idx, c in enumerate(complaints[:5], start=1):
            c_id = c.get("complaintId") or c.get("complaintNumber") or c.get("id") or f"FT-{idx}"
            nature = c.get("nature") or c.get("category") or c.get("issue") or "Maintenance"
            desc = c.get("description") or c.get("details") or ""
            status = c.get("status") or "In Progress"
            updated = c.get("updatedAt") or c.get("createdAt") or datetime.now().strftime("%d %b %Y")

            msg += f"• *Complaint #{c_id}*\n"
            msg += f"  Issue: {nature}\n"
            if desc and desc != nature:
                msg += f"  Details: {desc[:60]}\n"
            msg += f"  Status: *{status}*\n"
            msg += f"  Updated: {updated}\n\n"

        send_text(sender_phone, msg.strip())
        return

    # 4. Complaint History
    elif button_id == "complaint_history":
        company = client.get("company_name", "")
        unit = client.get("unit_number", "")
        send_text(sender_phone, f"📜 Fetching complaint history for *{company}* (Unit {unit})...")

        complaints = get_complaints(client, days_back=365, active_only=False)

        if not complaints:
            send_text(sender_phone, "No previous complaints were found for your account.")
            return

        msg = f"📜 *Your Complaint History:*\n\n"
        for idx, c in enumerate(complaints[:5], start=1):
            c_id = c.get("complaintId") or c.get("complaintNumber") or c.get("id") or f"FT-{idx}"
            nature = c.get("nature") or c.get("issue") or "Maintenance"
            status = c.get("status") or "Closed"
            date = c.get("createdAt") or c.get("closedAt") or "Recent"

            msg += f"{idx}. *{c_id}*\n"
            msg += f"   {nature}\n"
            msg += f"   Status: {status}\n"
            msg += f"   Date: {date}\n\n"

        send_text(sender_phone, msg.strip())
        return


def has_active_client_flow(sender_phone: str) -> bool:
    """Checks if sender is currently awaiting complaint input."""
    try:
        res = (
            supabase.table("wa_task_states")
            .select("action")
            .eq("whatsapp_number", sender_phone)
            .execute()
        )
        if res.data and res.data[0].get("action") == "AWAITING_CLIENT_COMPLAINT_DESC":
            return True
    except Exception:
        pass
    return False


def handle_client_text(sender_phone: str, text: str) -> bool:
    """
    Processes plain text when the client is in a complaint creation flow.
    Returns True if handled, False otherwise.
    """
    try:
        res = (
            supabase.table("wa_task_states")
            .select("*")
            .eq("whatsapp_number", sender_phone)
            .execute()
        )
        if not res.data or res.data[0].get("action") != "AWAITING_CLIENT_COMPLAINT_DESC":
            return False

        meta = res.data[0].get("metadata") or {}
        client = meta.get("client_context") or get_active_client_context(sender_phone)

        if not client:
            clients = lookup_clients_by_phone(sender_phone)
            client = clients[0] if clients else {}

        # Clear the awaiting state
        try:
            supabase.table("wa_task_states").delete().eq(
                "whatsapp_number", sender_phone
            ).execute()
        except Exception:
            pass

        clean_text = text.strip()
        if clean_text.lower() in ("cancel", "exit", "menu"):
            send_text(sender_phone, "Complaint logging cancelled.")
            send_client_welcome_menu(sender_phone, client)
            return True

        # Send to Factech
        send_text(sender_phone, "⏳ Registering your complaint with Factech...")
        result = create_complaint(client, {
            "nature": "General Maintenance",
            "sub_nature": "",
            "description": clean_text,
        })

        if result.get("success"):
            cid = result.get("complaint_id", "FT-Recorded")
            company = client.get("company_name", "")
            unit = client.get("unit_number", "")
            building = client.get("building", "")

            confirmation = (
                f"✅ *Complaint Logged Successfully!*\n\n"
                f"🎫 *Complaint ID:* #{cid}\n"
                f"🏢 *Company:* {company}\n"
                f"📍 *Building:* {building} | *Unit:* {unit}\n"
                f"📝 *Description:* {clean_text}\n\n"
                f"Our facility team has received your ticket and is working on it."
            )
            send_text(sender_phone, confirmation)
        else:
            send_text(
                sender_phone,
                "Sorry, we're unable to submit your complaint right now. Please try again shortly.",
            )

        return True

    except Exception as e:
        logger.error(f"Error handling client text input: {e}", exc_info=True)
        return False
