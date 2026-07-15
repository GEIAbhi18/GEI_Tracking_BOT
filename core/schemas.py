from pydantic import BaseModel
from typing import Optional, Union, Literal, List

class QueryFilters(BaseModel):
    range: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    assignee: Optional[str] = None
    status: Optional[str] = None
    has_blockers: Optional[bool] = None
    progress_lt: Optional[int] = None
    include_no_deadline: Optional[bool] = None

class IntentResponse(BaseModel):
    intent: str
    task_reference: Optional[str] = None
    project_name: Optional[str] = None
    target_user: Optional[str] = None
    message_type: Optional[str] = None
    progress: Optional[Union[int, float]] = None
    blocker_text: Optional[str] = None
    deadline: Optional[str] = None
    confidence: float
    query_filters: Optional[QueryFilters] = None
    assigned_to: Optional[str] = None
    is_personal: Optional[bool] = None

class MultiIntentResponse(BaseModel):
    intents: List[IntentResponse]
