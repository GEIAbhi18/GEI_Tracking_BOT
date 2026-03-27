import logging
import json
import requests
from typing import List, Dict, Optional
from config import GEMINI_API_KEY, OPENROUTER_API_KEY, GROQCLOUD_API_KEY, LLM_PROVIDER
from core.schemas import IntentResponse

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are an AI assistant for a construction task management system.

ROLE:
You classify user messages into intents and extract structured data.

INSTRUCTIONS:
* Identify the user intent
* Extract all relevant entities
* Return structured JSON only

ALLOWED INTENTS:
* task_update: For progress updates (e.g., "60% done")
* complete_task: To mark a task as finished
* add_blocker: To report a new blocker/issue
* remove_blocker: To resolve an existing blocker
* query_tasks: To list, find, or search tasks. Use this for ALL task listing requests by date, status, or blockers.
* query_blockers: To see current blockers
* greeting: For simple greetings
* create_task: For adding new tasks
* create_project: For adding new projects
* create_ticket: For raising issues
* view_projects: For listing projects
* view_tickets: For showing open tickets
* trigger_reminder_user: To manually ping a user for updates (e.g., "ask asif", "send updates to asif")
* help: For assistance

FILTER RULES:
* range: MUST be one of "overdue", "today", "tomorrow", "this_week", "custom_range", or "all" (default)
* status: MUST be one of "pending", "completed", or "all" (default)
* Use "pending" for: "ongoing", "in progress", "incomplete", "unfinished"
* Use "completed" for: "finished", "done", "closed", "marked as complete"
* Use "overdue" for: "delayed", "late", "behind schedule"

FEW-SHOT EXAMPLES:
Example 1:
User: "complete task 2"
Output: {"intent": "complete_task", "task_reference": "task 2", "confidence": 0.95}

Example 2:
User: "add blocker no material found"
Output: {"intent": "add_blocker", "blocker_text": "no material found", "confidence": 0.9}

Example 3:
User: "Top Terrace waterproofing 60%"
Output: {"intent": "task_update", "project_name": "Top Terrace", "progress": 60, "confidence": 0.92}

Example 4:
User: "show my tasks"
Output: {"intent": "query_tasks", "confidence": 0.98, "query_filters": {"range": "all", "status": "pending"}}

Example 5:
User: "overdue tasks with blockers"
Output: {"intent": "query_tasks", "confidence": 0.95, "query_filters": {"range": "overdue", "has_blockers": true}}

Example 6:
User: "show completed tasks"
Output: {"intent": "query_tasks", "confidence": 0.95, "query_filters": {"range": "all", "status": "completed"}}

Example 7:
User: "which tasks are in progress"
Output: {"intent": "query_tasks", "confidence": 0.95, "query_filters": {"range": "all", "status": "pending"}}

Example 8:
User: "show tasks from 10 Mar to 25 Mar"
Output: {"intent": "query_tasks", "confidence": 0.98, "query_filters": {"range": "custom_range", "start_date": "10 Mar", "end_date": "25 Mar"}}

Example 9:
User: "show tasks due today"
Output: {"intent": "query_tasks", "confidence": 0.95, "query_filters": {"range": "today"}}

Example 10:
User: "which tasks are blocked"
Output: {"intent": "query_tasks", "confidence": 0.95, "query_filters": {"range": "all", "has_blockers": true}}

Example 11:
User: "ask asif"
Output: {"intent": "trigger_reminder_user", "target_user": "Asif", "message_type": "task_update_reminder", "confidence": 0.98}

Example 12:
User: "ask asif for updates"
Output: {"intent": "trigger_reminder_user", "target_user": "Asif", "message_type": "task_update_reminder", "confidence": 0.98}

Example 13:
User: "send updates to asif"
Output: {"intent": "trigger_reminder_user", "target_user": "Asif", "message_type": "task_update_reminder", "confidence": 0.98}

OUTPUT FORMAT:
{
"intent": "intent_here",
"task_reference": "task name if any",
"project_name": "project name if any",
"target_user": "user name if any",
"message_type": "task_update_reminder if applicable",
"progress": null,
"blocker_text": "blocker text if any",
"confidence": 1.0,
"query_filters": {
  "range": "overdue|today|tomorrow|this_week|custom_range|all",
  "start_date": null,
  "end_date": null,
  "status": "pending|completed|all",
  "has_blockers": false
}
}
"""

def parse_with_llm(message: str, history: List[Dict] = None, state: Dict = None):
    # Construct context string
    context_str = ""
    if history:
        context_str += "\nRecent Conversation:\n"
        for msg in history[-5:]:
            role = "User" if msg.get('role') == 'user' else "Assistant"
            context_str += f"{role}: {msg.get('content')}\n"
    
    if state:
        context_str += f"\nCurrent State: {json.dumps(state)}\n"
    
    full_message = f"{context_str}\nCurrent Message: \"{message}\""

    provider = LLM_PROVIDER.lower()
    try:
        if provider == "gemini":
            result_json = _call_gemini(full_message, SYSTEM_PROMPT)
        elif provider == "openrouter":
            result_json = _call_openrouter(full_message, SYSTEM_PROMPT)
        elif provider == "groq":
            result_json = _call_groq(full_message, SYSTEM_PROMPT)
        else:
            logger.error(f"Unsupported LLM provider: {LLM_PROVIDER}")
            return {"intent": "clarify", "confidence": 0}

        # Pydantic Validation
        parsed = IntentResponse.model_validate(result_json)
        return parsed.model_dump()

    except Exception as e:
        logger.error(f"LLM parsing or validation failed: {str(e)}")
        return {"intent": "clarify", "confidence": 0}

def _call_groq(message, system_prompt):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQCLOUD_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.1-8b-instant", # Default Groq model
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0
    }
    
    response = requests.post(url, headers=headers, json=payload, timeout=10)
    response.raise_for_status()
    data = response.json()
    return json.loads(data['choices'][0]['message']['content'])

def _call_gemini(message, system_prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={GEMINI_API_KEY}"
    
    payload = {
        "contents": [{
            "parts": [{
                "text": f"{system_prompt}\n\nUser message: {message}"
            }]
        }],
        "generationConfig": {
            "response_mime_type": "application/json"
        }
    }
    
    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()
    data = response.json()
    
    content = data['candidates'][0]['content']['parts'][0]['text']
    return json.loads(content)

def _call_openrouter(message, system_prompt):
    url = "https://openrouter.ai/api/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "google/gemini-flash-1.5", # Or any other model
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message}
        ],
        "response_format": {"type": "json_object"}
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        content = data['choices'][0]['message']['content']
        return json.loads(content)
    except Exception as e:
        logger.error(f"OpenRouter API error: {e}")
        return {"intent": "unknown"}
