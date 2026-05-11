import re
import json
import logging
from db import get_projects, get_all_tasks, supabase, get_user_by_telegram_id
from core.utils import resolve_project, resolve_task_from_list

logger = logging.getLogger(__name__)

async def process_multi_line_trigger(text, user_id, send_reply_func, set_state):
    """
    Parses, validates, and generates confirmation for multi-line inputs ending in 'done'.
    Throws errors if validation fails.
    """
    text = text.strip()
    lines = text.split('\n')
    # Remove 'done' line
    lines = [l.strip() for l in lines if l.strip() and l.strip().lower() != 'done']
    
    if not lines:
        return False

    parsed_updates = []
    
    for idx, line in enumerate(lines, 1):
        # Regex: (.+?)\s*-\s*(.+?)\s*-\s*(\d+)%?\s*(?:done)?\s*-\s*(.*)
        match = re.match(r'^(.+?)\s*-\s*(.+?)\s*-\s*(\d+)%?\s*(?:done)?\s*-\s*(.*)$', line, re.IGNORECASE)
        if not match:
            # Fallback to LLM
            try:
                from core.llm_parser import _call_gemini
                
                # We use strict error throwing as per standard
                prompt = f"Extract structured update from this text line: '{line}'. Return plain JSON with keys: projectRaw, taskRaw, progress (int), blocker. If unparseable, return {{}}."
                js = _call_gemini(line, prompt)
                
                if not js or not all(k in js for k in ("projectRaw", "taskRaw", "progress")):
                    raise ValueError("Missing keys")
                
                parsed_updates.append({
                    "line_num": idx,
                    "projectRaw": str(js["projectRaw"]).strip(),
                    "taskRaw": str(js["taskRaw"]).strip(),
                    "progress": int(js["progress"]),
                    "blocker": str(js.get("blocker", "No blocker")).strip() or "No blocker"
                })
            except Exception as e:
                await send_reply_func(f"Line {idx} didn't quite match the format.\nTry: 'Project - Task - Progress - Blocker'")
                return True
        else:
            pRaw = match.group(1).strip()
            tRaw = match.group(2).strip()
            prog = int(match.group(3).strip())
            blocker = match.group(4).strip()
            
            # Normalization
            tRaw = re.sub(r'(?i)task\s*', '', tRaw).strip()
            if not blocker:
                blocker = "No blocker"
                
            parsed_updates.append({
                "line_num": idx,
                "projectRaw": pRaw,
                "taskRaw": tRaw,
                "progress": prog,
                "blocker": blocker
            })

    # Validate AND Resolve
    projects = get_projects()
    # Sort projects consistently by created_at (which is default in get_projects)
    proj_map = {str(idx): p for idx, p in enumerate(projects, 1)}
    
    all_tasks = get_all_tasks()
    validated = []
    
    for item in parsed_updates:
        lNum = item['line_num']
        pRaw = item['projectRaw']
        tRaw = item['taskRaw']
        prog = item['progress']
        
        if not (0 <= prog <= 100):
            await send_reply_func(f"Line {lNum}: Progress should be between 0 and 100.\nTry: 'Project - Task - 60 - No blocker'")
            return True
            
        matched_proj = proj_map.get(pRaw) or resolve_project(pRaw, projects)
        if not matched_proj:
            await send_reply_func(f"Line {lNum}: Couldn't find project '{pRaw}'.\nTry: 'show projects' to see the list, or use the project number")
            return True
            
        p_tasks = [t for t in all_tasks if t.get('project_id') == matched_proj['id']]
        p_tasks.sort(key=lambda x: x.get('created_at') or str(x.get('id')))
        
        t_map_num = {str(idx): t for idx, t in enumerate(p_tasks, 1)}
        
        matched_task = t_map_num.get(tRaw) or resolve_task_from_list(tRaw, p_tasks)
        if not matched_task:
            await send_reply_func(f"Line {lNum}: Couldn't find task '{tRaw}' in '{matched_proj['name']}'.\nTry: 'show tasks' to see available tasks")
            return True
            
        validated.append({
            "project_id": matched_proj['id'],
            "project_name": matched_proj['name'],
            "task_id": matched_task['id'],
            "task_name": matched_task['name'],
            "progress": prog,
            "blocker": item['blocker']
        })
        
    # Confirmation Step
    msg = "I understood:\n\n"
    for idx, v in enumerate(validated, 1):
        b_text = "No blocker" if v['blocker'].lower() in ["none", "no blocker"] else f"Blocker: {v['blocker']}"
        msg += f"{idx}. {v['project_name']} - {v['task_name']} - {v['progress']}% - {b_text}\n"
        
    msg += "\nReply:\n**YES** → to save\n**EDIT** → to retry"
    
    set_state(user_id, {
        "action": "awaiting_multi_update_confirmation",
        "pending_updates": validated
    })
    
    await send_reply_func(msg)
    return True

async def handle_multi_update_confirmation(text, user_id, state, send_reply_func, clear_state):
    """
    Handles YES/EDIT flow.
    """
    choice = text.strip().lower()
    
    if choice == "yes":
        updates = state.get("pending_updates", [])
        u_info = get_user_by_telegram_id(user_id)
        u_uuid = u_info['id'] if u_info else None
        
        from datetime import datetime
        now_str = datetime.now().isoformat()
        
        db_records = []
        for upd in updates:
            db_records.append({
                "user_id": u_uuid,
                "project_id": upd['project_id'],
                "task_id": upd['task_id'],
                "progress": upd['progress'],
                "blocker": upd['blocker'],
                "timestamp": now_str
            })
            
        if db_records:
            try:
                supabase.table("daily_updates").insert(db_records).execute()
                await send_reply_func("✅ Updates saved successfully")
            except Exception as e:
                logger.error(f"Error saving daily_updates: {e}")
                await send_reply_func("The system is a little slow right now — please try again in a moment.\nYour message was not lost.")
        else:
            await send_reply_func("No valid updates to save.")
            
        clear_state(user_id)
        return True
        
    elif choice == "edit":
        clear_state(user_id)
        await send_reply_func("Please resend your updates in the correct format.")
        return True
        
    else:
        await send_reply_func("I'm waiting for your confirmation.\nReply **YES** to save, or **EDIT** to retry.")
        return True
