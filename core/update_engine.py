import logging
import re
import json
from core.llm_parser import parse_with_llm
from core.conversation_state import get_state, set_state, clear_state
from core.context_manager import get_context, update_context
from core.message_parser import parse_message as rule_based_parse_message
import core.intent_handlers as handlers
from db import (
    get_all_tasks, get_projects, get_user_by_telegram_id, create_ticket,
    update_user_activity, remove_blocker, create_project_db, add_task, save_note,
    add_blocker, update_task_image
)
from core.utils import parse_human_date, resolve_project, resolve_task_from_list
from core.error_messages import (
    friendly_clarify, friendly_system_error, friendly_task_not_found,
    friendly_project_not_found, friendly_missing_info,
)

logger = logging.getLogger(__name__)


def _resolve_user_ue(user_id):
    """Resolve user by telegram_id first, then fall back to whatsapp_number or DB ID.
    (Separate copy to avoid circular import with intent_handlers.)"""
    if not user_id:
        return None
    u_info = get_user_by_telegram_id(user_id)
    if u_info:
        return u_info
    try:
        from whatsapp.task_assignment import get_user_by_whatsapp
        u_info = get_user_by_whatsapp(str(user_id))
        if u_info:
            return u_info
    except Exception:
        pass
    try:
        from db import get_user_by_id
        u_info = get_user_by_id(str(user_id))
        if u_info:
            return u_info
    except Exception:
        pass
    return None

