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
    
    today = datetime.now()
    
    # 1. Basic Constants
    if text == "today":
        return today.strftime("%Y-%m-%d")
    if text == "tomorrow":
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    if text in ["day after tomorrow", "next to tomorrow", "day after"]:
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")
    
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

    # Finally try generic parser if available or just return original
    try:
        # Check if it's already YYYY-MM-DD
        datetime.strptime(text, "%Y-%m-%d")
        return text
    except:
        pass

    return date_text

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
            
    # Priority 3: Query in project name
    for p in projects:
        if q_lower in p['name'].lower():
            return p
            
    return None

def resolve_task_from_list(query, tasks, last_list_ids=None, active_project_id=None):
    """
    Resolves a task from a query and a list of tasks.
    Supports active_project_id mapping to project_task_number.
    """
    if not query:
        return None
        
    q = str(query).strip().lower()
    if q.startswith("task "): q = q[5:].strip()
    q_numeric = re.search(r'(\d+)', q)
    
    # 0. Try active project mapping using project_task_number
    if q_numeric and active_project_id:
        target_number = int(q_numeric.group(1))
        # Find task with this project_task_number natively assigned
        for t in tasks:
            if t.get('project_id') == active_project_id and t.get('project_task_number') == target_number:
                return t
                
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

    # 3. Try name matching
    # Priority 1: Exact match
    for t in tasks:
        if t.get('name', '').lower() == q:
            return t
    
    # Priority 2: Starts with
    for t in tasks:
        if t.get('name', '').lower().startswith(q):
            return t
            
    # Priority 3: Contains
    for t in tasks:
        if q in t.get('name', '').lower():
            return t
            
    return None
