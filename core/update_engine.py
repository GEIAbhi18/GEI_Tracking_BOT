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
    if state:
        await continue_conversation(text, user_id, state, images, send_reply_func)
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
            "confidence": confidence
        }

        # Step 7: Fallback if confidence is low
        if confidence < 0.6:
            raise ValueError("Low confidence")

    except Exception as e:
        logger.warning(f"LLM parsing failed or low confidence: {e}. Falling back to rule-based parser.")
        # 4. Fallback to Rule-based Parser (Step 7)
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
        await handlers.handle_task_update(parsed, user_id, context, send_reply_func)
    elif intent == "complete_task":
        await handlers.handle_complete_task(parsed, user_id, context, send_reply_func)
    elif intent == "add_blocker":
        await handlers.handle_add_blocker(parsed, user_id, context, send_reply_func)
    elif intent == "remove_blocker":
        await handlers.handle_remove_blocker(parsed, user_id, context, send_reply_func)
    elif intent == "list_tasks" or intent == "query_tasks":
        await handlers.handle_query_tasks(parsed, user_id, context, send_reply_func)
    elif intent == "query_blockers":
        await handlers.handle_query_blockers(parsed, user_id, context, send_reply_func)
    elif intent == "help":
        await handlers.handle_help(parsed, user_id, context, send_reply_func)
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
        if step == "waiting_for_task":
            await handlers.handle_add_blocker({"task_name": text}, user_id, context, send_reply_func)
            # handle_add_blocker will set next state internally if needed
        elif step == "waiting_for_description":
            task_query = state.get("task_query")
            await handlers.perform_add_blocker(task_query, text, user_id, send_reply_func)
            clear_state(user_id)
    
    elif action == "remove_blocker":
        if step == "waiting_for_task":
            await handlers.perform_remove_blocker(text, user_id, send_reply_func)
            clear_state(user_id)
    
    elif action == "update_task":
        if step == "waiting_for_task":
            set_state(user_id, {"action": "update_task", "step": "waiting_for_progress", "task_query": text})
            await send_reply_func(f"What is the progress % for '{text}'?")
        elif step == "waiting_for_progress":
            task_query = state.get("task_query")
            await handlers.perform_update(task_query, text, user_id, send_reply_func)
            clear_state(user_id)
    
    elif action == "complete_task":
        if step == "waiting_for_task":
            await handlers.perform_update(text, "100", user_id, send_reply_func)
            clear_state(user_id)

    elif action == "create_ticket":
        if step == "waiting_for_project":
            state["project_query"] = text
            state["step"] = "waiting_for_description"
            set_state(user_id, state)
            await send_reply_func("What is the issue or concern?")
        elif step == "waiting_for_description":
            project_query = state.get("project_query")
            # Logic for creating ticket (can be moved to handlers too)
            projects = get_projects()
            match = next((p for p in projects if project_query.lower() in p['name'].lower()), None)
            u_info = get_user_by_telegram_id(user_id)
            if match and u_info:
                create_ticket(u_info['id'], match['id'], message=text)
                await send_reply_func(f"✅ Ticket raised for project '{match['name']}'.")
            else:
                await send_reply_func("Failed to create ticket. Project not found.")
            clear_state(user_id)

# Legacy support for process_update_message (if still needed by some parts)
async def process_update_message(text: str, user_id: int, images: list, send_reply_func):
    await handle_message(text, user_id, images, send_reply_func)
