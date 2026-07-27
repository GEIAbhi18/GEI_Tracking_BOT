from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY
from datetime import datetime, timedelta
import threading as _threading


class _LazySupabase:
    """Lazy-init wrapper: creates the Supabase client on first use instead of
    at import time, so gunicorn can bind the port without waiting for a
    network round-trip to Supabase during module import."""
    _client: Client = None
    _lock = _threading.Lock()

    def _init(self):
        if self._client is None:
            with self._lock:
                if self._client is None:  # double-checked locking
                    type(self)._client = create_client(SUPABASE_URL, SUPABASE_KEY)
        return self._client

    def __getattr__(self, name):
        return getattr(self._init(), name)


supabase: Client = _LazySupabase()  # type: ignore[assignment]

def _apply_project_task_numbers(tasks):
    if not tasks:
        return tasks
    from collections import defaultdict
    by_proj = defaultdict(list)
    for t in tasks:
        by_proj[t.get("project_id")].append(t)
    
    for pid, p_tasks in by_proj.items():
        # Sort by creation time or id (consistent ordering)
        p_tasks.sort(key=lambda x: x.get('created_at') or str(x.get('id')))
        for idx, t in enumerate(p_tasks):
            t['project_task_number'] = idx + 1
            if 'title' in t:
                t['name'] = t['title']
            
    return tasks

def get_projects():
    response = supabase.table("projects").select("*").order("created_at").execute()
    return response.data

def get_tasks_for_project(project_id):
    response = supabase.table("tasks").select("*").eq("project_id", project_id).execute()
    return _apply_project_task_numbers(response.data)

def get_all_tasks(user_id=None, include_personal=False):
    response = supabase.table("tasks").select("*, projects(name), assigned_to_user:users!assigned_to(name)").execute()
    tasks = _apply_project_task_numbers(response.data)
    
    filtered_tasks = []
    for t in tasks:
        if t.get('task_type') == 'PERSONAL':
            if not include_personal and not user_id:
                continue
            if user_id and str(t.get('created_by')) != str(user_id) and str(t.get('assigned_to')) != str(user_id) and str(t.get('assigned_by')) != str(user_id):
                continue
        filtered_tasks.append(t)
        
    return filtered_tasks


def save_update(task_id, progress, blockers, images, employee_id=None, new_deadline=None):
    from rag import calculate_rag
    
    try:
        progress = int(str(progress).replace('%', '').strip())
    except:
        progress = 0
        
    task_response = supabase.table("tasks").select("created_at, deadline, planned_start_date").eq("id", task_id).execute()
    task_data = task_response.data[0] if task_response.data else {}
    
    # Robust date parsing to prevent crashes
    try:
        # Priority: planned_start_date > created_at
        start_date_str = task_data.get("planned_start_date") or task_data.get("created_at")
        task_start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')) if start_date_str else None
    except:
        task_start_date = None
    
    # Use new deadline if provided, else use existing
    final_deadline_str = new_deadline if new_deadline else task_data.get("deadline")
    try:
        if final_deadline_str and " " in final_deadline_str and len(final_deadline_str) > 10:
            final_deadline_str = final_deadline_str.split(" ")[0]
        task_deadline = datetime.fromisoformat(final_deadline_str.replace('Z', '+00:00')) if final_deadline_str and len(str(final_deadline_str)) >= 10 else None
    except:
        task_deadline = None
    
    rag_color, _ = calculate_rag(progress, task_start_date, task_deadline, blockers, 0)
    
    data = {
        "task_id": task_id,
        "progress": progress,
        "blockers": blockers,
        "note": None,
        "images": images,
        "rag": rag_color,
        "timestamp": datetime.now().isoformat()
    }
    if employee_id:
        data["employee_id"] = employee_id
        # Update last_activity_at for the user even if they are using the simulator
        supabase.table("users").update({"last_activity_at": datetime.now().isoformat()}).eq("id", employee_id).execute()
        
    response = supabase.table("updates").insert(data).execute()
    
    # Update task progress and optionally deadline
    task_update_data = {"progress": progress}
    if new_deadline:
        task_update_data["deadline"] = new_deadline
    
    if int(progress) >= 100:
        task_update_data["status"] = "Completed"
        task_update_data["actual_end_date"] = datetime.now().isoformat()
        
    supabase.table("tasks").update(task_update_data).eq("id", task_id).execute()
    
    # Notify Notification Engine
    try:
        from notifications.dispatcher import dispatch_task_event
        if int(progress) >= 100:
            dispatch_task_event(task_id, "Completed")
        elif int(progress) > 0 and int(progress) < 100:
            # We don't have exact previous state, so we just assume it's in progress/started
            dispatch_task_event(task_id, "Started")
    except Exception as e:
        import logging
        logging.error(f"Failed to dispatch task event: {e}")
        
    return response.data

