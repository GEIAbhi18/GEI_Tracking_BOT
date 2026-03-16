import json
import requests
import logging
from config import GEMINI_API_KEY, OPENROUTER_API_KEY, LLM_PROVIDER

logger = logging.getLogger(__name__)

def parse_with_llm(message: str):
    system_prompt = """
You are a task management assistant.

Convert user messages into structured JSON.

Allowed intents:
task_update
complete_task
add_blocker
remove_blocker
query_tasks
query_blockers
help
clarify
unknown

Return JSON only.

Schema:
{
"intent": "",
"task_id": "",
"task_name": "",
"progress": "",
"blocker_description": "",
"ticket_description": ""
}
"""

    if LLM_PROVIDER.lower() == "gemini":
        return _call_gemini(message, system_prompt)
    elif LLM_PROVIDER.lower() == "openrouter":
        return _call_openrouter(message, system_prompt)
    else:
        logger.error(f"Unsupported LLM provider: {LLM_PROVIDER}")
        return {"intent": "unknown"}

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
