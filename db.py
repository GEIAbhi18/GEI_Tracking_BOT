from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY
from datetime import datetime, timedelta

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_projects():
    response = supabase.table("projects").select("*").order("created_at").execute()
    return response.data

def get_tasks_for_project(project_id):
    response = supabase.table("tasks").select("*").eq("project_id", project_id).execute()
    return response.data

def get_all_tasks():
    response = supabase.table("tasks").select("*, projects(name), assigned_to_user:users!assigned_to(name)").execute()
    return response.data

def save_update(task_id, progress, blockers, images, employee_id=None):
    from rag import calculate_rag
    
    task_response = supabase.table("tasks").select("created_at, deadline").eq("id", task_id).execute()
    task_data = task_response.data[0] if task_response.data else {}
    
    task_created_at = datetime.fromisoformat(task_data.get("created_at")) if task_data.get("created_at") else None
    task_deadline = datetime.fromisoformat(task_data.get("deadline")) if task_data.get("deadline") else None
    
    rag_color, _ = calculate_rag(progress, task_created_at, task_deadline, blockers, 0)
    
    data = {
        "task_id": task_id,
        "progress": progress,
        "blockers": blockers,
        "images": images,
        "rag": rag_color,
        "timestamp": datetime.now().isoformat()
    }
    if employee_id:
        data["employee_id"] = employee_id
        
    response = supabase.table("updates").insert(data).execute()
    supabase.table("tasks").update({"progress": progress}).eq("id", task_id).execute()
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

def add_task(project_id, name, deadline=None, assigned_to=None):
    data = {
        "project_id": project_id,
        "name": name,
        "status": "pending"
    }
    if assigned_to:
        data["assigned_to"] = assigned_to
    if deadline:
        data["deadline"] = deadline
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
        msgs = supabase.table("ticket_messages").select("message_text").eq("ticket_id", t["id"]).order("timestamp", desc=False).execute()
        t["messages"] = [m["message_text"] for m in msgs.data] if msgs.data else []
        result.append(t)
    return result

def close_ticket(ticket_id):
    supabase.table("tickets").update({"status": "closed"}).eq("id", ticket_id).execute()

def get_user_by_telegram_id(tid):
    r = supabase.table("users").select("*").eq("telegram_id", tid).execute()
    return r.data[0] if r.data else None

def get_tasks_for_user(user_uuid):
    response = supabase.table("tasks").select("*, projects(name)").eq("assigned_to", user_uuid).execute()
    return response.data

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

def get_task_by_name(task_name):
    # Basic partial match
    response = supabase.table("tasks").select("*, projects(name)").ilike("name", f"%{task_name}%").execute()
    return response.data