def get_todays_updates():
    today = datetime.now().date().isoformat()
    response = supabase.table("updates").select("*, tasks(title, deadline, projects(id, name))").gte("timestamp", today).execute()
    return response.data

def get_upcoming_deadlines():
    today = datetime.now().date()
    tomorrow = (datetime.now() + timedelta(days=1)).date()
    response = supabase.table("tasks").select("*, projects(name)").gte("deadline", today.isoformat()).lte("deadline", tomorrow.isoformat()).neq("status", "Completed").execute()
    return response.data

def create_ticket(created_by, project_id, task_id=None, message=""):
    data = {
        "created_by": created_by,
        "project_id": project_id,
        "status": "open"
    }
    if task_id:
        data["task_id"] = task_id
    ticket_response = supabase.table("tickets").insert(data).execute()
    ticket_id = ticket_response.data[0]['id']
    
    if message:
        add_ticket_message(ticket_id, created_by, message)
    return ticket_id

def create_project_db(name, created_by=None):
    from datetime import datetime
    data = {
        "name": name,
        "status": "active",
        "created_at": datetime.now().isoformat()
    }
    if created_by:
        data["created_by"] = created_by
    resp = supabase.table("projects").insert(data).execute()
    return resp.data[0] if resp.data else None

def add_task(project_id, name, deadline=None, assigned_to=None, start_date=None, assigned_by=None, task_type="PROJECT", team_id=None):
    # Ensure project_id is never None to satisfy Supabase NOT NULL constraint
    if not project_id:
        try:
            projects = get_projects()
            if projects:
                match = next((p for p in projects if p['name'].lower() in ["general", "personal", "gei"]), None)
                project_id = match['id'] if match else projects[0]['id']
            else:
                new_proj = create_project_db("General Project")
                if new_proj:
                    project_id = new_proj['id']
        except Exception as p_err:
            import logging
            logging.error(f"Fallback project resolution error in add_task: {p_err}")

    data = {
        "project_id": project_id,
        "title": name,
        "status": "Pending",
        "task_type": task_type
    }
    if assigned_to:
        data["assigned_to"] = assigned_to
    if deadline:
        data["deadline"] = deadline
    if start_date:
        data["planned_start_date"] = start_date
    if assigned_by:
        data["assigned_by"] = assigned_by
    if team_id:
        data["team_id"] = team_id
    try:
        resp = supabase.table("tasks").insert(data).execute()
        new_task = resp.data[0] if resp.data else None
        
        # Notify Notification Engine
        if new_task:
            try:
                from notifications.dispatcher import dispatch_task_event
                dispatch_task_event(new_task['id'], "Assigned" if assigned_to else "Follow-up Created")
            except Exception as e:
                import logging
                logging.error(f"Failed to dispatch task event on create: {e}")
                
        return new_task
    except Exception as e:
        import logging
        logging.error(f"Error adding task: {e}")
        return None


def get_user_by_id(user_id: str):
    """Return user row by UUID primary key."""
    try:
        r = supabase.table("users").select("*").eq("id", user_id).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        import logging
        logging.error(f"get_user_by_id error: {e}")
        return None

def add_ticket_message(ticket_id, sender_id, message_text, image_url=None):
    data = {
        "ticket_id": ticket_id,
        "sender_id": sender_id,
        "message_text": message_text,
        "timestamp": datetime.now().isoformat()
    }
    if image_url:
        data["image_url"] = image_url
    supabase.table("ticket_messages").insert(data).execute()

def get_open_tickets():
    response = supabase.table("tickets").select("*, projects(name), tasks(title), users!created_by(name)").eq("status", "open").execute()
    result = []
    for t in response.data:
        msgs = supabase.table("ticket_messages").select("message_text, users!sender_id(name)").eq("ticket_id", t["id"]).order("timestamp", desc=False).execute()
        t["messages"] = [f"{m['users']['name']}: {m['message_text']}" for m in msgs.data] if msgs.data else []
        result.append(t)
    return result

def close_ticket(ticket_id):
    supabase.table("tickets").update({"status": "closed"}).eq("id", ticket_id).execute()

def get_user_by_telegram_id(tid):
    r = supabase.table("users").select("*").eq("telegram_id", tid).execute()
    return r.data[0] if r.data else None

def update_user_activity(tid):
    curr = datetime.now().isoformat()
    # Try updating last_activity_at; if column missing, this will fail gracefully or ignore
    try:
        supabase.table("users").update({"last_activity_at": curr}).eq("telegram_id", tid).execute()
    except Exception as e:
        import logging
        logging.warning(f"Could not update last_activity_at: {e}")

def get_user_by_name(name):
    r = supabase.table("users").select("*").ilike("name", f"%{name}%").execute()
    return r.data[0] if r.data else None

