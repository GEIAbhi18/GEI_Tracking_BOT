def get_notification_template(event_type: str, context: dict) -> str:
    """
    Returns a formatted notification message based on the event type and context.
    """
    task_title = context.get("task_title", "Unknown Task")
    creator_name = context.get("creator_name", "Someone")
    assignee_name = context.get("assignee_name", "Someone")
    due_date = context.get("due_date", "No date")
    project_name = context.get("project_name", "")

    project_str = f" in project '{project_name}'" if project_name else ""

    templates = {
        "Assigned": f"📌 You have been assigned a new task: '{task_title}'{project_str} by {creator_name}.\nDue: {due_date}",
        "Accepted": f"✅ {assignee_name} has accepted the task: '{task_title}'{project_str}.",
        "Started": f"🚀 {assignee_name} has started working on the task: '{task_title}'{project_str}.",
        "Reminder": f"⏰ Reminder: The task '{task_title}'{project_str} is due on {due_date}.",
        "Overdue": f"⚠️ Overdue: The task '{task_title}'{project_str} was due on {due_date} and is incomplete.",
        "Completed": f"🎉 {assignee_name} has marked the task '{task_title}'{project_str} as Completed.",
        "Closed": f"🔒 The task '{task_title}'{project_str} has been closed by {creator_name}.",
        "Follow-up Created": f"🔄 A follow-up task has been created for '{task_title}'{project_str}."
    }

    return templates.get(event_type, f"Notification regarding task: {task_title}")
