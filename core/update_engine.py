import logging
import json
from core.llm_parser import parse_with_llm
from core.conversation_state import get_state, set_state, clear_state
from core.context_manager import get_context, update_context
from core.message_parser import parse_message as rule_based_parse_message
import core.intent_handlers as handlers
from db import get_all_tasks, get_projects, get_user_by_telegram_id, create_ticket

logger = logging.getLogger(__name__)

async def handle_message(text: str, user_id: int, images: list, send_reply_func):
    """
    Main message handler implementing the audit-compliant architecture:
    State -> LLM -> Intent Handlers -> Fallback
    """
    
    # Update context with raw message
    update_context(user_id, message=text)
    context = get_context(user_id)

    # 1. Check for command mode (bypass LLM/State)
    if text.startswith('/'):
        # Handled by telegram_adapter CommandHandlers
        return

    # 2. Check Conversation State
    state = get_state(user_id)
    stripped_lower = text.strip().lower()

    # Pre-intercept "state-breakers" - If user types a clear top-level command, break any existing loop
    COMMAND_KEYWORDS = ["/start", "show tasks", "view tasks", "list tasks", "show blockers", "help", "/help", "exit", "cancel"]
    if state and any(cmd in stripped_lower for cmd in COMMAND_KEYWORDS):
        clear_state(user_id)
        state = None # Fall through to LLM/Router

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
        await handlers.handle_ask_asif({}, user_id, context, send_reply_func)
        return

    if stripped_lower in ["complete task", "/complete_task"]:
        await handlers.handle_complete_task({"intent": "complete_task"}, user_id, context, send_reply_func)
        return
    elif stripped_lower in ["show tasks", "/show_tasks", "show my tasks", "list tasks", "/list_tasks", "view tasks"]:
        await handlers.handle_query_tasks({"intent": "query_tasks"}, user_id, context, send_reply_func)
        return
    elif stripped_lower in ["show blockers", "/show_blockers", "show me blockers"]:
        await handlers.handle_query_blockers({"intent": "query_blockers"}, user_id, context, send_reply_func)
        return
    elif stripped_lower in ["create project", "/create_project"]:
        await handlers.handle_create_project({"intent": "create_project"}, user_id, context, send_reply_func)
        return
    elif stripped_lower in ["create task", "/create_task"]:
        await handlers.handle_create_task({"intent": "create_task"}, user_id, context, send_reply_func)
        return
    elif stripped_lower in ["update task", "/update_task"]:
        await handlers.handle_task_update({"intent": "task_update"}, user_id, context, send_reply_func)
        return
    elif stripped_lower in ["raise ticket", "/raise_ticket", "create ticket", "/create_ticket"]:
        await handlers.handle_create_ticket({"intent": "create_ticket"}, user_id, context, send_reply_func)
        return
    elif stripped_lower in ["view tickets", "/view_tickets", "show tickets", "/show_tickets"]:
        await handlers.handle_view_tickets({"intent": "view_tickets"}, user_id, context, send_reply_func)
        return
    elif stripped_lower in ["get report", "/get_report", "request report", "/request_report"]:
        await handlers.handle_request_report({"intent": "request_report"}, user_id, context, send_reply_func)
        return
    elif stripped_lower in ["hello", "hi", "hey", "greetings", "start", "/start", "help", "/help"]:
        await handlers.handle_greeting({"intent": "greeting"}, user_id, context, send_reply_func)
        return
        
    # 3. LLM Intent Parser
    try:
        # Prepare history for LLM context
        history = [{"role": "user", "content": m} for m in context.get("messages", [])[:-1]]
        
        parsed_obj = parse_with_llm(text, history=history, state=state)
        intent = parsed_obj.get("intent", "clarify")
        confidence = parsed_obj.get("confidence", 0)

        # Mapping new schema to existing handler keys
        parsed = {
            "intent": intent,
            "task_name": parsed_obj.get("task_reference") or parsed_obj.get("project_name"),
            "progress": parsed_obj.get("progress"),
            "blocker_description": parsed_obj.get("blocker_text"),
            "confidence": confidence,
            "query_filters": parsed_obj.get("query_filters")
        }

        # Step 7: Fallback if confidence is low
        if confidence < 0.6:
            raise ValueError("Low confidence")

    except Exception as e:
        logger.warning(f"LLM parsing failed or low confidence: {e}. Falling back to rule-based parser.")
        # 4. Fallback to Rule-based Parser (Step 7)
        if "task" in text.lower() and ("show" in text.lower() or "list" in text.lower() or "my" in text.lower() or "view" in text.lower()):
            intent = "query_tasks"
            parsed = {"intent": "query_tasks", "confidence": 0.8}
        elif "blocker" in text.lower() and ("show" in text.lower() or "list" in text.lower() or "current" in text.lower()):
            intent = "query_blockers"
            parsed = {"intent": "query_blockers", "confidence": 0.8}
        elif "ticket" in text.lower() and ("view" in text.lower() or "show" in text.lower()):
            intent = "view_tickets"
            parsed = {"intent": "view_tickets", "confidence": 0.8}
        elif "ticket" in text.lower() and ("raise" in text.lower() or "create" in text.lower()):
            intent = "create_ticket"
            parsed = {"intent": "create_ticket", "confidence": 0.8}
        elif "report" in text.lower() and ("get" in text.lower() or "show" in text.lower() or "generate" in text.lower()):
            intent = "request_report"
            parsed = {"intent": "request_report", "confidence": 0.8}
        elif "project" in text.lower() and "create" in text.lower():
            intent = "create_project"
            parsed = {"intent": "create_project", "confidence": 0.8}
        elif "project" in text.lower() and ("show" in text.lower() or "view" in text.lower() or "list" in text.lower()):
            intent = "view_projects"
            parsed = {"intent": "view_projects", "confidence": 0.8}
        elif "task" in text.lower() and "create" in text.lower():
            intent = "create_task"
            parsed = {"intent": "create_task", "confidence": 0.8}
        else:
            rule_parsed = rule_based_parse_message(text)
            if rule_parsed["confidence"] != "low":
                parsed = {
                    "intent": "task_update", # Default to task_update for rule-based
                    "task_name": f"{rule_parsed.get('project', '')} {rule_parsed.get('task_keyword', '')}".strip(),
                    "progress": rule_parsed.get("progress"),
                    "blocker_description": rule_parsed.get("blocker"),
                    "confidence": 0.8 # Manual boost for valid rule-based match
                }
                intent = "task_update"
            else:
                intent = "clarify"
                parsed = {"intent": "clarify", "confidence": 0}

    # 5. Intent Router / Handlers
    if intent == "task_update":
        await handlers.handle_task_update(parsed, user_id, context, send_reply_func, images=images)
    elif intent == "complete_task":
        await handlers.handle_complete_task(parsed, user_id, context, send_reply_func, images=images)
    elif intent == "add_blocker":
        await handlers.handle_add_blocker(parsed, user_id, context, send_reply_func, images=images)
    elif intent == "remove_blocker":
        await handlers.handle_remove_blocker(parsed, user_id, context, send_reply_func)
    elif intent == "list_tasks" or intent == "query_tasks":
        await handlers.handle_query_tasks(parsed, user_id, context, send_reply_func)
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
    elif intent == "request_report" or intent == "get_report":
        await handlers.handle_request_report(parsed, user_id, context, send_reply_func)
    elif intent == "create_project":
        await handlers.handle_create_project(parsed, user_id, context, send_reply_func)
    elif intent == "create_task":
        await handlers.handle_create_task(parsed, user_id, context, send_reply_func)
    elif intent == "create_ticket":
        await handlers.handle_create_ticket(parsed, user_id, context, send_reply_func)
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
            state["step"] = "waiting_for_task"
            set_state(user_id, state)
            
            projects = get_projects()
            match = None
            pq = text.strip()
            if pq.isdigit() and 0 <= int(pq) - 1 < len(projects):
                match = projects[int(pq) - 1]
            else:
                match = next((p for p in projects if pq.lower() in p['name'].lower()), None)
                
            tasks = get_all_tasks()
            if match:
                p_tasks = [t for t in tasks if t['status'] != 'completed' and t.get('project_id') == match['id']]
            else:
                p_tasks = [t for t in tasks if t['status'] != 'completed' and t.get('projects') and pq.lower() in t['projects']['name'].lower()]
                
            if not p_tasks:
                await send_reply_func("No pending tasks found for this project.")
                clear_state(user_id)
                return
                
            tasks_msg = "\n".join([f"{idx + 1}. {t['name']}" for idx, t in enumerate(p_tasks)])
            state["_task_map"] = [t['name'] for t in p_tasks]
            set_state(user_id, state)
            await send_reply_func(f"Which task is blocked? (Type the number)\n\n{tasks_msg}")
        elif step == "waiting_for_task":
            t_map = state.get("_task_map", [])
            tq = text.strip()
            if tq.isdigit() and 0 <= int(tq) - 1 < len(t_map):
                tq = t_map[int(tq) - 1]
            state["task_query"] = tq
            state["step"] = "waiting_for_description"
            set_state(user_id, state)
            await send_reply_func(f"What is the issue holding up '{tq}'?")
        elif step == "waiting_for_description":
            task_query = state.get("task_query")
            await handlers.perform_add_blocker(task_query, text, user_id, send_reply_func)
            clear_state(user_id)
    
    elif action == "remove_blocker":
        if step == "waiting_for_task":
            await handlers.perform_remove_blocker(text, user_id, send_reply_func)
            clear_state(user_id)
    
    elif action == "update_task":
        if step == "waiting_for_project":
            state["project_query"] = text
            state["step"] = "waiting_for_task"
            set_state(user_id, state)
            
            projects = get_projects()
            match = None
            pq = text.strip()
            if pq.isdigit() and 0 <= int(pq) - 1 < len(projects):
                match = projects[int(pq) - 1]
            else:
                match = next((p for p in projects if pq.lower() in p['name'].lower()), None)
                
            tasks = get_all_tasks()
            if match:
                p_tasks = [t for t in tasks if t['status'] != 'completed' and t.get('project_id') == match['id']]
            else:
                p_tasks = [t for t in tasks if t['status'] != 'completed' and t.get('projects') and pq.lower() in t['projects']['name'].lower()]
                
            if not p_tasks:
                await send_reply_func("No pending tasks found for this project.")
                clear_state(user_id)
                return
                
            tasks_msg = "\n".join([f"{idx + 1}. {t['name']}" for idx, t in enumerate(p_tasks)])
            state["_task_map"] = [t['name'] for t in p_tasks]
            set_state(user_id, state)
            await send_reply_func(f"Which task do you want to update? (Type the number)\n\n{tasks_msg}")
        elif step == "waiting_for_task":
            t_map = state.get("_task_map", [])
            tq = text.strip()
            if tq.isdigit() and 0 <= int(tq) - 1 < len(t_map):
                tq = t_map[int(tq) - 1]
            state["task_query"] = tq
            state["step"] = "waiting_for_progress"
            set_state(user_id, state)
            await send_reply_func(f"What is the progress % for '{tq}'?")
        elif step == "waiting_for_progress":
            task_query = state.get("task_query")
            await handlers.perform_update(task_query, text, user_id, send_reply_func)
            clear_state(user_id)
    
    elif action == "complete_task":
        if step == "waiting_for_project":
            state["project_query"] = text
            state["step"] = "waiting_for_task"
            set_state(user_id, state)
            
            projects = get_projects()
            match = None
            pq = text.strip()
            if pq.isdigit() and 0 <= int(pq) - 1 < len(projects):
                match = projects[int(pq) - 1]
            else:
                match = next((p for p in projects if pq.lower() in p['name'].lower()), None)
                
            tasks = get_all_tasks()
            if match:
                p_tasks = [t for t in tasks if t['status'] != 'completed' and t.get('project_id') == match['id']]
            else:
                p_tasks = [t for t in tasks if t['status'] != 'completed' and t.get('projects') and pq.lower() in t['projects']['name'].lower()]
                
            if not p_tasks:
                await send_reply_func("No pending tasks found for this project.")
                clear_state(user_id)
                return
                
            tasks_msg = "\n".join([f"{idx + 1}. {t['name']}" for idx, t in enumerate(p_tasks)])
            # Save task list natively into state for index matching next turn
            state["_task_map"] = [t['name'] for t in p_tasks]
            set_state(user_id, state)
            await send_reply_func(f"Which task should I complete? (You can type the number)\n\n{tasks_msg}")
            
        elif step == "waiting_for_task":
            t_map = state.get("_task_map", [])
            tq = text.strip()
            if tq.isdigit() and 0 <= int(tq) - 1 < len(t_map):
                tq = t_map[int(tq) - 1]
            
            # Now ask for proof instead of finishing
            state["task_query"] = tq
            state["step"] = "waiting_for_proof"
            set_state(user_id, state)
            await send_reply_func(f"Please upload an image proof to mark '{tq}' as complete.")
            
        elif step == "waiting_for_proof":
            if not images:
                await send_reply_func("Please upload an actual image as proof.")
                return
            tq = state.get("task_query")
            await handlers.perform_update(tq, "100", user_id, send_reply_func, images=images)
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
            if pq.isdigit() and 0 <= int(pq) - 1 < len(projects):
                match = projects[int(pq) - 1]
            else:
                match = next((p for p in projects if pq.lower() in p['name'].lower()), None)
                
            u_info = get_user_by_telegram_id(user_id)
            if not match:
                await send_reply_func("Failed to create ticket. Project not found.")
            elif not u_info:
                await send_reply_func(f"Employee/User with Telegram ID {user_id} not found in database. Please contact admin to register your device before raising tickets.")
            else:
                create_ticket(u_info['id'], match['id'], message=text)
                await send_reply_func(f"✅ Ticket raised for project '{match['name']}'.")
            clear_state(user_id)

    elif action == "create_project":
        if step == "waiting_for_name":
            from db import create_project_db
            u_info = get_user_by_telegram_id(user_id)
            uid = u_info['id'] if u_info else None
            create_project_db(text, created_by=uid)
            clear_state(user_id)
            await send_reply_func(f"Project '{text}' created successfully! ✅")

    elif action == "create_task":
        if step == "waiting_for_project":
            state["project_query"] = text
            state["step"] = "waiting_for_task_name"
            set_state(user_id, state)
            await send_reply_func("What is the name of the new task?")
        elif step == "waiting_for_task_name":
            state["task_name"] = text
            state["step"] = "waiting_for_deadline"
            set_state(user_id, state)
            await send_reply_func("What is the deadline for this task? (e.g. YYYY-MM-DD or tomorrow)")
        elif step == "waiting_for_deadline":
            project_query = state.get("project_query", "")
            task_name = state.get("task_name")
            deadline = text
            pq = project_query.strip()
            projects = get_projects()
            if pq.isdigit() and 0 <= int(pq) - 1 < len(projects):
                match = projects[int(pq) - 1]
            else:
                match = next((p for p in projects if pq.lower() in p['name'].lower()), None)
                
            if match:
                from db import add_task
                from datetime import datetime, timedelta
                
                # Simple Natural Language Date Parser
                parsed_deadline = deadline
                dl_lower = deadline.lower()
                today = datetime.now()
                
                if dl_lower == "today":
                    parsed_deadline = today.strftime("%Y-%m-%d")
                elif dl_lower == "tomorrow":
                    parsed_deadline = (today + timedelta(days=1)).strftime("%Y-%m-%d")
                elif "day" in dl_lower and ("from now" in dl_lower or "from today" in dl_lower):
                    import re
                    m = re.search(r'(\d+)', dl_lower)
                    if m:
                        days = int(m.group(1))
                        parsed_deadline = (today + timedelta(days=days)).strftime("%Y-%m-%d")
                
                result = add_task(match['id'], task_name, parsed_deadline)
                if result:
                    await send_reply_func(f"Task '{task_name}' created successfully for project '{match['name']}'! ✅")
                else:
                    await send_reply_func(f"Sorry, I couldn't save the task '{task_name}'. Please check the format and try again.")
            else:
                await send_reply_func("Failed to create task. Project not found.")
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
                await send_reply_func("Invalid choice. Please try again or rephrase your request.")

# Legacy support for process_update_message (if still needed by some parts)
async def process_update_message(text: str, user_id: int, images: list, send_reply_func):
    await handle_message(text, user_id, images, send_reply_func)
