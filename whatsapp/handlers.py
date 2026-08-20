import logging
from tasks.service import orchestrate_status_update
from whatsapp.ux import send_text, send_interactive_buttons, send_list_message
from db import supabase

logger = logging.getLogger(__name__)

def set_wa_state(phone: str, state: str, metadata: dict = None):
    """Sets a temporary conversation state for multi-step flows."""
    try:
        payload = {"whatsapp_number": phone, "action": state}
        if metadata:
            payload["metadata"] = metadata
            if metadata.get("task_id"):
                payload["task_id"] = metadata.get("task_id")
            
        supabase.table("wa_task_states").upsert(payload, on_conflict="whatsapp_number").execute()
    except Exception as e:
        logger.error(f"Error setting WA state: {e}")

def handle_interactive_reply(sender_phone: str, button_id: str, user: dict):
    """Routes an interactive button/list ID to the proper service logic."""
    if not user:
        return
        
    logger.info(f"UX Handler processing button ID: {button_id}")
    
    # ── Facilities Module Routing ───────────────────────────────────────────
    if button_id.startswith("fac_") or user.get("department") == "Facilities":
        from facilities.flows.router import route_facilities_message
        route_facilities_message(sender_phone, button_id=button_id, user=user)
        return
        
    # ── Main Menu Routing ────────────────────────────────────────────────────
    if button_id.startswith("menu_"):
        if button_id == "menu_team_tasks":
            import asyncio
            from core.logic import process_user_message
            async def _send_reply(text=None, document=None, target_user_id=None):
                if text: send_text(sender_phone, text)
            asyncio.run(process_user_message(sender_phone, "show team tasks", send_reply_func=_send_reply))
            
        elif button_id == "menu_my_tasks":
            import asyncio
            from core.logic import process_user_message
            async def _send_reply(text=None, document=None, target_user_id=None):
                if text: send_text(sender_phone, text)
            asyncio.run(process_user_message(sender_phone, "show my personal tasks", send_reply_func=_send_reply))
            
        elif button_id == "menu_create_task":
            buttons = [
                {"id": "create_task_personal", "title": "Personal Task"},
                {"id": "create_task_team", "title": "Team Task"}
            ]
            send_interactive_buttons(sender_phone, "What type of task do you want to create?", buttons)
            
        elif button_id == "menu_update_task":
            buttons = [
                {"id": "update_task_personal", "title": "Personal Task"},
                {"id": "update_task_team", "title": "Team Task"}
            ]
            send_interactive_buttons(sender_phone, "Which task list would you like to update?", buttons)
            
        elif button_id == "menu_update_date":
            buttons = [
                {"id": "update_date_personal", "title": "Personal Task"},
                {"id": "update_date_team", "title": "Team Task"}
            ]
            send_interactive_buttons(sender_phone, "Which task list would you like to update date for?", buttons)
            
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
            buttons = [
                {"id": "analytics_team", "title": "📋 Team Analytics"},
                {"id": "analytics_personal", "title": "👤 Personal Analytics"}
            ]
            send_interactive_buttons(sender_phone, "📈 *GEI Analytics Dashboard*\n\nSelect the type of analytics dashboard you would like to view:", buttons)
            
        elif button_id == "menu_reports":
            role = user.get("role", "Guest")
            original_role = user.get("original_role")
            if role in ["Developer", "Director"] or original_role == "Developer":
                send_text(sender_phone, "📄 *Generating Daily PDF Report...*\nPlease wait a moment while your report is generated.")
                try:
                    from core.intent_handlers import generate_pdf_report
                    from whatsapp.task_assignment import _send_document_wa
                    pdf_path = generate_pdf_report()
                    _send_document_wa(sender_phone, pdf_path)
                    send_text(sender_phone, "✅ Daily Project Report sent above!")
                except Exception as pdf_err:
                    logger.error(f"Error generating/sending PDF report: {pdf_err}")
                    send_text(sender_phone, "Failed to generate PDF report. Please contact an admin.")
            else:
                send_text(sender_phone, "📊 *Daily Reports*\n\nDetailed system PDF reports are reserved for Directors and Developers. Please contact your administrator if you need access.")
            
        else:
            send_text(sender_phone, f"You selected: {button_id} (Coming soon)")
        return
        
    # ── Building selection for Create Project ────────────────────────────────
    if button_id.startswith("create_proj_b_"):
        building_name = button_id.replace("create_proj_b_", "")
        from db import get_buildings
        from core.conversation_state import get_state, set_state
        buildings = get_buildings()
        matched = next((b for b in buildings if b["name"] == building_name), None)
        if not matched:
            send_text(sender_phone, "Invalid building selection. Please try again.")
            return
        
        state = get_state(sender_phone) or {}
        state["action"] = "create_project"
        state["step"] = "waiting_for_name"
        state["building_id"] = matched["id"]
        set_state(sender_phone, state)
        send_text(sender_phone, "What is the name of the new project?")
        return

    # ── Admin Switch Routing ─────────────────────────────────────────────────
    if button_id.startswith("admin_switch_"):
        if user.get("role") != "Developer" and user.get("original_role") != "Developer":
            send_text(sender_phone, "Unauthorized.")
            return
            
        # The real developer's user ID (not the impersonated one)
        real_id = user.get("real_user_id", user["id"])
        target = button_id.replace("admin_switch_", "")
        
        try:
            if target == "guest":
                # Guest mode: clear the FK column (set NULL) and flag via wa_task_states
                supabase.table("users").update({"impersonating_user_id": None}).eq("id", real_id).execute()
                set_wa_state(sender_phone, "GUEST_MODE")
                send_text(sender_phone, "✅ You are now testing as: Guest.\nSend 'menu' to see the Guest view.")
                
            elif target == "kanav":
                # Switching back to self: clear impersonation and guest mode
                supabase.table("users").update({"impersonating_user_id": None}).eq("id", real_id).execute()
                supabase.table("wa_task_states").delete().eq("whatsapp_number", sender_phone).execute()
                send_text(sender_phone, "✅ Switched back to your normal profile (Kanav).")
                
            else:
                # Look up the target user — MUST exist before we write
                r = supabase.table("users").select("id, name").ilike("name", f"%{target}%").execute()
                if not r.data:
                    send_text(sender_phone, f"Could not find user '{target}' in the database.")
                    return
                    
                target_id = r.data[0]["id"]
                target_name = r.data[0]["name"]
                
                # Clear any guest mode state first
                supabase.table("wa_task_states").delete().eq("whatsapp_number", sender_phone).execute()
                # Write validated FK
                supabase.table("users").update({"impersonating_user_id": target_id}).eq("id", real_id).execute()
                send_text(sender_phone, f"✅ You are now testing as: {target_name}.\nSend 'menu' to see their view.")
                
        except Exception as e:
            logger.error(f"Admin switch error for target '{target}': {e}")
            send_text(sender_phone, f"Failed to switch user. Error: {str(e)[:100]}")
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

    # ── Update Task Routing ──────────────────────────────────────────────────
    if button_id.startswith("update_task_"):
        from auth.middleware import authenticate_whatsapp_request
        user_info = authenticate_whatsapp_request(sender_phone)
        user_id = user_info["id"] if user_info else None
        
        if button_id == "update_task_personal":
            raw_tasks = supabase.table("tasks").select("*, projects(name)").neq("status", "Completed").execute().data or []
            tasks = [
                t for t in raw_tasks 
                if t.get("task_type") == "PERSONAL" and (
                    not user_id or 
                    str(t.get("created_by")) == str(user_id) or 
                    str(t.get("assigned_to")) == str(user_id)
                )
            ]
            task_type_label = "Personal Tasks"
        elif button_id == "update_task_team":
            from db import get_tasks_by_buildings
            b_data = get_tasks_by_buildings(user_id, include_completed=False)
            tasks = []
            building_lines = []
            task_ids = []
            serial = 1
            for b in (b_data or []):
                b_name = b.get("building_name", "Building")
                b_projects = b.get("projects", [])
                has_t = any(p.get("tasks") for p in b_projects)
                if not has_t:
                    continue
                building_lines.append(f"*{b_name}*")
                for p in b_projects:
                    p_name = p.get("project_name", "Project")
                    p_tasks = p.get("tasks", [])
                    if not p_tasks:
                        continue
                    building_lines.append(f"  *{p_name}*")
                    for t in p_tasks:
                        task_ids.append(t["id"])
                        tasks.append(t)
                        title = t.get("title") or t.get("name") or "Task"
                        prog = t.get("progress", 0) or 0
                        status = t.get("status", "Pending")
                        building_lines.append(f"    {serial}. *{title}* ({prog}%, Status: {status})")
                        serial += 1
            task_type_label = "Team Tasks"

        if not tasks:
            send_text(sender_phone, f"No active {task_type_label.lower()} found to update.")
            return

        lines = [f"📋 *Select a {task_type_label[:-1]} to Update:*\n"]
        task_ids = []
        for idx, t in enumerate(tasks, 1):
            task_ids.append(t["id"])
            title = t.get("title") or t.get("name") or "Task"
            prog = t.get("progress", 0)
            status = t.get("status", "Pending")
            lines.append(f"{idx}. *{title}* (Progress: {prog}%, Status: {status})")

        lines.append("\n💬 *Reply with the task number and update details* (e.g., *1 75% done* or *2 completed*), or send a voice recording!")
        
        msg = "\n".join(lines)
        from core.context_manager import update_context
        update_context(sender_phone, last_task_list=task_ids)
        if user_id:
            update_context(user_id, last_task_list=task_ids)
            
        set_wa_state(sender_phone, "WAITING_FOR_TASK_UPDATE", metadata={"task_id": task_ids[0] if task_ids else None})
        send_text(sender_phone, msg)
        return

    # ── Update Date Routing ──────────────────────────────────────────────────
    if button_id.startswith("update_date_"):
        from auth.middleware import authenticate_whatsapp_request
        from core.utils import format_date_human
        user_info = authenticate_whatsapp_request(sender_phone)
        user_id = user_info["id"] if user_info else None
        
        if button_id == "update_date_personal":
            raw_tasks = supabase.table("tasks").select("*, projects(name)").neq("status", "Completed").execute().data or []
            tasks = [
                t for t in raw_tasks 
                if t.get("task_type") == "PERSONAL" and (
                    not user_id or 
                    str(t.get("created_by")) == str(user_id) or 
                    str(t.get("assigned_to")) == str(user_id)
                )
            ]
            task_type_label = "Personal Tasks"
        elif button_id == "update_date_team":
            from db import get_tasks_by_buildings
            b_data = get_tasks_by_buildings(user_id, include_completed=False)
            tasks = []
            building_lines = []
            task_ids = []
            serial = 1
            for b in (b_data or []):
                b_name = b.get("building_name", "Building")
                b_projects = b.get("projects", [])
                has_t = any(p.get("tasks") for p in b_projects)
                if not has_t:
                    continue
                building_lines.append(f"*{b_name}*")
                for p in b_projects:
                    p_name = p.get("project_name", "Project")
                    p_tasks = p.get("tasks", [])
                    if not p_tasks:
                        continue
                    building_lines.append(f"  *{p_name}*")
                    for t in p_tasks:
                        task_ids.append(t["id"])
                        tasks.append(t)
                        title = t.get("title") or t.get("name") or "Task"
                        f_start = format_date_human(t.get("planned_start_date") or t.get("created_at"))
                        f_dl = format_date_human(t.get("deadline"))
                        building_lines.append(f"    {serial}. *{title}* (Start: {f_start} | Deadline: {f_dl})")
                        serial += 1
            task_type_label = "Team Tasks"

        if not tasks:
            send_text(sender_phone, f"No active {task_type_label.lower()} found to update date.")
            return

        lines = [f"📋 *Select a {task_type_label[:-1]} to Update Date:*\n"]
        task_ids = []
        for idx, t in enumerate(tasks, 1):
            task_ids.append(t["id"])
            title = t.get("title") or t.get("name") or "Task"
            f_start = format_date_human(t.get("planned_start_date") or t.get("created_at"))
            f_dl = format_date_human(t.get("deadline"))
            lines.append(f"{idx}. *{title}*\n   📅 Start: {f_start} | Deadline: {f_dl}")

        lines.append("\n💬 *Reply with the task number* (e.g., *1* or *task 2*) to change its date.")
        
        msg = "\n".join(lines)
        from core.context_manager import update_context
        update_context(sender_phone, last_task_list=task_ids)
        if user_id:
            update_context(user_id, last_task_list=task_ids)
            
        set_wa_state(sender_phone, "WAITING_FOR_UPDATE_DATE_TASK_SELECTION", metadata={"task_ids": task_ids})
        send_text(sender_phone, msg)
        return

    if button_id.startswith("date_type_start_"):
        task_id = button_id.replace("date_type_start_", "")
        t_row = supabase.table("tasks").select("title").eq("id", task_id).execute().data
        t_title = t_row[0].get("title", "Task") if t_row else "Task"
        send_text(sender_phone, f"Please enter new Start Date for *'{t_title}'*\n(e.g., *today*, *tomorrow*, *next Monday*, or *2026-08-10*):")
        set_wa_state(sender_phone, "WAITING_FOR_NEW_START_DATE", metadata={"task_id": task_id})
        return

    if button_id.startswith("date_type_dl_"):
        task_id = button_id.replace("date_type_dl_", "")
        t_row = supabase.table("tasks").select("title").eq("id", task_id).execute().data
        t_title = t_row[0].get("title", "Task") if t_row else "Task"
        send_text(sender_phone, f"Please enter new Deadline for *'{t_title}'*\n(e.g., *tomorrow*, *next Friday*, *in 2 weeks*, or *2026-08-15*):")
        set_wa_state(sender_phone, "WAITING_FOR_NEW_DEADLINE", metadata={"task_id": task_id})
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
    if button_id.startswith("ACCEPT_TASK_") or button_id.startswith("REJECT_TASK_"):
        if button_id.startswith("ACCEPT_TASK_"):
            button_id = f"task_accept_{button_id.replace('ACCEPT_TASK_', '')}"
        else:
            button_id = f"task_reject_{button_id.replace('REJECT_TASK_', '')}"

    if button_id.startswith("complete_img_yes_"):
        task_id = button_id.replace("complete_img_yes_", "")
        send_text(sender_phone, "Please upload an image as proof of completion 📎")
        set_wa_state(sender_phone, "WAITING_FOR_COMPLETION_IMAGE", metadata={"task_id": task_id})
        return

    if button_id.startswith("complete_img_no_"):
        task_id = button_id.replace("complete_img_no_", "")
        send_text(sender_phone, "Would you like to add a final comment or note for this task? 📝\n\nReply with your comment, or send 'No' to skip.")
        set_wa_state(sender_phone, "WAITING_FOR_COMPLETION_COMMENT", metadata={"task_id": task_id})
        return

    if button_id.startswith("task_"):
        parts = button_id.split("_", 2)
        if len(parts) < 3: return
        
        action = parts[1]
        task_id = parts[2]
        
        if action in ["accept", "reject"]:
            new_status = "Accepted" if action == "accept" else "Rejected"
            try:
                orchestrate_status_update(user, task_id, new_status)
            except Exception as e:
                logger.error(f"Error executing status update to {new_status}: {e}")

            if action == "accept":
                send_text(sender_phone, "✅ Task Accepted! The creator has been notified.")
            else:
                send_text(sender_phone, "❌ Task Rejected. The creator has been notified.")

            # Send WhatsApp notification to the Assignor / Creator
            try:
                task_res = supabase.table("tasks").select("title, deadline, due_date, created_by, assigned_by").eq("id", task_id).execute()
                if task_res.data:
                    t_data = task_res.data[0]
                    t_title = t_data.get("title", "Team Task")
                    due_val = t_data.get("deadline") or t_data.get("due_date") or "No due date"
                    d_date_str = str(due_val).split("T")[0] if due_val != "No due date" and "T" in str(due_val) else str(due_val)
                    assignor_id = t_data.get("assigned_by") or t_data.get("created_by")

                    if assignor_id and str(assignor_id).lower() != str(user.get("id")).lower():
                        from db import get_user_by_id
                        creator_user = get_user_by_id(assignor_id)
                        if creator_user:
                            creator_wa = creator_user.get("whatsapp_number") or creator_user.get("telegram_id")
                            if creator_wa:
                                creator_name = creator_user.get("name", "Creator")
                                assignee_name = user.get("name", "Assignee")
                                if action == "accept":
                                    notify_creator_msg = (
                                        f"✅ *Task Accepted!*\n\n"
                                        f"Hi {creator_name} 👋,\n"
                                        f"*{assignee_name}* accepted your Team Task:\n\n"
                                        f"📌 *Task:* {t_title}\n"
                                        f"📅 *Due Date:* {d_date_str}"
                                    )
                                else:
                                    notify_creator_msg = (
                                        f"❌ *Task Rejected*\n\n"
                                        f"Hi {creator_name} 👋,\n"
                                        f"*{assignee_name}* rejected your Team Task:\n\n"
                                        f"📌 *Task:* {t_title}\n"
                                        f"📅 *Due Date:* {d_date_str}"
                                    )
                                sent = send_text(creator_wa, notify_creator_msg)
                                if not sent:
                                    from whatsapp.task_assignment import send_task_status_template
                                    act_str = "ACCEPTED" if action == "accept" else "REJECTED"
                                    sent = send_task_status_template(creator_wa, creator_name, assignee_name, act_str, t_title, d_date_str)

                                if sent:
                                    logger.info(f"✅ Creator notification sent to {creator_name} ({creator_wa}) that task '{t_title}' was {action}ed by {assignee_name}")
                                else:
                                    logger.error(f"❌ Failed to send creator notification to {creator_name} ({creator_wa}) for task '{t_title}'")
                            else:
                                logger.warning(f"⚠️ Creator {creator_user.get('name')} (ID: {assignor_id}) has no valid whatsapp_number")
            except Exception as notify_err:
                logger.error(f"Error sending creator notification for task {action}: {notify_err}")
            return
            
        elif action == "start":
            orchestrate_status_update(user, task_id, "In Progress")
            send_text(sender_phone, "🚀 Task moved to In Progress! Keep up the good work.")
            
        elif action == "complete":
            body = "Would you like to attach an image proof of completion for this task? 📸"
            buttons = [
                {"id": f"complete_img_yes_{task_id}", "title": "Yes"},
                {"id": f"complete_img_no_{task_id}", "title": "No"}
            ]
            send_interactive_buttons(sender_phone, body, buttons)
            set_wa_state(sender_phone, "WAITING_FOR_COMPLETION_IMAGE_DECISION", metadata={"task_id": task_id})
            return
            
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

    # ── Analytics Routing ───────────────────────────────────────────────────
    if button_id.startswith("analytics_"):
        if button_id == "analytics_team":
            dashboard_text = build_team_analytics_dashboard(user)
            send_text(sender_phone, dashboard_text)
        elif button_id == "analytics_personal":
            dashboard_text = build_personal_analytics_dashboard(user)
            send_text(sender_phone, dashboard_text)
        return

    # ── Assign Task Routing ──────────────────────────────────────────────────
    if button_id.startswith("assign_task_"):
        parts = button_id.split("_", 3)
        if len(parts) >= 4:
            task_id = parts[2]
            member_id = parts[3]

            from db import get_user_by_id
            from whatsapp.ux import clean_phone_number

            assigned_user = get_user_by_id(member_id)
            member_name = assigned_user.get("name", "Team Member") if assigned_user else "Team Member"

            update_payload = {
                "assigned_to": member_id,
                "assignment_status": "pending_acceptance"
            }
            if assigned_user and assigned_user.get("team_id"):
                update_payload["team_id"] = assigned_user.get("team_id")

            try:
                supabase.table("tasks").update(update_payload).eq("id", task_id).execute()
                task_res = supabase.table("tasks").select("title, deadline, due_date").eq("id", task_id).execute()
                task_title = "Team Task"
                due_date_str = "No due date"
                if task_res.data:
                    task_title = task_res.data[0].get("title") or "Team Task"
                    due_val = task_res.data[0].get("deadline") or task_res.data[0].get("due_date") or "No due date"
                    due_date_str = str(due_val).split("T")[0] if due_val != "No due date" and "T" in str(due_val) else str(due_val)
            except Exception as update_err:
                logger.error(f"Error updating task assigned_to: {update_err}")
                task_title = "Team Task"
                due_date_str = "No due date"

            send_text(sender_phone, f"✅ Task '{task_title}' assigned to *{member_name}*!")

            # Send WhatsApp notification to assigned member
            if assigned_user:
                raw_wa = assigned_user.get("whatsapp_number") or assigned_user.get("telegram_id")
                assigned_wa = clean_phone_number(raw_wa) if raw_wa else ""
                if assigned_wa:
                    creator_name = user.get("name", "A team member") if user else "A team member"
                    is_self_assignment = (user and assigned_user and str(user.get("id")) == str(assigned_user.get("id")))

                    if is_self_assignment:
                        notify_msg = (
                            f"📋 *New Task Assigned to You!*\n\n"
                            f"Hi {member_name} 👋,\n"
                            f"*{creator_name}* assigned a new Team Task to you:\n\n"
                            f"📌 *Task:* {task_title}\n"
                            f"📅 *Due Date:* {due_date_str}\n\n"
                            f"Please check your task list in GEI_BOT for details."
                        )
                        sent = send_text(assigned_wa, notify_msg)
                        if sent:
                            logger.info(f"WhatsApp message for task acceptance has been sent to {member_name} ({assigned_wa}) for task '{task_title}' (ID: {task_id})")
                            print(f"[ASSIGNMENT] WhatsApp message for task acceptance has been sent to {member_name} ({assigned_wa}) for task '{task_title}' (ID: {task_id})", flush=True)
                        else:
                            logger.error(f"❌ Failed to send self-assignment notification to {member_name} ({assigned_wa}) for task '{task_title}' (ID: {task_id})")
                    else:
                        body = (
                            f"📋 *New Task Assigned to You!*\n\n"
                            f"Hi {member_name} 👋,\n"
                            f"*{creator_name}* assigned a new Team Task to you:\n\n"
                            f"📌 *Task:* {task_title}\n"
                            f"📅 *Due Date:* {due_date_str}\n\n"
                            f"Please select an option below:"
                        )
                        buttons = [
                            {"id": f"task_accept_{task_id}", "title": "Accept"},
                            {"id": f"task_reject_{task_id}", "title": "Reject"}
                        ]
                        sent = send_interactive_buttons(assigned_wa, body, buttons)
                        if not sent:
                            # Fallback to Meta Utility Template task_assignment_notification (bypasses 24h window)
                            from whatsapp.task_assignment import send_task_assignment_template
                            sent_template = send_task_assignment_template(assigned_wa, member_name, creator_name, task_title, due_date_str, task_id)
                            if not sent_template:
                                # Fallback to plain text if template also fails
                                fallback_msg = (
                                    f"📋 *New Task Assigned to You!*\n\n"
                                    f"Hi {member_name} 👋,\n"
                                    f"*{creator_name}* assigned a new Team Task to you:\n\n"
                                    f"📌 *Task:* {task_title}\n"
                                    f"📅 *Due Date:* {due_date_str}\n\n"
                                    f"Reply *Accept* to accept or *Reject* to reject this task."
                                )
                                send_text(assigned_wa, fallback_msg)

                        logger.info(f"WhatsApp message for task acceptance has been sent to {member_name} ({assigned_wa}) for task '{task_title}' (ID: {task_id})")
                        print(f"[ASSIGNMENT] WhatsApp message for task acceptance has been sent to {member_name} ({assigned_wa}) for task '{task_title}' (ID: {task_id})", flush=True)
                else:
                    logger.warning(f"⚠️ Assigned user {member_name} (ID: {member_id}) has no valid whatsapp_number configured")
        return


