from pydantic import BaseModel
from typing import Optional, Union

class IntentResponse(BaseModel):
    intent: str
    task_reference: Optional[str] = None
    project_name: Optional[str] = None
    progress: Optional[Union[int, float]] = None
    blocker_text: Optional[str] = None
    confidence: float
