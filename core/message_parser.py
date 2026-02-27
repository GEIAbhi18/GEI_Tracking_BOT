import re
from rapidfuzz import fuzz

PROJECTS = ["Top Terrace", "9TH FLOOR (CENTRIC)"]

TASK_KEYWORDS = {
    "Top Terrace": ["tile", "membrane", "malba", "slope", "solar", "waterproof", "ponding"],
    "9TH FLOOR (CENTRIC)": ["tile", "malba", "slope", "waterproof", "ponding"]
}

def detect_project(text: str) -> str:
    best_match = None
    highest_score = 0
    
    for project in PROJECTS:
        score = fuzz.partial_ratio(project.lower(), text.lower())
        if score > highest_score:
            highest_score = score
            best_match = project
            
    if highest_score >= 75:
        return best_match
    return None

def detect_task(text: str, project_name: str) -> str:
    if not project_name or project_name not in TASK_KEYWORDS:
        return None
        
    keywords = TASK_KEYWORDS[project_name]
    best_match = None
    highest_score = 0
    words = text.lower().split()
    
    for keyword in keywords:
        for word in words:
            score = fuzz.partial_ratio(keyword, word)
            if score > highest_score:
                highest_score = score
                best_match = keyword
                
    if highest_score >= 70:
        return best_match
    return None

def extract_progress(text: str):
    match = re.search(r'(\d{1,3})\s*%', text)
    if match:
        val = int(match.group(1))
        if 0 <= val <= 100:
            return val
    return None

def extract_blocker(text: str, parsed_fields: dict) -> str:
    clean_text = text
    
    # Remove project
    if parsed_fields.get("project"):
        # naive replace ignoring case
        pattern = re.compile(re.escape(parsed_fields["project"]), re.IGNORECASE)
        clean_text = pattern.sub('', clean_text)
        
    # Remove task keyword
    if parsed_fields.get("task_keyword"):
        pattern = re.compile(re.escape(parsed_fields["task_keyword"]), re.IGNORECASE)
        clean_text = pattern.sub('', clean_text)
        
    # Remove progress
    progress_val = parsed_fields.get("progress")
    if progress_val is not None:
        clean_text = re.sub(rf'{progress_val}\s*%', '', clean_text)
        
    # Extra cleanups like "done", spaces, commas
    clean_text = re.sub(r'\b(done|percent|completed)\b', '', clean_text, flags=re.IGNORECASE)
    clean_text = clean_text.replace(',', '').strip()
    
    if not clean_text:
        return None
    return ' '.join(clean_text.split())

def calculate_confidence(parsed_dict: dict) -> str:
    has_proj = bool(parsed_dict.get("project"))
    has_task = bool(parsed_dict.get("task_keyword"))
    has_prog = parsed_dict.get("progress") is not None
    
    if has_proj and has_task and has_prog:
        return "high"
    elif has_task and has_prog:
        return "medium"
    return "low"

def parse_message(text: str) -> dict:
    project = detect_project(text)
    task_keyword = detect_task(text, project)
    progress = extract_progress(text)
    
    parsed = {
        "project": project,
        "task_keyword": task_keyword,
        "progress": progress
    }
    
    blocker = extract_blocker(text, parsed)
    parsed["blocker"] = blocker
    
    confidence = calculate_confidence(parsed)
    parsed["confidence"] = confidence
    
    return parsed
