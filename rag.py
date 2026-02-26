from datetime import datetime, timezone

def calculate_rag(progress, task_created_at, task_deadline, blockers, missed_updates=0):
    now = datetime.now(timezone.utc)
    
    if task_created_at and task_created_at.tzinfo is None:
        task_created_at = task_created_at.replace(tzinfo=timezone.utc)
    if task_deadline and task_deadline.tzinfo is None:
        task_deadline = task_deadline.replace(tzinfo=timezone.utc)
        
    if missed_updates > 0:
        return "RED", "No update submitted."
        
    if blockers and blockers.lower() not in ['no', 'none', 'nothing', '']:
        return "RED", f"Blocker reported: {blockers}"
    
    if task_deadline and now > task_deadline and progress < 100:
        return "RED", f"Deadline passed, progress {progress}%."
        
    if task_created_at and task_deadline:
        total_time = (task_deadline - task_created_at).total_seconds()
        elapsed_time = (now - task_created_at).total_seconds()
        if total_time > 0:
            time_elapsed_pct = (elapsed_time / total_time) * 100
            if time_elapsed_pct > 80 and progress < 80:
                return "AMBER", f"Time elapsed is {int(time_elapsed_pct)}% but progress is only {progress}%."
            if time_elapsed_pct > 50 and progress < 30:
                return "AMBER", f"Time elapsed is {int(time_elapsed_pct)}% but progress is only {progress}%."
                
    if progress == 100:
        return "GREEN", "Task completed."
        
    return "GREEN", "On track."

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