def send_assignee_selection_prompt(to_phone: str, task_id: str, task_title: str, creator_user: dict):
    """Presents interactive selection of team members to assign the team task."""
    from db import supabase
    from whatsapp.ux import send_interactive_buttons, send_list_message

    try:
        res = supabase.table("users").select("id, name, role, whatsapp_number, telegram_id, team_id").execute()
        users_list = res.data or []
    except Exception as e:
        logger.error(f"Error fetching users for task assignment prompt: {e}")
        users_list = []

    team_id = creator_user.get("team_id") if creator_user else None
    
    if team_id:
        same_team = [u for u in users_list if str(u.get("team_id")) == str(team_id)]
        other_team = [u for u in users_list if str(u.get("team_id")) != str(team_id)]
        members = same_team + other_team
    else:
        members = users_list

    members = [m for m in members if m.get("name")]

    if not members:
        send_text(to_phone, f"✅ Team Task '{task_title}' created successfully!")
        return

    body = f"✅ Team Task '{task_title}' created!\n\n👥 Who should this Team Task be assigned to?"

    if len(members) <= 3:
        buttons = [
            {"id": f"assign_task_{task_id}_{m['id']}", "title": m["name"][:20]}
            for m in members[:3]
        ]
        send_interactive_buttons(to_phone, body, buttons)
    else:
        sections = [{
            "title": "Select Team Member",
            "rows": [
                {"id": f"assign_task_{task_id}_{m['id']}", "title": m["name"][:24], "description": m.get("role", "Team Member")}
                for m in members[:10]
            ]
        }]
        send_list_message(to_phone, body, "Assign Task", sections)


