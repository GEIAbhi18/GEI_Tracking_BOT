from datetime import datetime, timezone

def calculate_rag(progress, task_start_date, task_deadline, blockers, missed_updates=0):
    now = datetime.now(timezone.utc)
    
    if task_start_date and task_start_date.tzinfo is None:
        task_start_date = task_start_date.replace(tzinfo=timezone.utc)
    if task_deadline and task_deadline.tzinfo is None:
        task_deadline = task_deadline.replace(tzinfo=timezone.utc)
        
    if missed_updates > 0:
        return "RED", "No update submitted."
        
    if blockers and blockers.lower() not in ['no', 'none', 'nothing', '', 'null']:
        return "RED", f"Blocker reported: {blockers}"
    
    # If no start date or deadline, we can't calculate ratio, default to Green if no blockers
    if not task_start_date or not task_deadline:
        if progress >= 100:
            return "GREEN", "Task completed."
        return "GREEN", "On track (No timeline defined)."

    total_duration = (task_deadline - task_start_date).total_seconds()
    days_passed = (now - task_start_date).total_seconds()

    # Protect against zero duration or negative start/end
    if total_duration <= 0:
        # If today is past deadline and not 100%, it's RED
        if now > task_deadline and progress < 100:
            return "RED", "Deadline passed."
        return "GREEN", "On track."

    expected_progress = (days_passed / total_duration) * 100
    
    # Cap expected progress between 0 and 100
    if expected_progress < 0: expected_progress = 0
    if expected_progress > 100: expected_progress = 100

    if expected_progress == 0:
        return "GREEN", "On track (Just started)."

    performance_ratio = progress / expected_progress if expected_progress > 0 else 1.0

    if performance_ratio >= 0.75:
        return "GREEN", "On track."
    elif performance_ratio >= 0.5:
        return "AMBER", f"Behind schedule (Ratio: {performance_ratio:.2f})."
    else:
        return "RED", f"Critically behind (Ratio: {performance_ratio:.2f})."

def calculate_project_rag(task_rags):
    """
    Project level:
    Green -> majority tasks green
    Amber -> mixed amber/green
    Red -> any red 
    """
    if not task_rags:
        return "GREEN"
        
    if "RED" in task_rags:
        return "RED"
        
    if "AMBER" in task_rags:
        return "AMBER"
        
    # Technically if majority is green it's green, if all amber it's amber.
    return "GREEN"
