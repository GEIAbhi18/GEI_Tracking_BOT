from whatsapp.ux import send_list_message, send_interactive_buttons

def send_main_menu(to: str, user: dict):
    """Generates and sends the main menu based on the user's role."""
    role = user.get("role", "Guest")
    
    if role == "Guest":
        rows = [
            {"id": "guest_office", "title": "🏢 Office Spaces"},
            {"id": "guest_retail", "title": "🛍️ Retail Spaces"},
            {"id": "guest_leasing", "title": "🤝 Leasing Options"},
            {"id": "guest_about", "title": "ℹ️ About Us"},
            {"id": "guest_careers", "title": "💼 Careers"}
        ]
        if user.get("original_role") == "Developer":
            rows.append({"id": "menu_admin", "title": "⚙️ System Admin (Exit Guest)"})
            
        sections = [{"title": "Explore GEI", "rows": rows}]
        return send_list_message(to, "Welcome to Good Earth Infra! 🌍\n\nWe specialize in premium commercial real estate, office & retail spaces in Gurugram.\n\nHow can we help you today?", "Explore Options", sections)

        
    rows = [
        {"id": "menu_team_tasks", "title": "📋 Team Tasks"},
        {"id": "menu_my_tasks", "title": "👤 My Personal Tasks"},
        {"id": "menu_create_task", "title": "➕ Create Task"},
        {"id": "menu_notifications", "title": "🔔 Notifications"},
        {"id": "menu_reports", "title": "📊 Reports"},
    ]
    
    if role in ["Director", "Developer"]:
        rows.append({"id": "menu_analytics", "title": "📈 Analytics"})
        
    if role == "Developer" or user.get("original_role") == "Developer":
        rows.append({"id": "menu_admin", "title": "⚙️ System Admin"})
        
    sections = [{"title": "Main Menu", "rows": rows}]
    return send_list_message(to, f"Hello {user.get('name', 'there')}! What would you like to do today?", "Open Menu", sections)

def send_task_actions(to: str, task: dict):
    """Sends the Task Actions buttons and the 'More Actions' list depending on status."""
    status = task.get("status", "Pending")
    task_id = task.get("id")
    title = task.get("title", "Task")
    
    body = f"*{title}*\nStatus: {status}\nDue: {task.get('due_date', 'N/A')}\n\nWhat would you like to do?"
    
    if task.get("task_type") == "PERSONAL":
        if task.get("is_archived"):
            buttons = [
                {"id": f"task_restore_{task_id}", "title": "Restore"},
                {"id": f"task_delete_{task_id}", "title": "Delete"}
            ]
            return send_interactive_buttons(to, f"*{title}*\nThis personal task is Archived.", buttons)
            
        buttons = [
            {"id": f"task_complete_{task_id}", "title": "Complete"},
            {"id": f"task_archive_{task_id}", "title": "Archive"}
        ]
        send_interactive_buttons(to, body, buttons)
        
        sections = [{"title": "Personal Actions", "rows": [
            {"id": f"task_remind_{task_id}", "title": "Set Reminder"},
            {"id": f"task_delete_{task_id}", "title": "Delete"},
            {"id": f"task_timeline_{task_id}", "title": "View Timeline"}
        ]}]
        return send_list_message(to, "Manage your task:", "View Actions", sections)
        
    if status == "Pending":
        buttons = [
            {"id": f"task_accept_{task_id}", "title": "Accept"},
            {"id": f"task_ignore_{task_id}", "title": "Ignore"}
        ]
        return send_interactive_buttons(to, body, buttons)
        
    if status == "Accepted":
        buttons = [
            {"id": f"task_start_{task_id}", "title": "Start Task"},
            {"id": f"task_note_{task_id}", "title": "Add Note"}
        ]
        send_interactive_buttons(to, body, buttons)
        
        # Send More Actions List
        sections = [{"title": "More Actions", "rows": [
            {"id": f"task_upload_{task_id}", "title": "Upload Attachment"},
            {"id": f"task_timeline_{task_id}", "title": "View Timeline"},
            {"id": f"task_followup_{task_id}", "title": "Create Follow-up"}
        ]}]
        return send_list_message(to, "Additional Options:", "View Actions", sections)
        
    if status == "In Progress":
        buttons = [
            {"id": f"task_complete_{task_id}", "title": "Complete"},
            {"id": f"task_note_{task_id}", "title": "Add Note"}
        ]
        send_interactive_buttons(to, body, buttons)
        
        sections = [{"title": "More Actions", "rows": [
            {"id": f"task_proof_{task_id}", "title": "Upload Proof"},
            {"id": f"task_timeline_{task_id}", "title": "View Timeline"},
            {"id": f"task_followup_{task_id}", "title": "Create Follow-up"}
        ]}]
        return send_list_message(to, "Additional Options:", "View Actions", sections)
        
    if status == "Completed":
        buttons = [
            {"id": f"task_close_{task_id}", "title": "Close Task"},
            {"id": f"task_timeline_{task_id}", "title": "View Timeline"}
        ]
        return send_interactive_buttons(to, f"*{title}*\nStatus: {status}\n\nAwaiting final closure.", buttons)
        
    # Default for closed
    buttons = [{"id": f"task_timeline_{task_id}", "title": "View Timeline"}]
    return send_interactive_buttons(to, f"*{title}*\nStatus: {status}\n\nTask is closed.", buttons)