def get_tasks_for_user(user_uuid):
    # We apply project task numbering globally first to be safe, but since this is filtered,
    # it might only number the returned subset. To truly get correct project block numbers,
    # we would need to fetch all tasks. The instruction says "When fetching tasks for a project... assign numbers".
    # For now, we fetch ALL tasks to assign numbers properly, then filter.
    all_tasks = get_all_tasks(user_id=user_uuid)
    user_tasks = [t for t in all_tasks if t.get('assigned_to') == user_uuid]
    return user_tasks


def get_active_users_with_tasks():
    # Get users who have pending tasks
    tasks = supabase.table("tasks").select("assigned_to").neq("status", "Completed").execute()
    uids = list(set([t['assigned_to'] for t in tasks.data if t.get('assigned_to')]))
    if not uids: return []
    
    users = supabase.table("users").select("*").in_("id", uids).execute()
    return users.data

def complete_task(task_id):
    data = {
        "status": "Completed",
        "progress": 100,
        "actual_end_date": datetime.now().isoformat()
    }
    response = supabase.table("tasks").update(data).eq("id", task_id).execute()
    return response.data

def add_blocker(task_id, blocker_text):
    data = {
        "is_blocked": True,
        "blocker_reason": blocker_text
    }
    response = supabase.table("tasks").update(data).eq("id", task_id).execute()
    return response.data

def remove_blocker(task_id):
    data = {
        "is_blocked": False,
        "blocker_reason": None
    }
    response = supabase.table("tasks").update(data).eq("id", task_id).execute()
    return response.data

def get_task_blockers(task_id):
    # Get from tasks table
    task_res = supabase.table("tasks").select("blocker_reason").eq("id", task_id).execute()
    # Also could get from updates history
    update_res = supabase.table("updates").select("blockers").eq("task_id", task_id).neq("blockers", "None").execute()
    
    reasons = []
    if task_res.data and task_res.data[0]['blocker_reason']:
        reasons.append(task_res.data[0]['blocker_reason'])
    
    for u in update_res.data:
        if u['blockers'] not in reasons:
            reasons.append(u['blockers'])
            
    return reasons

def save_note(task_id, note_text):
    """Updates the most recent task update with a confirmed user note."""
    response = supabase.table("updates").select("id").eq("task_id", task_id).order("timestamp", desc=True).limit(1).execute()
    if response.data:
        update_id = response.data[0]['id']
        supabase.table("updates").update({"note": note_text}).eq("id", update_id).execute()
        return True
    return False

def get_task_by_name(task_name):
    # Basic partial match
    response = supabase.table("tasks").select("*, projects(name)").ilike("title", f"%{task_name}%").execute()
    return response.data

def update_task_image(task_id, images):
    """Replaces old image with new one in tasks and latest update to ensure it overrides in the report."""
    response = supabase.table("tasks").update({"attachments": images}).eq("id", task_id).execute()
    
    # Also update the latest update's image so the PDF report picks it correctly
    update_res = supabase.table("updates").select("id").eq("task_id", task_id).order("timestamp", desc=True).limit(1).execute()
    if update_res.data:
        update_id = update_res.data[0]['id']
        supabase.table("updates").update({"images": images}).eq("id", update_id).execute()
        
    return response.data

def update_task_dates(task_id, start_date=None, deadline=None):
    """Updates the start date and/or deadline of a specific task."""
    data = {}
    if start_date:
        data["planned_start_date"] = start_date
    if deadline:
        data["deadline"] = deadline
    
    if not data:
        return None
        
    response = supabase.table("tasks").update(data).eq("id", task_id).execute()
    return response.data[0] if response.data else None

def get_or_create_user_by_whatsapp(whatsapp_number):
    try:
        r = supabase.table("users").select("*").eq("whatsapp_number", whatsapp_number).execute()
        if r.data:
            return r.data[0]
            
        # User not found, create as Guest
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Creating new Guest user for {whatsapp_number}")
        
        new_user = {
            "name": f"User {whatsapp_number[-4:]}",
            "whatsapp_number": whatsapp_number,
            "role": "Guest"
        }
        create_res = supabase.table("users").insert(new_user).execute()
        return create_res.data[0] if create_res.data else None
    except Exception as e:
        import logging
        logging.error(f"get_or_create_user_by_whatsapp error: {e}")
        return None

def archive_task(task_id: str):
    response = supabase.table("tasks").update({"is_archived": True}).eq("id", task_id).execute()
    return response.data

def restore_task(task_id: str):
    response = supabase.table("tasks").update({"is_archived": False}).eq("id", task_id).execute()
    return response.data

def delete_task(task_id: str):
    response = supabase.table("tasks").delete().eq("id", task_id).execute()
    return response.data

def set_task_reminder(task_id: str, reminder_time: str):
    response = supabase.table("tasks").update({"reminder_time": reminder_time}).eq("id", task_id).execute()
    return response.data

def bulk_update_tasks(task_ids: list, update_data: dict):
    response = supabase.table("tasks").update(update_data).in_("id", task_ids).execute()
    return response.data