async def handle_message(text: str, user_id: int, images: list, send_reply_func):
    """
    Main message handler implementing the audit-compliant architecture:
    State -> LLM -> Intent Handlers -> Fallback
    """
    
    # Update context with raw message
    update_context(user_id, message=text)
    context = get_context(user_id)
    
    # Track activity (Feature 2)
    update_user_activity(user_id)

    # 1. Check for command mode (bypass LLM/State)
    if text.startswith('/'):
        # Handled by telegram_adapter CommandHandlers
        return

    # 2. Check Conversation State
    state = get_state(user_id)
    stripped_lower = text.strip().lower()

    # Pre-intercept "state-breakers" - If user types a clear top-level command, break any existing loop
    COMMAND_KEYWORDS = [
        "/start", "show tasks", "view tasks", "list tasks", "show blockers", 
        "team tasks", "personal tasks", "my tasks", "show team tasks", "show my personal tasks",
        "show all tasks", "help", "/help", "exit", "cancel", "update task", "add image", 
        "complete task", "task detail", "create project", "create task", "add blocker",
        "update date", "edit date"
    ]
    if state and any(cmd in stripped_lower for cmd in COMMAND_KEYWORDS):
        from core.context_manager import clear_context
        clear_state(user_id)
        clear_context(user_id)
        update_context(user_id, message=text) # Start fresh with current command
        context = get_context(user_id) # Refresh blank context
        state = None # Fall through to LLM/Router

    # MULTILINE UPDATE INTERCEPT 1: "YES/EDIT" Confirmation
    if state and state.get("action") == "awaiting_multi_update_confirmation":
        from core.multi_line_update import handle_multi_update_confirmation
        handled = await handle_multi_update_confirmation(text, user_id, state, send_reply_func, clear_state)
        if handled:
            return

    # MULTILINE UPDATE INTERCEPT 2: Ending with 'done'
    # text might end with done, or the word 'done' is the last line.
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if lines and lines[-1].lower() == "done":
        from core.multi_line_update import process_multi_line_trigger
        handled = await process_multi_line_trigger(text, user_id, send_reply_func, set_state)
        if handled:
            return

    if state:
        await continue_conversation(text, user_id, state, images, send_reply_func)
        return

    # 2.5 Intercept specific commands and regexes before LLM
    import re
    match_reply = re.match(r'^Ticket\s*(\d+)\.\s*(.+)$', text.strip(), re.IGNORECASE)
    match_close = re.match(r'^close Ticket\s*(\d+)$', text.strip(), re.IGNORECASE)
    
    if match_close:
        parsed = {"intent": "close_ticket", "ticket_index": int(match_close.group(1)), "confidence": 1.0}
        await handlers.handle_close_ticket(parsed, user_id, context, send_reply_func)
        return
    elif match_reply:
        parsed = {"intent": "reply_ticket", "ticket_index": int(match_reply.group(1)), "message": match_reply.group(2).strip(), "confidence": 1.0}
        await handlers.handle_reply_ticket(parsed, user_id, context, send_reply_func)
        return

    stripped_lower = text.strip().lower()
    
    # 2.6 Kanav specific notification ping request
    if "ask asif" in stripped_lower or "ask for update" in stripped_lower or stripped_lower == "/ask_asif":
        await handlers.handle_trigger_reminder_user({"intent": "trigger_reminder_user", "target_user": "Asif"}, user_id, context, send_reply_func)
        return

    # Check for "no blocker" or "remove blocker" before progress updates
    if "no blocker" in stripped_lower or "blocker resolved" in stripped_lower or "removed blocker" in stripped_lower:
        m = re.search(r'(\d+)', stripped_lower)
        t_ref = f"task {m.group(1)}" if m else None
        await handlers.handle_remove_blocker({"intent": "remove_blocker", "task_name": t_ref}, user_id, context, send_reply_func)
        return

    is_task_query = (
        stripped_lower in ["show tasks", "view tasks", "list tasks", "show_tasks", "list_tasks", 
                           "show team tasks", "show my personal tasks", "show all tasks", 
                           "team tasks", "personal tasks", "my tasks", "my personal tasks"] or
        ("show" in stripped_lower and "task" in stripped_lower) or
        ("list" in stripped_lower and "task" in stripped_lower) or
        ("view" in stripped_lower and "task" in stripped_lower) or
        stripped_lower in ["tasks", "/tasks", "all tasks"]
    ) and not any(action in stripped_lower for action in ["complete", "update", "create", "new", "delete", "add", "detail"])

    if stripped_lower in ["complete task", "complete_task"]:
        await handlers.handle_complete_task({"intent": "complete_task"}, user_id, context, send_reply_func)
        return
    elif is_task_query:
        await handlers.handle_query_tasks({"intent": "query_tasks", "raw_text": text}, user_id, context, send_reply_func)
        return
    elif stripped_lower in ["show blockers", "view blockers", "list blockers", "show_blockers", "view_blockers"]:
        await handlers.handle_query_blockers({"intent": "query_blockers"}, user_id, context, send_reply_func)
        return
    elif stripped_lower in ["create project", "new project", "create_project", "new_project"]:
        await handlers.handle_create_project({"intent": "create_project"}, user_id, context, send_reply_func)
        return
    elif stripped_lower in ["create task", "new task", "create_task", "new_task"]:
        await handlers.handle_create_task({"intent": "create_task"}, user_id, context, send_reply_func)
        return
    elif stripped_lower in ["add image", "upload image", "add_image", "upload_image"]:
        await handlers.handle_add_image({"intent": "add_image"}, user_id, context, send_reply_func)
        return
    elif stripped_lower in ["update task", "task update", "update_task", "task_update"]:
        await handlers.handle_task_update({"intent": "task_update"}, user_id, context, send_reply_func)
        return
    elif stripped_lower in ["raise ticket", "create ticket", "raise_ticket", "create_ticket"]:
        await handlers.handle_create_ticket({"intent": "create_ticket"}, user_id, context, send_reply_func)
        return
    elif stripped_lower in ["view tickets", "show tickets", "view_tickets", "show_tickets"]:
        await handlers.handle_view_tickets({"intent": "view_tickets"}, user_id, context, send_reply_func)
        return
    elif stripped_lower in ["edit date", "edit_date", "/edit_date", "change date", "update date", "update_date", "/update_date"]:
        await handlers.handle_edit_date({"intent": "edit_date"}, user_id, context, send_reply_func)
        return
    elif stripped_lower in ["create note", "create_note", "/create_note", "add note"]:
        await handlers.handle_create_note({"intent": "create_note"}, user_id, context, send_reply_func)
        return
    elif (stripped_lower in [
        "get report", "request report", "get_report", "request_report",
        "report", "show report", "daily report", "give report",
        "give me report", "generate report", "send report", "/get_report"
    ] or (stripped_lower == "report")):
        await handlers.handle_request_report({"intent": "request_report"}, user_id, context, send_reply_func)
        return
    elif stripped_lower in ["hello", "hi", "hey", "greetings", "start", "help"]:
        await handlers.handle_greeting({"intent": "greeting"}, user_id, context, send_reply_func)
        return
        
    # High-priority: task detail detection (Step 1/6)
    match_detail = re.match(r'^(show\s*)?task\s*(\d+)(\s*info|\s*details)?$', stripped_lower)
    if match_detail:
        await handlers.handle_get_task_detail({"intent": "get_task_detail", "task_reference": f"task {match_detail.group(2)}"}, user_id, context, send_reply_func)
        return
        
    # 3. LLM Intent Parser
    intents_to_process = []
    
    try:
        # Prepare history for LLM context
        history = [{"role": "user", "content": m} for m in context.get("messages", [])[:-1]]
        
        parsed_obj = parse_with_llm(text, history=history, state=state)
        
        raw_intents = parsed_obj.get("intents", [])
        if not raw_intents:
            raw_intents = [{"intent": "clarify", "confidence": 0}]
            
        for p_obj in raw_intents:
            intent = p_obj.get("intent", "clarify")
            confidence = p_obj.get("confidence", 0)
    
            # Mapping new schema to existing handler keys
            parsed = {
                "intent": intent,
                "task_name": p_obj.get("task_reference") or p_obj.get("project_name"),
                "project_name_extracted": p_obj.get("project_name"),
                "progress": p_obj.get("progress"),
                "blocker_description": p_obj.get("blocker_text"),
                "confidence": confidence,
                "query_filters": p_obj.get("query_filters"),
                "target_user": p_obj.get("target_user"),
                "assigned_to": p_obj.get("assigned_to"),
                "is_personal": p_obj.get("is_personal"),
                "message_type": p_obj.get("message_type"),
                "deadline": p_obj.get("deadline")
            }
            intents_to_process.append(parsed)

        # Step 7: Fallback if ANY confidence is low
        if any(i["confidence"] < 0.6 for i in intents_to_process):
            raise ValueError("Low confidence in one or more intents")

    except Exception as e:
        logger.warning(f"LLM parsing failed or low confidence: {e}. Falling back to rule-based parser.")
        # 4. Fallback to Rule-based Parser (Step 7)
        intents_to_process = []
        if "task" in text.lower() and ("show" in text.lower() or "list" in text.lower() or "my" in text.lower() or "view" in text.lower()):
            intents_to_process.append({"intent": "query_tasks", "confidence": 0.8})
        elif "blocker" in text.lower() and ("show" in text.lower() or "list" in text.lower() or "current" in text.lower()):
            intents_to_process.append({"intent": "query_blockers", "confidence": 0.8})
        elif "ticket" in text.lower() and ("view" in text.lower() or "show" in text.lower()):
            intents_to_process.append({"intent": "view_tickets", "confidence": 0.8})
        elif "ticket" in text.lower() and ("raise" in text.lower() or "create" in text.lower()):
            intents_to_process.append({"intent": "create_ticket", "confidence": 0.8})
        elif "report" in text.lower() and ("get" in text.lower() or "show" in text.lower() or "generate" in text.lower()):
            intents_to_process.append({"intent": "request_report", "confidence": 0.8})
        elif "project" in text.lower() and "create" in text.lower():
            intents_to_process.append({"intent": "create_project", "confidence": 0.8})
        elif "project" in text.lower() and ("show" in text.lower() or "view" in text.lower() or "list" in text.lower()):
            intents_to_process.append({"intent": "view_projects", "confidence": 0.8})
        elif "task" in text.lower() and "create" in text.lower():
            intents_to_process.append({"intent": "create_task", "confidence": 0.8})
        elif "image" in text.lower() and ("add" in text.lower() or "upload" in text.lower()):
            intents_to_process.append({"intent": "add_image", "confidence": 0.8})
        elif "task" in text.lower() and re.search(r'task\s*\d+', text.lower()):
            intents_to_process.append({"intent": "get_task_detail", "task_reference": re.search(r'task\s*(\d+)', text.lower()).group(0), "confidence": 0.9})
        else:
            rule_parsed = rule_based_parse_message(text)
            if rule_parsed["confidence"] != "low":
                intents_to_process.append({
                    "intent": "task_update", # Default to task_update for rule-based
                    "task_name": f"{rule_parsed.get('project', '')} {rule_parsed.get('task_keyword', '')}".strip(),
                    "progress": rule_parsed.get("progress"),
                    "blocker_description": rule_parsed.get("blocker"),
                    "confidence": 0.8 # Manual boost for valid rule-based match
                })
            else:
                intents_to_process.append({"intent": "clarify", "confidence": 0})

    # 5. Intent Router / Handlers
    for parsed in intents_to_process:
        intent = parsed.get("intent")
        
        if intent == "task_update":
            await handlers.handle_task_update(parsed, user_id, context, send_reply_func, images=images)
        elif intent == "complete_task":
            await handlers.handle_complete_task(parsed, user_id, context, send_reply_func, images=images)
        elif intent == "add_blocker":
            await handlers.handle_add_blocker(parsed, user_id, context, send_reply_func, images=images)
        elif intent == "remove_blocker":
            await handlers.handle_remove_blocker(parsed, user_id, context, send_reply_func)
        elif intent == "add_image":
            await handlers.handle_add_image(parsed, user_id, context, send_reply_func, images=images)
        elif intent == "list_tasks" or intent == "query_tasks":
            await handlers.handle_query_tasks(parsed, user_id, context, send_reply_func)
        elif intent == "get_task_detail":
            await handlers.handle_get_task_detail(parsed, user_id, context, send_reply_func)
        elif intent == "query_blockers":
            await handlers.handle_query_blockers(parsed, user_id, context, send_reply_func)
        elif intent == "help" or intent == "greeting":
            await handlers.handle_greeting(parsed, user_id, context, send_reply_func)
        elif intent == "view_tickets":
            await handlers.handle_view_tickets(parsed, user_id, context, send_reply_func)
        elif intent == "reply_ticket":
            await handlers.handle_reply_ticket(parsed, user_id, context, send_reply_func)
        elif intent == "view_projects":
            await handlers.handle_view_projects(parsed, user_id, context, send_reply_func)
        elif intent == "edit_date":
            await handlers.handle_edit_date(parsed, user_id, context, send_reply_func)
        elif intent == "create_note":
            await handlers.handle_create_note(parsed, user_id, context, send_reply_func)
        elif intent == "request_report" or intent == "get_report":
            await handlers.handle_request_report(parsed, user_id, context, send_reply_func)
        elif intent == "create_project":
            await handlers.handle_create_project(parsed, user_id, context, send_reply_func)
        elif intent == "create_task":
            await handlers.handle_create_task(parsed, user_id, context, send_reply_func)
        elif intent == "create_ticket":
            await handlers.handle_create_ticket(parsed, user_id, context, send_reply_func)
        elif intent == "trigger_reminder_user":
            await handlers.handle_trigger_reminder_user(parsed, user_id, context, send_reply_func)
        elif intent == "clarify":
            await handlers.handle_clarify(parsed, user_id, context, send_reply_func)
        else:
            # Catch-all for other intents
            await handlers.handle_clarify(parsed, user_id, context, send_reply_func)


