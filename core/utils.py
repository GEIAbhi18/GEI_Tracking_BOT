import re
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

def parse_human_date(date_text: str) -> str:
    """
    Parses human-readable date text into YYYY-MM-DD format.
    Handles: "today", "tomorrow", "day after tomorrow", "in 3 days", "after 1 week", 
    "next friday", "this friday", "12-05-2026", "2026-05-12", etc.
    """
    if not date_text:
        return None
        
    text = date_text.strip().lower()
    # Remove common filler words
    text = re.sub(r'\b(on|at|by|for|the)\b', '', text).strip()
    # Remove ordinal suffixes: 1st, 2nd, 3rd, 4th -> 1, 2, 3, 4
    text = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', text)
    text = text.strip()
    
    today = datetime.now()
    
    # 1. Basic Constants with typo handling
    if text in ["day after tomorrow", "day after tommorow", "day after tomorow", "next to tomorrow", "next to tommorow", "day after"]:
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")
    if text in ["today", "tday"]:
        return today.strftime("%Y-%m-%d")
    if text in ["tomorrow", "tommorow", "tomorow", "tomrow", "tomm", "tom"] or re.search(r'\bto?m+o+r+o+w\b', text):
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # 2. Relative Days/Weeks (e.g., "in 3 days", "after 2 weeks", "3 days after")
    # Match "3 days", "2 weeks", "in 1 month" (approx)
    match_rel = re.search(r'(\d+)\s*(day|week|month)s?', text)
    if match_rel:
        num = int(match_rel.group(1))
        unit = match_rel.group(2)
        if unit == "day":
            delta = timedelta(days=num)
        elif unit == "week":
            delta = timedelta(weeks=num)
        elif unit == "month":
            delta = timedelta(days=num * 30) # approximation
        
        # Check for "ago" or "before" (though usually deadlines are future)
        if "ago" in text or "before" in text:
            return (today - delta).strftime("%Y-%m-%d")
        else:
            return (today + delta).strftime("%Y-%m-%d")

    # 3. Specific Day of Week (e.g., "friday", "next friday", "this friday")
    days_of_week = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, 
        "friday": 4, "saturday": 5, "sunday": 6
    }
    for day_name, target_weekday in days_of_week.items():
        if day_name in text:
            current_weekday = today.weekday()
            days_ahead = target_weekday - current_weekday
            
            if "next" in text:
                if days_ahead <= 0:
                    days_ahead += 7
                days_ahead += 7 # "next friday" often means next week's friday
            elif days_ahead <= 0: 
                # e.g. today is Friday, user says "friday", or today is Sat, user says "friday"
                days_ahead += 7
                
            return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    # 4. Standard Date Formats
    # YYYY-MM-DD
    match_iso = re.search(r'\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b', text)
    if match_iso:
        return f"{match_iso.group(1)}-{int(match_iso.group(2)):02d}-{int(match_iso.group(3)):02d}"
        
    # DD-MM-YYYY or DD/MM/YYYY
    match_ddmm = re.search(r'\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b', text)
    if match_ddmm:
        try:
            return f"{match_ddmm.group(3)}-{int(match_ddmm.group(2)):02d}-{int(match_ddmm.group(1)):02d}"
        except: pass

    # Month Names Support
    months_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
    }
    
    # DD Month (e.g. 11 Mar, 11 March)
    match_dd_month = re.search(r'\b(\d{1,2})\s+([a-z]{3,})\b', text)
    if match_dd_month:
        d = int(match_dd_month.group(1))
        m_str = match_dd_month.group(2)
        if m_str in months_map:
            m = months_map[m_str]
            return f"{today.year}-{m:02d}-{d:02d}"

    # Month DD (e.g. Mar 11, March 11)
    match_month_dd = re.search(r'\b([a-z]{3,})\s+(\d{1,2})\b', text)
    if match_month_dd:
        m_str = match_month_dd.group(1)
        d = int(match_month_dd.group(2))
        if m_str in months_map:
            m = months_map[m_str]
            return f"{today.year}-{m:02d}-{d:02d}"

    # DD-MM (assumes current year)
    match_short = re.search(r'\b(\d{1,2})[-/](\d{1,2})\b', text)
    if match_short:
        try:
            return f"{today.year}-{int(match_short.group(2)):02d}-{int(match_short.group(1)):02d}"
        except: pass

    # Finally check if it's already YYYY-MM-DD
    try:
        if re.match(r'^\d{4}-\d{2}-\d{2}', text):
            return text.split('T')[0]
        datetime.strptime(text, "%Y-%m-%d")
        return text
    except:
        pass

    # Return None for unparseable text so DB receives NULL instead of invalid text syntax
    return None

def resolve_project(query, projects):
    """
    Resolves project from a query string.
    Handles: "7.", "7", "project name", "partial name"
    """
    if not query:
        return None
        
    # Clean query: "7." -> "7"
    q = str(query).strip().rstrip('.')
    
    # 1. Try index matching
    if q.isdigit():
        idx = int(q) - 1
        if 0 <= idx < len(projects):
            return projects[idx]
            
    # 2. Try partial name matching
    q_lower = q.lower()
    
    # Priority 1: Exact name match
    for p in projects:
        if p['name'].lower() == q_lower:
            return p
            
    # Priority 2: Project name starts with query
    for p in projects:
        if p['name'].lower().startswith(q_lower):
            return p
            
    return None

