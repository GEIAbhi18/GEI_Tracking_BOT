import logging
from auth.context import get_current_user
from tasks.service import orchestrate_status_update
from whatsapp.ux import send_text
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
            send_text(sender_phone, "Fetching your Team Tasks...")
            # Trigger list team tasks logic
        elif button_id == "menu_my_tasks":
            send_text(sender_phone, "Fetching your Personal Tasks...")
            # Trigger list personal tasks logic
        elif button_id == "menu_create_task":
            send_text(sender_phone, "What is the title of the new task?")
            set_wa_state(sender_phone, "WAITING_FOR_TASK_TITLE")
        else:
            send_text(sender_phone, f"You selected: {button_id} (Coming soon)")
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