def build_team_analytics_dashboard(user: dict) -> str:
    """Builds person-wise team analytics showing done, left, blocked tasks and velocity."""
    from db import get_all_tasks
    from collections import defaultdict

    target_user_id = user.get("id") if user else None
    user_role = str(user.get("role", "")).capitalize() if user else ""
    original_role = user.get("original_role") if user else None
    user_team_id = user.get("team_id") if user else None

    all_tasks = get_all_tasks(include_personal=True)
    
    # Filter team tasks based on role / team membership
    if user_role in ["Developer", "Director"] or original_role == "Developer":
        team_tasks = [t for t in all_tasks if t.get("task_type") != "PERSONAL"]
    else:
        team_tasks = [
            t for t in all_tasks 
            if t.get("task_type") != "PERSONAL" and (
                (user_team_id and str(t.get("team_id")) == str(user_team_id)) or
                str(t.get("assigned_to")) == str(target_user_id) or
                str(t.get("assigned_by")) == str(target_user_id) or
                str(t.get("created_by")) == str(target_user_id)
            )
        ]

    if not team_tasks:
        return "📈 *GEI Team Analytics Dashboard*\n\nNo team tasks currently found in the system."

    # Group person-wise
    grouped_by_user = defaultdict(list)
    for t in team_tasks:
        assignee_name = "Unassigned"
        if t.get("assigned_to_user") and isinstance(t["assigned_to_user"], dict):
            assignee_name = t["assigned_to_user"].get("name") or "Unassigned"
        elif t.get("assigned_to"):
            assignee_name = str(t.get("assigned_to"))[:8]
        grouped_by_user[assignee_name].append(t)

    msg = "📈 *GEI Team Analytics Dashboard*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━\n"
    msg += "👥 *Person-Wise Breakdown*\n\n"

    total_all = len(team_tasks)
    completed_all = 0
    left_all = 0
    blocked_all = 0
    total_prog_sum = 0

    for person_name, p_tasks in sorted(grouped_by_user.items(), key=lambda x: x[0]):
        p_total = len(p_tasks)
        p_completed = 0
        p_left = 0
        p_blocked = 0
        p_prog_sum = 0

        for t in p_tasks:
            try:
                prog = int(str(t.get("progress", 0) or 0).replace("%", "").strip())
            except Exception:
                prog = 0
            status = str(t.get("status", "")).capitalize()
            blocker = t.get("blocker_reason") or t.get("blockers")

            is_done = status in ["Completed", "Closed"] or prog >= 100
            is_blocked = bool(blocker and str(blocker).lower() not in ["none", "null", "undefined", "no blocker"])

            if is_done:
                p_completed += 1
            else:
                p_left += 1

            if is_blocked and not is_done:
                p_blocked += 1

            p_prog_sum += min(prog, 100)

        completed_all += p_completed
        left_all += p_left
        blocked_all += p_blocked
        total_prog_sum += p_prog_sum

        avg_prog = round(p_prog_sum / p_total) if p_total > 0 else 0

        msg += f"👤 *{person_name}*\n"
        msg += f"  ├ 📋 Total Tasks: {p_total}\n"
        msg += f"  ├ ✅ Done: {p_completed}\n"
        msg += f"  ├ ⏳ Left: {p_left}\n"
        msg += f"  ├ 🛑 Blocked: {p_blocked}\n"
        msg += f"  └ 📊 Velocity: {avg_prog}%\n\n"

    overall_avg = round(total_prog_sum / total_all) if total_all > 0 else 0

    msg += "📌 *Overall Team Summary*\n"
    msg += f"  • Total Team Tasks: {total_all}\n"
    msg += f"  • Done: {completed_all} | Left: {left_all} | Blocked: {blocked_all}\n"
    msg += f"  • Overall Team Velocity: {overall_avg}%\n"

    return msg