def format_date_human(date_str):
    """
    Formats a date string (YYYY-MM-DD or ISO) into a human-friendly format like '7th April'.
    """
    if not date_str or date_str == 'None':
        return "No deadline"
    from datetime import datetime
    try:
        sd = str(date_str).strip()
        # Extract date part if it's ISO or has time
        if 'T' in sd:
            date_part = sd.split('T')[0]
        elif ' ' in sd and len(sd) > 10:
            date_part = sd.split(' ')[0]
        else:
            date_part = sd
            
        dt = datetime.strptime(date_part, "%Y-%m-%d")
        
        day = dt.day
        if 11 <= day <= 13:
            suffix = 'th'
        else:
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
            
        return f"{day}{suffix} {dt.strftime('%B')}"
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Date formatting failed for {date_str}: {e}")
        return str(date_str)[:10]

def resolve_task_from_list(query, tasks, last_list_ids=None, active_project_id=None):
    """
    Resolves a task from a query and a list of tasks.
    Supports active_project_id mapping to project_task_number.
    
    AMBIGUITY HANDLING:
    When a partial name matches multiple tasks with similar relevance,
    this function returns None and stores the ambiguous matches in
    resolve_task_from_list.ambiguous_matches so the caller can ask the user.
    """
    # Reset ambiguous matches on every call
    resolve_task_from_list.ambiguous_matches = []

    if not query:
        return None
        
    q = str(query).strip().lower()
    if q.startswith("task "): q = q[5:].strip()
    q_numeric = re.search(r'(\d+)', q)
    
    # 0. Try X-Y format (ProjectNumber-TaskNumber)
    match_xy = re.match(r'^(\d+)[-.](\d+)$', q)
    if match_xy:
        proj_idx = int(match_xy.group(1))
        task_idx = int(match_xy.group(2))
        
        from core.context_manager import get_context
        ctx = get_context(tasks[0].get('id') if tasks else None) # Dummy context fetch
        # Actually we need the grouped structure here. 
        # But we can simulate it if we know the project order.
        # For simplicity, we'll try to find tasks that match this project index if we have it in a shared map.
        # However, a cleaner way is to resolve it based on the sorted projects.
        
        from collections import defaultdict
        grouped = defaultdict(list)
        for t in tasks:
            p_obj = t.get('projects')
            p_name = p_obj.get('name', 'Unknown') if isinstance(p_obj, dict) else 'Unknown'
            grouped[p_name].append(t)
            
        # Use database creation order to match the display list (Feature Fix)
        from db import get_projects
        all_projects = get_projects()
        p_order_map = {p['name']: i for i, p in enumerate(all_projects)}
        
        sorted_projects = sorted(grouped.keys(), key=lambda x: p_order_map.get(x, 999))
        
        if 1 <= proj_idx <= len(sorted_projects):
            target_p_name = sorted_projects[proj_idx - 1]
            p_tasks = sorted(grouped[target_p_name], key=lambda x: x.get('project_task_number', 0))
            if 1 <= task_idx <= len(p_tasks):
                return p_tasks[task_idx - 1]

    # 1. Try list index matching
    if q_numeric and last_list_ids:
        idx = int(q_numeric.group(1)) - 1
        if 0 <= idx < len(last_list_ids):
            target_id = last_list_ids[idx]
            return next((t for t in tasks if t['id'] == target_id), None)
            
    # 2. Try direct index in provided tasks list
    if q.isdigit():
        idx = int(q) - 1
        if 0 <= idx < len(tasks):
            return tasks[idx]

    # 3. Try name matching WITH ambiguity detection
    # Priority 1: Exact match (no ambiguity possible)
    for t in tasks:
        if t.get('name', '').lower() == q:
            return t
    
    # Priority 2: Starts with — check for multiple matches
    starts_with = [t for t in tasks if t.get('name', '').lower().startswith(q)]
    if len(starts_with) == 1:
        return starts_with[0]
    elif len(starts_with) > 1:
        # If active_project_id is set, try to narrow down
        if active_project_id:
            filtered = [t for t in starts_with if t.get('project_id') == active_project_id]
            if len(filtered) == 1:
                return filtered[0]
        # AMBIGUOUS — store for caller to handle
        resolve_task_from_list.ambiguous_matches = starts_with
        logger.info(f"Ambiguous task match for '{query}': {[t.get('name') for t in starts_with]}")
        return None
            
    # Priority 3: Contains — check for multiple matches
    contains = [t for t in tasks if q in t.get('name', '').lower()]
    if len(contains) == 1:
        return contains[0]
    elif len(contains) > 1:
        if active_project_id:
            filtered = [t for t in contains if t.get('project_id') == active_project_id]
            if len(filtered) == 1:
                return filtered[0]
        # AMBIGUOUS — store for caller to handle
        resolve_task_from_list.ambiguous_matches = contains
        logger.info(f"Ambiguous task match for '{query}': {[t.get('name') for t in contains]}")
        return None
            
    return None

# Initialize the class attribute
resolve_task_from_list.ambiguous_matches = []