async def continue_conversation(text, user_id, state, images, send_reply_func):
    """Handles multi-step conversation flows based on stored state."""
    action = state.get("action")
    step = state.get("step")
    context = get_context(user_id)

    if action == "add_blocker":
        if step == "waiting_for_project":
            state["project_query"] = text
            
            projects = get_projects()
            match = resolve_project(text, projects)
            if match:
                update_context(user_id, active_project_id=match['id'])
                
            if state.get("task_query_pending"):
                t_name = state.get("task_query_pending")
                b_desc = state.get("blocker_description")
                if not b_desc:
                    state["step"] = "waiting_for_description"
                    state["task_query"] = t_name
                    set_state(user_id, state)
                    await send_reply_func(f"What is the issue holding up '{t_name}'?")
                else:
                    await handlers.perform_add_blocker(t_name, b_desc, user_id, send_reply_func)
                    clear_state(user_id)
                return

            state["step"] = "waiting_for_task"
            set_state(user_id, state)
            
            tasks = get_all_tasks()
            if match:
                p_tasks = [t for t in tasks if t.get('project_id') == match['id']]
            else:
                p_tasks = [t for t in tasks if t.get('projects') and text.lower() in t['projects']['name'].lower()]
                
            if not p_tasks:
                await send_reply_func("No pending tasks found for this project.")
                clear_state(user_id)
                return
            
            # Sort tasks to match show tasks order
            p_tasks.sort(key=lambda x: x.get('project_task_number', 999))
            tasks_msg = "\n".join([f"{idx + 1}. {t['name']}" for idx, t in enumerate(p_tasks)])
            state["_task_map"] = [t['name'] for t in p_tasks]
            set_state(user_id, state)
            await send_reply_func(f"Which task is blocked? (Type the number)\n\n{tasks_msg}")
        elif step == "waiting_for_task":
            t_map = state.get("_task_map", [])
            tq = resolve_task_from_list(text, [{"name": n} for n in t_map])
            t_name = tq['name'] if tq else text.strip()
            state["task_query"] = t_name
            state["step"] = "waiting_for_description"
            set_state(user_id, state)
            await send_reply_func(f"What is the issue holding up '{t_name}'?")
        elif step == "waiting_for_description":
            task_query = state.get("task_query")
            await handlers.perform_add_blocker(task_query, text, user_id, send_reply_func)
            clear_state(user_id)
    
    elif action == "remove_blocker":
        if step == "waiting_for_project":
            state["project_query"] = text
            
            projects = get_projects()
            match = resolve_project(text, projects)
            if match:
                update_context(user_id, active_project_id=match['id'])
                
            state["step"] = "waiting_for_task"
            set_state(user_id, state)
            
            tasks = get_all_tasks()
            if match:
                p_tasks = [t for t in tasks if t.get('is_blocked') and t.get('project_id') == match['id']]
            else:
                p_tasks = [t for t in tasks if t.get('is_blocked') and t.get('projects') and text.lower() in str(t.get('projects', {}).get('name', '')).lower()]
                
            if not p_tasks:
                await send_reply_func("No blocked tasks found for this project.")
                clear_state(user_id)
                return
            
            # Sort tasks to match show tasks order
            p_tasks.sort(key=lambda x: x.get('project_task_number', 999))
            tasks_msg = "\n".join([f"{idx + 1}. {t['name']}" for idx, t in enumerate(p_tasks)])
            state["_task_map"] = [t['name'] for t in p_tasks]
            set_state(user_id, state)
            await send_reply_func(f"Which task do you want to remove the blocker from? (Type the number)\n\n{tasks_msg}")

        elif step == "waiting_for_task":
            t_map = state.get("_task_map", [])
            if t_map:
                tq_obj = resolve_task_from_list(text, [{"name": n} for n in t_map])
                tq = tq_obj['name'] if tq_obj else text.strip()
            else:
                tq = text.strip()
            await handlers.perform_remove_blocker(tq, user_id, send_reply_func)
            # clear_state will be handled inside perform_remove_blocker if it sets a new state
        elif step == "waiting_for_resolve_choice":
            choice = text.strip().lower()
            if choice in ["all", "yes", "all resolved"]:
                remove_blocker(state['task_id'])
                await send_reply_func(f"All blockers resolved for '{state['task_name']}' 🟢")
                clear_state(user_id)
            elif choice.isdigit():
                idx = int(choice) - 1
                blockers = state.get('blockers', [])
                if 0 <= idx < len(blockers):
                    remove_blocker(state['task_id'])
                    await send_reply_func(f"Blocker '{blockers[idx]}' resolved. 🟢 (Task status set to unblocked)")
                    clear_state(user_id)
                else:
                    await send_reply_func("That didn't match — type the blocker number or 'All' to resolve everything.")
            else:
                await send_reply_func("Type 'All' to resolve everything, or the number of the specific blocker.")
    
    elif action == "add_image":
        if step == "waiting_for_project":
            state["project_query"] = text
            projects = get_projects()
            match = resolve_project(text, projects)
            if match:
                update_context(user_id, active_project_id=match['id'])
                
            state["step"] = "waiting_for_task"
            set_state(user_id, state)
            
            tasks = get_all_tasks()
            if match:
                p_tasks = [t for t in tasks if t.get('project_id') == match['id']]
            else:
                p_tasks = [t for t in tasks if t.get('projects') and text.lower() in t['projects']['name'].lower()]
                
            if not p_tasks:
                await send_reply_func("No pending tasks found for this project.")
                clear_state(user_id)
                return
            
            # Sort tasks to match show tasks order
            p_tasks.sort(key=lambda x: x.get('project_task_number', 999))
            tasks_msg = "\n".join([f"{idx + 1}. {t['name']}" for idx, t in enumerate(p_tasks)])
            state["_task_map"] = [t['name'] for t in p_tasks]
            set_state(user_id, state)
            await send_reply_func(f"Which task do you want to add an image to? (Type the number)\n\n{tasks_msg}")
        elif step == "waiting_for_task":
            t_map = state.get("_task_map", [])
            tq_obj = resolve_task_from_list(text, [{"name": n} for n in t_map])
            tq = tq_obj['name'] if tq_obj else text.strip()
            state["task_query"] = tq
            state["step"] = "waiting_for_proof"
            set_state(user_id, state)
            await send_reply_func(f"Please upload the image for '{tq}'. (This will replace any older images)")
        elif step == "waiting_for_proof":
            if images:
                if "collected_images" not in state: state["collected_images"] = []
                state["collected_images"].extend(images)
                set_state(user_id, state)
                await send_reply_func(f"Image received ({len(state['collected_images'])} total). Send more or type 'done' to finish.")
                return
            
            if text.strip().lower() == "done":
                collected = state.get("collected_images", [])
                if not collected:
                    await send_reply_func("You haven't uploaded any images yet. Please upload proof or type 'cancel'.")
                    return
                tq = state.get("task_query")
                await handlers.perform_add_image(tq, user_id, send_reply_func, images=collected)
                return
            
            await send_reply_func("Please upload an image as proof or type 'done' to finish.")
            

    elif action == "update_task":
        if step == "waiting_for_project":
            state["project_query"] = text
            
            projects = get_projects()
            match = resolve_project(text, projects)
            if match:
                update_context(user_id, active_project_id=match['id'])
                
            if state.get("task_query_pending"):
                t_name = state.get("task_query_pending")
                pr = state.get("progress")
                dl = state.get("deadline")
                if pr is None and not dl:
                    state["step"] = "waiting_for_progress"
                    state["task_query"] = t_name
                    set_state(user_id, state)
                    await send_reply_func(f"What is the progress % for '{t_name}'?")
                else:
                    await handlers.perform_update(t_name, pr, user_id, send_reply_func, deadline=dl)
                    clear_state(user_id)
                return

            state["step"] = "waiting_for_task"
            set_state(user_id, state)
            
            tasks = get_all_tasks()
            if match:
                p_tasks = [t for t in tasks if t.get('project_id') == match['id']]
            else:
                p_tasks = [t for t in tasks if t.get('projects') and text.lower() in t['projects']['name'].lower()]
                
            if not p_tasks:
                await send_reply_func("No pending tasks found for this project.")
                clear_state(user_id)
                return
            
            # Sort tasks to match show tasks order
            p_tasks.sort(key=lambda x: x.get('project_task_number', 999))
            tasks_msg = "\n".join([f"{idx + 1}. {t['name']}" for idx, t in enumerate(p_tasks)])
            state["_task_map"] = [t['name'] for t in p_tasks]
            set_state(user_id, state)
            await send_reply_func(f"Which task do you want to update? (Type the number)\n\n{tasks_msg}")
        elif step == "waiting_for_task":
            t_map = state.get("_task_map", [])
            tq_obj = resolve_task_from_list(text, [{"name": n} for n in t_map])
            tq = tq_obj['name'] if tq_obj else text.strip()
            state["task_query"] = tq
            state["step"] = "waiting_for_progress"
            set_state(user_id, state)
            await send_reply_func(f"What is the progress % for '{tq}'?")
        elif step == "waiting_for_progress":
            task_query = state.get("task_query")
            deadline = state.get("deadline")
            await handlers.perform_update(task_query, text, user_id, send_reply_func, deadline=deadline)
        elif step == "waiting_for_proof_choice":
            choice = text.strip().lower()
            tq = state.get("task_query")
            pr = state.get("progress", "100")
            dl = state.get("deadline")
            if choice in ["no", "n", "skip", "nope"]:
                await handlers.perform_update(tq, pr, user_id, send_reply_func, deadline=dl)
            elif choice in ["yes", "y", "yep", "ok", "sure"]:
                state["step"] = "waiting_for_proof"
                set_state(user_id, state)
                await send_reply_func(f"Please upload the image proof for '{tq}'.")
            else:
                await send_reply_func("Please reply with **Yes** to upload an image or **No** to complete without an image.")
        elif step == "waiting_for_proof":
            if images:
                if "collected_images" not in state: state["collected_images"] = []
                state["collected_images"].extend(images)
                set_state(user_id, state)
                await send_reply_func(f"Image received ({len(state['collected_images'])} total). Send more or type 'done' to finish.")
                return
                
            if text.strip().lower() == "done":
                collected = state.get("collected_images", [])
                tq = state.get("task_query")
                pr = state.get("progress", "100")
                dl = state.get("deadline")
                await handlers.perform_update(tq, pr, user_id, send_reply_func, images=collected, deadline=dl)
                return
                
            if text.strip().lower() in ["no", "skip"]:
                tq = state.get("task_query")
                pr = state.get("progress", "100")
                dl = state.get("deadline")
                await handlers.perform_update(tq, pr, user_id, send_reply_func, deadline=dl)
                return
            
            await send_reply_func("Please upload an image proof or type 'done' to finish.")
    
    elif action == "complete_task":
        if step == "waiting_for_project":
            state["project_query"] = text
            
            projects = get_projects()
            match = resolve_project(text, projects)
            if match:
                update_context(user_id, active_project_id=match['id'])
                
            if state.get("task_query_pending"):
                t_name = state.get("task_query_pending")
                state["step"] = "waiting_for_proof_choice"
                state["task_query"] = t_name
                set_state(user_id, state)
                await send_reply_func(f"Task '{t_name}' is marked as complete! ✅\nDo you want to upload a proof image? (Reply **Yes** or **No**)")
                return

            state["step"] = "waiting_for_task"
            set_state(user_id, state)
            
            tasks = get_all_tasks()
            if match:
                p_tasks = [t for t in tasks if t.get('project_id') == match['id']]
            else:
                p_tasks = [t for t in tasks if t.get('projects') and text.lower() in t['projects']['name'].lower()]
                
            if not p_tasks:
                await send_reply_func("No pending tasks found for this project.")
                clear_state(user_id)
                return
            
            # Sort tasks to match show tasks order
            p_tasks.sort(key=lambda x: x.get('project_task_number', 999))
            tasks_msg = "\n".join([f"{idx + 1}. {t['name']}" for idx, t in enumerate(p_tasks)])
            # Save task list natively into state for index matching next turn
            state["_task_map"] = [t['name'] for t in p_tasks]
            set_state(user_id, state)
            await send_reply_func(f"Which task should I complete? (You can type the number)\n\n{tasks_msg}")
            
        elif step == "waiting_for_task":
            t_map = state.get("_task_map", [])
            tq_obj = resolve_task_from_list(text, [{"name": n} for n in t_map])
            tq = tq_obj['name'] if tq_obj else text.strip()
            
            # Now ask for proof choice instead of finishing correctly
            state["task_query"] = tq
            state["step"] = "waiting_for_proof_choice"
            set_state(user_id, state)
            await send_reply_func(f"Task '{tq}' is marked as complete! ✅\nDo you want to upload a proof image? (Reply **Yes** or **No**)")
            
        elif step == "waiting_for_proof_choice":
            choice = text.strip().lower()
            tq = state.get("task_query")
            if choice in ["no", "n", "skip", "nope"]:
                state["step"] = "waiting_for_comment"
                state["collected_images"] = []
                set_state(user_id, state)
                await send_reply_func(f"Would you like to add a final comment or note for '{tq}'? 📝\n\nReply with your comment, or type **No** to skip.")
            elif choice in ["yes", "y", "yep", "ok", "sure"]:
                state["step"] = "waiting_for_proof"
                set_state(user_id, state)
                await send_reply_func(f"Please upload the image proof for '{tq}'.")
            else:
                await send_reply_func("Please reply with **Yes** to upload an image or **No** to skip image.")
                
        elif step == "waiting_for_proof":
            tq = state.get("task_query")
            if images:
                if "collected_images" not in state: state["collected_images"] = []
                state["collected_images"].extend(images)
                state["step"] = "waiting_for_comment"
                set_state(user_id, state)
                await send_reply_func(f"Image received! 📸\n\nWould you like to add a final comment or note for '{tq}'? 📝\n\nReply with your comment, or type **No** to skip.")
                return
                
            if text.strip().lower() in ["no", "skip", "done"]:
                state["step"] = "waiting_for_comment"
                set_state(user_id, state)
                await send_reply_func(f"Would you like to add a final comment or note for '{tq}'? 📝\n\nReply with your comment, or type **No** to skip.")
                return

            await send_reply_func("Please upload an image proof or type **No** to skip image.")

        elif step == "waiting_for_comment":
            comment = text.strip()
            tq = state.get("task_query")
            collected = state.get("collected_images", [])
            final_note = None if comment.lower() in ["no", "n", "skip", "none", "nope"] else comment
            
            await handlers.perform_update(tq, "100", user_id, send_reply_func, images=collected, note=final_note)
            clear_state(user_id)
            
    elif action == "get_task_detail":
        if step == "waiting_for_project":
            state["project_query"] = text
            projects = get_projects()
            match = resolve_project(text, projects)
            if match:
                update_context(user_id, active_project_id=match['id'])
                
            if state.get("task_query_pending"):
                t_name = state.get("task_query_pending")
                clear_state(user_id)
                await handlers.handle_get_task_detail({"task_reference": t_name}, user_id, context, send_reply_func)
                return
            clear_state(user_id)

    elif action == "create_ticket":
        if step == "waiting_for_project":
            state["project_query"] = text
            state["step"] = "waiting_for_description"
            set_state(user_id, state)
            await send_reply_func("What is the issue or concern?")
        elif step == "waiting_for_description":
            project_query = state.get("project_query", "")
            pq = project_query.strip()
            projects = get_projects()
            match = resolve_project(pq, projects)
                
            u_info = _resolve_user_ue(user_id)
            if not match:
                await send_reply_func(friendly_project_not_found(pq))
            elif not u_info:
                await send_reply_func("Your device isn't registered yet.\nPlease contact Kanav to get set up before raising tickets.")
            else:
                try:
                    create_ticket(u_info['id'], match['id'], message=text)
                    await send_reply_func(f"✅ Ticket raised for project '{match['name']}'.")
                except Exception as e:
                    logging.error(f"Error creating ticket: {e}")
                    await send_reply_func(friendly_system_error())
            clear_state(user_id)

    elif action == "create_project":
        if step == "waiting_for_name":
            u_info = _resolve_user_ue(user_id)
            uid = u_info['id'] if u_info else None
            create_project_db(text, created_by=uid)
            clear_state(user_id)
            await send_reply_func(f"Project '{text}' created successfully! ✅")

    elif action == "create_task":
        if step == "waiting_for_task_type":
            choice = text.strip().replace('.', '').strip()
            if choice == "1":
                # Personal task — use "Personal" project
                projects = get_projects()
                personal_proj = next((p for p in projects if p['name'].lower() == "personal"), None)
                if personal_proj:
                    state["project_query"] = personal_proj['name']
                else:
                    state["project_query"] = projects[0]['name'] if projects else ""
                state["is_personal"] = True
                state["step"] = "waiting_for_task_name"
                set_state(user_id, state)
                await send_reply_func("Enter task name:")
            elif choice == "2":
                # Team task — show project list
                projects = get_projects()
                if not projects:
                    await send_reply_func("No projects exist. Create a project first.")
                    clear_state(user_id)
                    return
                msg = "Select Project: (Type the number)\n\n"
                for i, p in enumerate(projects, 1):
                    msg += f"{i}. {p['name']}\n"
                state["step"] = "waiting_for_project"
                set_state(user_id, state)
                await send_reply_func(msg)
            else:
                await send_reply_func("Please enter 1 for Personal Task or 2 for Team Task.")
        elif step == "waiting_for_project":
            state["project_query"] = text
            state["step"] = "waiting_for_task_name"
            set_state(user_id, state)
            await send_reply_func("Enter task name:")
        elif step == "waiting_for_task_name":
            state["task_name"] = text
            state["step"] = "waiting_for_start_date"
            set_state(user_id, state)
            await send_reply_func("Start date (YYYY-MM-DD or NLP like tommorow or 10th April)")
        elif step == "waiting_for_start_date":
            # Parse start date
            try:
                parsed_start = parse_human_date(text)
            except Exception as e:
                logging.warning(f"Start date parsing failed for '{text}': {e}")
                parsed_start = text
            state["start_date"] = parsed_start
            state["step"] = "waiting_for_deadline"
            set_state(user_id, state)
            await send_reply_func("deadline YYYY-MM-DD or NLP like tommorow or 10th April")
        elif step == "waiting_for_deadline":
            project_query = state.get("project_query", "")
            task_name = state.get("task_name")
            start_date = state.get("start_date")
            creator_user_id = state.get("creator_user_id")  # WA: who created this task
            is_personal = state.get("is_personal", False)
            deadline = text
            pq = project_query.strip()
            projects = get_projects()
            match = resolve_project(pq, projects)
                
            if match:
                # Robust Human Date Parser
                try:
                    parsed_deadline = parse_human_date(deadline)
                except Exception as de:
                    logging.warning(f"Date parsing failed for '{deadline}': {de}")
                    parsed_deadline = deadline 
                
                try:
                    result = add_task(
                        match['id'],
                        task_name,
                        parsed_deadline,
                        start_date=start_date,
                        assigned_by=creator_user_id,
                        assigned_to=creator_user_id if is_personal else None,
                        task_type="PERSONAL" if is_personal else "PROJECT"
                    )
                except Exception as ae:
                    logging.error(f"Database error in add_task: {ae}")
                    result = None
                
                if result:
                    from core.utils import format_date_human
                    f_start = format_date_human(start_date)
                    f_dl = format_date_human(parsed_deadline)
                    await send_reply_func(f"task created successfully start date: {f_start} , deadline: {f_dl}")

                    # ── WhatsApp Task Assignment: Trigger ONLY if creator is Kanav ──
                    try:
                        _trigger_wa_task_assignment(
                            task_id=result['id'],
                            task_name=task_name,
                            project_name=match['name'],
                            due_date=f_dl,
                            creator_telegram_id=user_id,
                            creator_db_id=creator_user_id,
                        )
                    except Exception as wa_err:
                        logging.error(f"WA task assignment trigger error: {wa_err}")
                else:
                    await send_reply_func(f"Couldn't save '{task_name}' — please double-check the details and try again.\nTry: 'create task' to start over")
            else:
                await send_reply_func(friendly_project_not_found(project_query))
            clear_state(user_id)

    elif action == "edit_date":
        if step == "waiting_for_project":
            state["project_query"] = text
            projects = get_projects()
            match = resolve_project(text, projects)
            if match:
                update_context(user_id, active_project_id=match['id'])
            
            state["step"] = "waiting_for_task"
            set_state(user_id, state)
            
            tasks = get_all_tasks()
            if match:
                p_tasks = [t for t in tasks if t.get('project_id') == match['id']]
            else:
                p_tasks = [t for t in tasks if t.get('projects') and text.lower() in t['projects']['name'].lower()]
            
            if not p_tasks:
                await send_reply_func("No tasks found for this project.")
                clear_state(user_id)
                return
            
            # Sort tasks to match show tasks order
            p_tasks.sort(key=lambda x: x.get('project_task_number', 999))
            tasks_msg = "\n".join([f"{idx + 1}. {t['name']}" for idx, t in enumerate(p_tasks)])
            state["_task_map"] = [t['name'] for t in p_tasks]
            set_state(user_id, state)
            await send_reply_func(f"Which task do you want to edit? (Type the number)\n\n{tasks_msg}")
            
        elif step == "waiting_for_task":
            t_map = state.get("_task_map", [])
            tq_obj = resolve_task_from_list(text, [{"name": n} for n in t_map])
            tq = tq_obj['name'] if tq_obj else text.strip()
            
            tasks = get_all_tasks()
            full_task = next((t for t in tasks if t['name'] == tq), None)
            if not full_task:
                await send_reply_func(friendly_task_not_found(tq))
                return
                
            state["task_id"] = full_task['id']
            state["task_name"] = full_task['name']
            state["step"] = "waiting_for_date_type"
            set_state(user_id, state)
            await send_reply_func("What do you want to edit?\n1. Start Date\n2. Deadline")
            
        elif step == "waiting_for_date_type":
            choice = text.strip()
            if choice == "1":
                state["date_type"] = "start_date"
                state["step"] = "waiting_for_new_date"
                set_state(user_id, state)
                await send_reply_func(f"Enter new Start Date for '{state['task_name']}':")
            elif choice == "2":
                state["date_type"] = "deadline"
                state["step"] = "waiting_for_new_date"
                set_state(user_id, state)
                await send_reply_func(f"Enter new Deadline for '{state['task_name']}':")
            else:
                await send_reply_func("Please enter 1 or 2.")
                
        elif step == "waiting_for_new_date":
            # Parse and Update
            try:
                parsed_date = parse_human_date(text)
            except:
                parsed_date = text
                
            from db import update_task_dates
            dt = state.get("date_type")
            t_id = state.get("task_id")
            
            if dt == "start_date":
                result = update_task_dates(t_id, start_date=parsed_date)
            else:
                result = update_task_dates(t_id, deadline=parsed_date)
            
            if result:
                from core.utils import format_date_human
                f_start = format_date_human(result.get('planned_start_date') or result.get('created_at'))
                f_dl = format_date_human(result.get('deadline'))
                await send_reply_func(f"✅ Update saved!\nTask: {result['name']}\nStart Date: {f_start}\nDeadline: {f_dl}")
            else:
                await send_reply_func(friendly_system_error())
            clear_state(user_id)

    elif action == "create_note":
        if step == "waiting_for_project":
            state["project_query"] = text
            projects = get_projects()
            match = resolve_project(text, projects)
            if match:
                update_context(user_id, active_project_id=match['id'])
            
            state["step"] = "waiting_for_task"
            set_state(user_id, state)
            
            tasks = get_all_tasks()
            if match:
                p_tasks = [t for t in tasks if t.get('project_id') == match['id']]
            else:
                p_tasks = [t for t in tasks if t.get('projects') and text.lower() in t['projects']['name'].lower()]
            
            if not p_tasks:
                await send_reply_func("No tasks found for this project.")
                clear_state(user_id)
                return
            
            # Sort tasks to match show tasks order
            p_tasks.sort(key=lambda x: x.get('project_task_number', 999))
            tasks_msg = "\n".join([f"{idx + 1}. {t['name']}" for idx, t in enumerate(p_tasks)])
            state["_task_map"] = [t['name'] for t in p_tasks]
            set_state(user_id, state)
            await send_reply_func(f"Select Task to add a note: (Type the number)\n\n{tasks_msg}")
            
        elif step == "waiting_for_task":
            t_map = state.get("_task_map", [])
            tq_obj = resolve_task_from_list(text, [{"name": n} for n in t_map])
            tq = tq_obj['name'] if tq_obj else text.strip()
            
            tasks = get_all_tasks()
            full_task = next((t for t in tasks if t['name'] == tq), None)
            if not full_task:
                await send_reply_func(friendly_task_not_found(tq))
                return
                
            state["task_id"] = full_task['id']
            state["task_name"] = full_task['name']
            state["step"] = "waiting_for_note_content"
            set_state(user_id, state)
            await send_reply_func(f"Enter Note to be added for '{full_task['name']}':")
            
        elif step == "waiting_for_note_content":
            # Save Note
            from db import save_note
            t_id = state.get("task_id")
            t_name = state.get("task_name")
            
            # Need to ensure there is at least one update to attach the note to, or create a dummy update?
            # actually save_note searches for latest update.
            # to be safe, we should create a manual update if none exists or just save_note
            success = save_note(t_id, text)
            if not success:
                # Create a placeholder update to hold the note
                from db import save_update
                u_info = _resolve_user_ue(user_id)
                save_update(t_id, 0, "None", [], u_info['id'] if u_info else None)
                save_note(t_id, text)
                
            await send_reply_func(f"✅ Note successfully added to *{t_name}*")
            clear_state(user_id)

    elif action == "clarify":
        if step == "waiting_for_choice":
            clear_state(user_id)
            text_strip = text.strip().replace('.', '').strip()
            if text_strip == "1":
                await handlers.handle_task_update({}, user_id, context, send_reply_func)
            elif text_strip == "2":
                await handlers.handle_add_blocker({}, user_id, context, send_reply_func)
            elif text_strip == "3":
                await handlers.handle_complete_task({}, user_id, context, send_reply_func)
            elif text_strip == "4":
                await handlers.handle_query_tasks({}, user_id, context, send_reply_func)
            else:
                await send_reply_func("That didn't match any option — try typing the number (1, 2, 3, or 4).")

    elif action == "disambiguate_update":
        if step == "waiting_for_choice":
            choice = text.strip().replace('.', '').strip()
            options = state.get("task_options", [])
            names = state.get("task_names", [])
            
            if choice.isdigit() and 1 <= int(choice) <= len(options):
                idx = int(choice) - 1
                task_id = options[idx]
                task_name = names[idx]
                progress_str = state.get("progress_str")
                deadline = state.get("deadline")
                img = state.get("images", [])
                clear_state(user_id)
                
                # Find the full task object
                tasks = get_all_tasks()
                match = next((t for t in tasks if t['id'] == task_id), None)
                if match:
                    try:
                        if progress_str is not None:
                            m = re.search(r'(\d+)', str(progress_str))
                            progress = int(m.group(1)) if m else (match.get('progress', 0) or 0)
                        else:
                            progress = match.get('progress', 0) or 0
                    except:
                        progress = match.get('progress', 0) or 0
                    
                    u_info = _resolve_user_ue(user_id)
                    emp_uuid = u_info['id'] if u_info else None
                    save_update(match['id'], progress, "None", img, emp_uuid, new_deadline=deadline)
                    update_context(user_id, task_id=match['id'], task_name=match['name'], last_command="update_task")
                    set_state(user_id, {"action": "task_update", "task_id": match['id'], "task_name": match['name']})
                    
                    dl_msg = f"\nDeadline: {deadline}" if deadline else ""
                    await send_reply_func(f"Update saved ✅\nTask: {match['name']}\nProgress: {progress}%{dl_msg}")
                else:
                    await send_reply_func("Task not found — please try again.")
            else:
                await send_reply_func(f"Please reply with a number between 1 and {len(options)}.")

    elif action == "disambiguate_blocker":
        if step == "waiting_for_choice":
            choice = text.strip().replace('.', '').strip()
            options = state.get("task_options", [])
            names = state.get("task_names", [])
            
            if choice.isdigit() and 1 <= int(choice) <= len(options):
                idx = int(choice) - 1
                task_id = options[idx]
                task_name = names[idx]
                description = state.get("description", "")
                img = state.get("images", [])
                clear_state(user_id)
                
                tasks = get_all_tasks()
                match = next((t for t in tasks if t['id'] == task_id), None)
                if match:
                    add_blocker(match['id'], description)
                    u_info = _resolve_user_ue(user_id)
                    save_update(match['id'], match.get('progress', 0), description, img, u_info['id'] if u_info else None)
                    update_context(user_id, task_id=match['id'], task_name=match['name'], last_command="add_blocker")
                    await send_reply_func(f"Blocker added successfully 🛑\nTask: {match['name']}\nIssue: {description}")
                else:
                    await send_reply_func("Task not found — please try again.")
            else:
                await send_reply_func(f"Please reply with a number between 1 and {len(options)}.")

    elif action == "voice_batch_image_confirm":
        if step == "waiting_for_choice":
            choice = text.strip().lower().replace('.', '').strip()
            task_ids = state.get("completed_task_ids", [])
            task_names = state.get("completed_task_names", [])
            
            if choice in ["1", "yes", "y", "haan", "ha"]:
                # Enter image upload state for the completed tasks
                clear_state(user_id)
                set_state(user_id, {
                    "action": "voice_batch_image_upload",
                    "step": "waiting_for_image",
                    "completed_task_ids": task_ids,
                    "completed_task_names": task_names,
                })
                names = ", ".join(task_names)
                await send_reply_func(
                    f"📸 Send the proof image(s) for: *{names}*\n"
                    f"(Send as a photo attachment)"
                )
            elif choice in ["2", "no", "n", "nahi", "nhi"]:
                clear_state(user_id)
                await send_reply_func("✅ Tasks marked complete without proof images.")
            else:
                await send_reply_func("Reply with *1* (Yes) or *2* (No).")

    elif action == "voice_batch_image_upload":
        if step == "waiting_for_image":
            if images:
                task_ids = state.get("completed_task_ids", [])
                task_names = state.get("completed_task_names", [])
                for tid in task_ids:
                    try:
                        update_task_image(tid, images[0])
                    except Exception as img_err:
                        logging.error(f"Image save error for task {tid}: {img_err}")
                clear_state(user_id)
                names = ", ".join(task_names)
                await send_reply_func(f"📸 Proof image saved for: *{names}* ✅")
            else:
                await send_reply_func("Please send a photo attachment, or type *skip* to finish without images.")
                if text.strip().lower() in ["skip", "cancel", "no"]:
                    clear_state(user_id)
                    await send_reply_func("✅ Completed without proof images.")

    elif action == "task_update":
        # Follow-up detection (Step 2)
        if not state.get("awaiting_note_confirmation"):
            # Check for command or project mention (Step 8: Safety)
            msg_lower = text.lower()
            COMMAND_KEYWORDS = ["show tasks", "list tasks", "view tasks", "show projects", "/", "update task", "complete task", "add blocker", "raise ticket"]
            
            proj_match = resolve_project(text, get_projects())
            
            # Step 8 check: If mentions "task 1" or similar, it's not a note
            is_task_reference = re.search(r'task\s*\d+', msg_lower)
            
            if any(cmd in msg_lower for cmd in COMMAND_KEYWORDS) or is_task_reference or (proj_match and proj_match['name'].lower() != state.get('task_name', '').lower()):
                clear_state(user_id)
                # Re-handle this as a base message
                await handle_message(text, user_id, images, send_reply_func)
                return
            
            # Treat as potential note
            state["pending_note"] = text
            state["awaiting_note_confirmation"] = True
            set_state(user_id, state)
            
            # Ask for confirmation (Step 3)
            task_name = state.get("task_name", "the recently updated task")
            await send_reply_func(f"Do you want to add this as a note for task: *{task_name}*?\n(Reply **Yes** or **No**)")
        else:
            # Handle confirmation (Step 4)
            choice = text.strip().lower()
            task_id = state.get("task_id")
            task_name = state.get("task_name", "task")
            note_content = state.get("pending_note")
            
            if choice in ["yes", "yep", "sure", "ok", "y"]:
                # Save note to DB
                save_note(task_id, note_content)
                await send_reply_func(f"📝 Note successfully added to *{task_name}*")
                clear_state(user_id)
            elif choice in ["no", "n", "cancel", "don't"]:
                await send_reply_func("❌ Note was not added")
                clear_state(user_id)
            else:
                await send_reply_func("Please reply with **Yes** or **No** to confirm the note.")

