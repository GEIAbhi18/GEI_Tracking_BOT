import logging
from auth.context import get_current_user
from tasks.service import orchestrate_status_update
from whatsapp.ux import send_text, send_interactive_buttons, send_list_message
from db import supabase

logger = logging.getLogger(__name__)

def set_wa_state(phone: str, state: str, metadata: dict = None):
    """Sets a temporary conversation state for multi-step flows."""
    try:
        payload = {"phone": phone, "action": state}
        if metadata:
            payload["task_id"] = metadata.get("task_id")
            
        supabase.table("wa_task_states").upsert(payload, on_conflict="phone").execute()
    except Exception as e:
        logger.error(f"Error setting WA state: {e}")

def handle_interactive_reply(sender_phone: str, button_id: str):
    """Routes an interactive button/list ID to the proper service logic."""
    user = get_current_user()
    if not user:
        return
        
    logger.info(f"UX Handler processing button ID: {button_id}")
    
    # ── Main Menu Routing ────────────────────────────────────────────────────
    if button_id.startswith("menu_"):
        if button_id == "menu_team_tasks":
            import asyncio
            from core.logic import process_user_message
            async def _send_reply(text=None, document=None, target_user_id=None):
                if text: send_text(sender_phone, text)
            asyncio.run(process_user_message(sender_phone, "show team tasks", _send_reply))
            
        elif button_id == "menu_my_tasks":
            import asyncio
            from core.logic import process_user_message
            async def _send_reply(text=None, document=None, target_user_id=None):
                if text: send_text(sender_phone, text)
            asyncio.run(process_user_message(sender_phone, "show my personal tasks", _send_reply))
            
        elif button_id == "menu_create_task":
            buttons = [
                {"id": "create_task_personal", "title": "Personal Task"},
                {"id": "create_task_team", "title": "Team Task"}
            ]
            send_interactive_buttons(sender_phone, "What type of task do you want to create?", buttons)
            
        elif button_id == "menu_admin":
            if user.get("role") != "Developer" and user.get("original_role") != "Developer":
                send_text(sender_phone, "You do not have permission to access System Admin.")
                return
            sections = [{"title": "Switch User", "rows": [
                {"id": "admin_switch_asif", "title": "Asif (Project Team)"},
                {"id": "admin_switch_abhijeet", "title": "Abhijeet (Tech)"},
                {"id": "admin_switch_kanav", "title": "Kanav (Director)"},
                {"id": "admin_switch_guest", "title": "Guest (External)"}
            ]}]
            send_list_message(sender_phone, "Admin Panel: Select a user to impersonate for testing.", "Select User", sections)
            
        elif button_id == "menu_notifications":
            send_text(sender_phone, "🔔 *Notifications*\n\nYou currently have no new notifications. Activity on your assigned tasks will appear here.")
            
        elif button_id == "menu_analytics":
            send_text(sender_phone, "📈 *Analytics*\n\nYour dashboard is being generated. This feature is currently in Beta and will show your weekly task velocity soon!")
            
        else:
            send_text(sender_phone, f"You selected: {button_id} (Coming soon)")
        return
        
    # ── Admin Switch Routing ─────────────────────────────────────────────────
    if button_id.startswith("admin_switch_"):
        if user.get("role") != "Developer" and user.get("original_role") != "Developer":
            send_text(sender_phone, "Unauthorized.")
            return
            
        target = button_id.replace("admin_switch_", "")
        target_id = None
        
        if target == "guest":
            target_id = "00000000-0000-0000-0000-000000000000"
        else:
            # Find the target user by name
            r = supabase.table("users").select("id").ilike("name", f"%{target}%").execute()
            if r.data:
                target_id = r.data[0]["id"]
                
        if target_id:
            # Note: We must update the REAL user's record, which means if they are already impersonating,
            # user['id'] is the impersonated ID. We need the real ID.
            real_id = user.get("real_user_id", user["id"])
            
            # If Kanav is switching back to Kanav, clear it
            if target == "kanav":
                supabase.table("users").update({"impersonating_user_id": None}).eq("id", real_id).execute()
                send_text(sender_phone, f"✅ Switched back to your normal profile (Kanav).")
            else:
                supabase.table("users").update({"impersonating_user_id": target_id}).eq("id", real_id).execute()
                send_text(sender_phone, f"✅ You are now testing as: {target.capitalize()}. \nSend 'menu' to see their view.")
        else:
            send_text(sender_phone, f"Could not find user '{target}' in the database.")
        return
        
    # ── Create Task Routing ──────────────────────────────────────────────────
    if button_id.startswith("create_task_"):
        if button_id == "create_task_personal":
            send_text(sender_phone, "What is the title of your new Personal Task?")
            set_wa_state(sender_phone, "WAITING_FOR_PERSONAL_TASK_TITLE")
        elif button_id == "create_task_team":
            send_text(sender_phone, "What is the title of the new Team Task?")
            set_wa_state(sender_phone, "WAITING_FOR_TEAM_TASK_TITLE")
        return

    # ── Guest Menu Routing ───────────────────────────────────────────────────
    if button_id.startswith("guest_"):
        if button_id == "guest_office":
            send_text(sender_phone, "🏢 *Office Spaces*\n\nExplore premium office spaces designed for business growth & success in Gurugram. From startups to enterprises, we offer state-of-the-art facilities.\n\nVisit: https://goodearthinfra.in/office")
        elif button_id == "guest_retail":
            send_text(sender_phone, "🛍️ *Retail Spaces*\n\nDiscover prime retail locations that attract high footfall and provide maximum visibility for your brand.\n\nVisit: https://goodearthinfra.in/retail")
        elif button_id == "guest_leasing":
            send_text(sender_phone, "🤝 *Leasing Options*\n\nFlexible leasing terms tailored to your business needs. Get in touch with our leasing experts today.\n\nVisit: https://goodearthinfra.in/leasing")
        elif button_id == "guest_about":
            send_text(sender_phone, "ℹ️ *About Good Earth Infra*\n\nFormerly Galaxy Group, we specialize in the sale & leasing of commercial spaces in Gurugram, building landmarks of tomorrow.\n\nVisit: https://goodearthinfra.in/about-us")
        elif button_id == "guest_careers":
            send_text(sender_phone, "💼 *Careers*\n\nJoin our dynamic team and build a rewarding career in commercial real estate.\n\nVisit: https://goodearthinfra.in/careers")
        return
        
    # ── Task Actions Routing ─────────────────────────────────────────────────
    if button_id.startswith("task_"):
        parts = button_id.split("_", 2)
        if len(parts) < 3: return
        
        action = parts[1]
        task_id = parts[2]
        
        if action == "accept":
            orchestrate_status_update(user, task_id, "Accepted")
            send_text(sender_phone, "✅ Task Accepted! The creator has been notified.")
            
        elif action == "start":
            orchestrate_status_update(user, task_id, "In Progress")
            send_text(sender_phone, "🚀 Task moved to In Progress! Keep up the good work.")
            
        elif action == "complete":
            orchestrate_status_update(user, task_id, "Completed")
            send_text(sender_phone, "🎉 Task Completed! Awaiting final closure.")
            
        elif action == "note":
            send_text(sender_phone, "Please type your note now, or send a Voice Note 🎤")
            set_wa_state(sender_phone, "WAITING_FOR_NOTE", {"task_id": task_id})
            
        elif action == "proof":
            send_text(sender_phone, "Please upload an image or document as proof of completion 📎")
            set_wa_state(sender_phone, "WAITING_FOR_PROOF", {"task_id": task_id})
            
        elif action == "timeline":
            from tasks.timeline import get_task_timeline
            events = get_task_timeline(task_id)
            timeline_str = "⏱️ *Task Timeline*\n"
            for ev in events:
                timeline_str += f"- {ev['action']} ({ev['users']['name']})\n"
                if ev.get('note'): timeline_str += f"  📝 {ev['note']}\n"
            send_text(sender_phone, timeline_str)
            
        elif action == "ignore":
            send_text(sender_phone, "Task ignored. It will remain in the Pending queue.")
            
        elif action == "close":
            orchestrate_status_update(user, task_id, "Closed")
            send_text(sender_phone, "Task has been successfully closed.")
            from whatsapp.ux import send_followup_prompt
            send_followup_prompt(sender_phone, task_id)
            
        elif action == "followup":
            from tasks.service import create_followup_task
            try:
                new_task = create_followup_task(user, task_id)
                send_text(sender_phone, f"✅ Follow-up task created: '{new_task['title']}'\n\nYou can update its details later.")
            except Exception as e:
                logger.error(f"Error creating follow-up task: {e}")
                send_text(sender_phone, "Failed to create follow-up task. Please try again.")
                
        elif action == "ignorefollowup":
            send_text(sender_phone, "Noted. No follow-up task will be created.")
            
        elif action == "archive":
            from tasks.service import orchestrate_archive_task
            try:
                orchestrate_archive_task(user, task_id)
                send_text(sender_phone, "✅ Task archived successfully.")
            except Exception as e:
                logger.error(f"Error archiving task: {e}")
                send_text(sender_phone, "Failed to archive task (or permission denied).")
                
        elif action == "restore":
            from tasks.service import orchestrate_restore_task
            try:
                orchestrate_restore_task(user, task_id)
                send_text(sender_phone, "✅ Task restored successfully.")
            except Exception as e:
                logger.error(f"Error restoring task: {e}")
                send_text(sender_phone, "Failed to restore task (or permission denied).")
                
        elif action == "delete":
            from tasks.service import orchestrate_delete_task
            try:
                orchestrate_delete_task(user, task_id)
                send_text(sender_phone, "✅ Task deleted permanently.")
            except Exception as e:
                logger.error(f"Error deleting task: {e}")
                send_text(sender_phone, "Failed to delete task (or permission denied).")
                
        elif action == "remind":
            send_text(sender_phone, "When do you want to be reminded? (e.g. 'tomorrow at 10am')")
            set_wa_state(sender_phone, "WAITING_FOR_REMINDER", {"task_id": task_id})

