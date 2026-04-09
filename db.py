from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY
from datetime import datetime, timedelta

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

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
            
    return tasks

def get_projects():
    response = supabase.table("projects").select("*").order("created_at").execute()
    return response.data

def get_tasks_for_project(project_id):
    response = supabase.table("tasks").select("*").eq("project_id", project_id).execute()
    return _apply_project_task_numbers(response.data)

def get_all_tasks():
    response = supabase.table("tasks").select("*, projects(name), assigned_to_user:users!assigned_to(name)").execute()
    return _apply_project_task_numbers(response.data)

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
        task_update_data["status"] = "completed"
        task_update_data["actual_end_date"] = datetime.now().isoformat()
        
    supabase.table("tasks").update(task_update_data).eq("id", task_id).execute()
    return response.data

def get_todays_updates():
    today = datetime.now().date().isoformat()
    response = supabase.table("updates").select("*, tasks(name, deadline, projects(id, name))").gte("timestamp", today).execute()
    return response.data

def get_upcoming_deadlines():
    today = datetime.now().date()
    tomorrow = (datetime.now() + timedelta(days=1)).date()
    response = supabase.table("tasks").select("*, projects(name)").gte("deadline", today.isoformat()).lte("deadline", tomorrow.isoformat()).neq("status", "completed").execute()
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

def add_task(project_id, name, deadline=None, assigned_to=None, start_date=None):
    data = {
        "project_id": project_id,
        "name": name,
        "status": "pending"
    }
    if assigned_to:
        data["assigned_to"] = assigned_to
    if deadline:
        data["deadline"] = deadline
    if start_date:
        data["planned_start_date"] = start_date
    try:
        resp = supabase.table("tasks").insert(data).execute()
        return resp.data[0] if resp.data else None
    except Exception as e:
        import logging
        logging.error(f"Error adding task: {e}")
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
    response = supabase.table("tickets").select("*, projects(name), tasks(name), users!created_by(name)").eq("status", "open").execute()
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
    response = supabase.table("tasks").select("*, projects(name)").eq("assigned_to", user_uuid).execute()
    # We apply project task numbering globally first to be safe, but since this is filtered,
    # it might only number the returned subset. To truly get correct project block numbers,
    # we would need to fetch all tasks. The instruction says "When fetching tasks for a project... assign numbers".
    # For now, we fetch ALL tasks to assign numbers properly, then filter.
    all_tasks = get_all_tasks()
    user_tasks = [t for t in all_tasks if t.get('assigned_to') == user_uuid]
    return user_tasks

def get_active_users_with_tasks():
    # Get users who have pending tasks
    tasks = supabase.table("tasks").select("assigned_to").neq("status", "completed").execute()
    uids = list(set([t['assigned_to'] for t in tasks.data if t.get('assigned_to')]))
    if not uids: return []
    
    users = supabase.table("users").select("*").in_("id", uids).execute()
    return users.data

def complete_task(task_id):
    data = {
        "status": "completed",
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
    response = supabase.table("tasks").select("*, projects(name)").ilike("name", f"%{task_name}%").execute()
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