# Legacy support for process_update_message (if still needed by some parts)
async def process_update_message(text: str, user_id: int, images: list, send_reply_func):
    await handle_message(text, user_id, images, send_reply_func)


# ─────────────────────────────────────────────────────────────────────────────
# WhatsApp Task Assignment Trigger (called after successful task creation)
# ─────────────────────────────────────────────────────────────────────────────

def _trigger_wa_task_assignment(task_id: str, task_name: str, project_name: str,
                                 due_date: str, creator_telegram_id: int,
                                 creator_db_id=None):
    """
    Fires the WhatsApp task assignment flow ONLY when the creator is Kanav.
    Called synchronously from the create_task flow after DB insert succeeds.

    Looks up:
      - Creator's DB record (by telegram_id if creator_db_id missing)
      - Kanav's WhatsApp number
      - Asif's WhatsApp number (first assigned-to user found for this task)
    """
    import logging as _log
    try:
        from db import get_user_by_telegram_id, get_user_by_name, supabase
        from whatsapp.task_assignment import on_task_created_by_kanav

        # 1. Resolve creator
        if creator_db_id:
            from db import get_user_by_id
            creator = get_user_by_id(creator_db_id)
        else:
            creator = get_user_by_telegram_id(creator_telegram_id)

        if not creator:
            _log.warning("WA trigger: could not resolve creator — skipping")
            return

        # 2. STRICT: only proceed if creator is Kanav
        if creator.get("name", "").strip().lower() != "kanav":
            _log.info(f"WA trigger: creator '{creator.get('name')}' is not Kanav — skipping")
            return

        kanav_wa = creator.get("whatsapp_number")
        if not kanav_wa:
            _log.warning("WA trigger: Kanav has no whatsapp_number — skipping")
            return

        # 3. Find the assigned user for this task
        task_res = supabase.table("tasks").select(
            "assigned_to, assigned_to_user:users!assigned_to(name, whatsapp_number)"
        ).eq("id", task_id).execute()

        if not task_res.data:
            _log.warning(f"WA trigger: task {task_id} not found after insert — skipping")
            return

        task_row = task_res.data[0]
        assignee = task_row.get("assigned_to_user") or {}
        if isinstance(assignee, list):
            assignee = assignee[0] if assignee else {}

        assignee_wa = assignee.get("whatsapp_number")
        assignee_name = assignee.get("name", "the assignee")

        if not assignee_wa:
            _log.warning(f"WA trigger: assigned user has no whatsapp_number — notifying Kanav only")
            from whatsapp.task_assignment import send_text
            send_text(kanav_wa, f"✅ Task Created.\n⚠️ {assignee_name} has no WhatsApp number registered. Please notify manually.")
            return

        # 4. Fire the assignment message
        on_task_created_by_kanav(
            task_id=task_id,
            task_name=task_name,
            project_name=project_name,
            due_date=due_date,
            creator_wa=kanav_wa,
            assignee_wa=assignee_wa,
            kanav_wa=kanav_wa,
        )

    except Exception as e:
        import logging as _log2
        _log2.error(f"_trigger_wa_task_assignment failed: {e}", exc_info=True)