def build_personal_analytics_dashboard(user: dict) -> str:
    """Builds personal task analytics showing done, left, blocked tasks and velocity."""
    from db import get_all_tasks

    target_user_id = user.get("id") if user else None
    user_name = user.get("name", "there") if user else "there"

    all_tasks = get_all_tasks(include_personal=True)
    
    personal_tasks = [
        t for t in all_tasks 
        if t.get("task_type") == "PERSONAL" and (
            str(t.get("created_by")) == str(target_user_id) or
            str(t.get("assigned_to")) == str(target_user_id) or
            str(t.get("assigned_by")) == str(target_user_id) or
            (t.get("assigned_to_user") and str(t["assigned_to_user"].get("id")) == str(target_user_id))
        )
    ]

    if not personal_tasks:
        return f"👤 *Personal Analytics Dashboard*\n\nHi {user_name} 👋, you currently have no personal tasks recorded in Supabase."

    total_tasks = len(personal_tasks)
    completed = 0
    left = 0
    blocked = 0
    prog_sum = 0

    for t in personal_tasks:
        try:
            prog = int(str(t.get("progress", 0) or 0).replace("%", "").strip())
        except Exception:
            prog = 0
        status = str(t.get("status", "")).capitalize()
        blocker = t.get("blocker_reason") or t.get("blockers")

        is_done = status in ["Completed", "Closed"] or prog >= 100
        is_blocked = bool(blocker and str(blocker).lower() not in ["none", "null", "undefined", "no blocker"])

        if is_done:
            completed += 1
        else:
            left += 1

        if is_blocked and not is_done:
            blocked += 1

        prog_sum += min(prog, 100)

    avg_prog = round(prog_sum / total_tasks) if total_tasks > 0 else 0

    msg = f"👤 *Personal Task Analytics*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"Hi {user_name} 👋, here is your personal task breakdown:\n\n"
    msg += f"  • 📋 Total Tasks: {total_tasks}\n"
    msg += f"  • ✅ Done: {completed}\n"
    msg += f"  • ⏳ Left: {left}\n"
    msg += f"  • 🛑 Blocked: {blocked}\n"
    msg += f"  • 📊 Personal Velocity: {avg_prog}%\n\n"
    msg += "💡 *Tip:* Tap '👤 My Personal Tasks' from the main menu to view and update your active tasks."

    return msg


def handle_direct_task_update(sender_phone: str, text: str, user_info: dict) -> bool:
    """
    Parses and executes a task update input (e.g. '1 75% done' or '2 completed' or voice transcript).
    Returns True if successfully processed, False if it couldn't resolve the task.
    """
    from core.context_manager import get_context
    from db import supabase, save_update
    from core.utils import resolve_task_from_list
    import re

    ctx = get_context(sender_phone)
    task_ids = ctx.get("last_task_list", [])
    user_id = user_info.get("id") if user_info else None

    if not task_ids and user_id:
        ctx_user = get_context(user_id)
        task_ids = ctx_user.get("last_task_list", [])

    all_raw = supabase.table("tasks").select("*, projects(name)").execute().data or []
    if task_ids:
        tasks = []
        for tid in task_ids:
            found = next((t for t in all_raw if t["id"] == tid), None)
            if found:
                tasks.append(found)
    else:
        tasks = [t for t in all_raw if t.get("status") != "Completed"]

    if not tasks:
        send_text(sender_phone, "No active tasks found to update.")
        return True

    # 1. Resolve task index or task matching
    target_task = None

    # Check leading number or explicit task number
    num_match = re.search(r'^(?:task|number|#)?\s*(\d+)', text.strip(), re.IGNORECASE)
    if num_match:
        idx = int(num_match.group(1)) - 1
        if 0 <= idx < len(tasks):
            target_task = tasks[idx]

    if not target_task:
        numbers = re.findall(r'\b\d+\b', text)
        if numbers:
            idx = int(numbers[0]) - 1
            if 0 <= idx < len(tasks):
                target_task = tasks[idx]

    if not target_task:
        target_task = resolve_task_from_list(text, tasks, last_list_ids=task_ids)

    if not target_task:
        send_text(sender_phone, "Could not identify which task you want to update. Please reply with the task number (e.g., '1 75% done').")
        return True

    # Check building access for update permission
    if user_id:
        from db import check_building_access
        if not check_building_access(user_id, target_task["id"]):
            send_text(sender_phone, "🚫 Unauthorized: You do not have permission to update tasks from this building.")
            return True

    # 2. Extract progress
    progress = None
    pct_match = re.search(r'(\d{1,3})\s*(?:%|percent)', text, re.IGNORECASE)
    if pct_match:
        progress = int(pct_match.group(1))
    elif re.search(r'\b(completed|done|finished|complete|closed)\b', text, re.IGNORECASE):
        numbers = re.findall(r'\b\d+\b', text)
        if len(numbers) >= 2:
            try:
                val = int(numbers[1])
                if 0 <= val <= 100:
                    progress = val
                else:
                    progress = 100
            except ValueError:
                progress = 100
        else:
            progress = 100
    else:
        numbers = re.findall(r'\b\d+\b', text)
        if len(numbers) >= 2:
            try:
                val = int(numbers[1])
                if 0 <= val <= 100:
                    progress = val
            except ValueError:
                pass
        elif len(numbers) == 1:
            try:
                val = int(numbers[0])
                if 0 <= val <= 100 and val != (tasks.index(target_task) + 1):
                    progress = val
            except ValueError:
                pass

    if progress is None:
        import random
        progress = random.randint(10, 35)

    progress = min(100, max(0, progress))

    # Extract initial note text from user input (e.g. "2 test comments and it worked" -> "test comments and it worked")
    note_text = text.strip()
    note_text = re.sub(r'^(?:task|number|#)?\s*\d+\s*', '', note_text, flags=re.IGNORECASE).strip()
    note_text = re.sub(r'\d{1,3}\s*(?:%|percent)', '', note_text, flags=re.IGNORECASE).strip()
    note_text = re.sub(r'\b(completed|done|finished|complete|closed)\b', '', note_text, flags=re.IGNORECASE).strip()
    note_text = re.sub(r'^[%\s,.-]+|[%\s,.-]+$', '', note_text).strip()
    initial_note = note_text if note_text else None

    task_id = target_task["id"]

    # 3. If completing task (progress >= 100), enter completion flow (ask for image proof decision and optional comment)
    if progress >= 100:
        body = "Would you like to attach an image proof of completion for this task? 📸"
        buttons = [
            {"id": f"complete_img_yes_{task_id}", "title": "Yes"},
            {"id": f"complete_img_no_{task_id}", "title": "No"}
        ]
        send_interactive_buttons(sender_phone, body, buttons)
        set_wa_state(sender_phone, "WAITING_FOR_COMPLETION_IMAGE_DECISION", metadata={"task_id": task_id})
        return True

    # Save update to DB for non-completion progress updates
    save_update(task_id, progress, "None", [], user_id, note=initial_note)

    if initial_note:
        from tasks.timeline import add_timeline_event
        add_timeline_event(task_id, user_id, "Note added to task update", note=initial_note)
        try:
            supabase.table("tasks").update({"notes": initial_note}).eq("id", task_id).execute()
        except Exception as err:
            logger.warning(f"Could not update task notes in DB: {err}")

    # 4. Prompt for notes/comments and set WAITING_FOR_UPDATE_NOTE state
    task_name = target_task.get("title") or target_task.get("name") or "Task"
    new_status = "In Progress" if progress > 0 else "Pending"

    send_text(
        sender_phone,
        f"Would you like to add any notes or comments for *'{task_name}'*? 📝\n\n"
        f"Reply with your comment, or send *No* to skip."
    )
    set_wa_state(sender_phone, "WAITING_FOR_UPDATE_NOTE", metadata={
        "task_id": task_id,
        "task_name": task_name,
        "progress": progress,
        "status": new_status,
        "initial_note": initial_note
    })
    return True


